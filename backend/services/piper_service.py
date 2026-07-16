"""
Piper TTS service. Generates per-turn WAV segments, then merges with pauses.

Uses subprocess (no shell=True, array args, timeout, capture stderr/stdout).
Only processes confirmed DialogueScript from the repository.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import get_config
from models import DialogueScript, AudioAsset, AssetStatus


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_piper_exe() -> str:
    cfg = get_config().get("piper", {})
    exe = cfg.get("executable", "piper")
    # Fallback: try piper on PATH
    if not os.path.exists(exe):
        exe = "piper"
    return exe


def _get_voice_path(voice_name: str) -> str:
    voice_dir = get_config().get("piper", {}).get("voice_dir", "")
    candidate = os.path.join(voice_dir, f"{voice_name}.onnx")
    if os.path.exists(candidate):
        return candidate
    return candidate  # let piper report the error


def _get_pause_seconds() -> float:
    return float(get_config().get("piper", {}).get("pauseSeconds", 0.4))


def _get_timeout() -> int:
    return int(get_config().get("piper", {}).get("timeoutSec", 30))


def _assets_dir(task_id: str) -> Path:
    root = get_config().get("assets", {}).get("rootDir", "storage")
    d = Path(root) / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


class PiperError(Exception):
    def __init__(self, message: str, stderr: str = "", exit_code: int = -1) -> None:
        super().__init__(message)
        self.stderr = stderr
        self.exit_code = exit_code


def _speak(text: str, voice_name: str, output_path: str, speech_rate: str = "normal") -> None:
    """
    Generate a single WAV using Piper.

    Args:
        text: Input text to synthesize
        voice_name: e.g. 'en_US-lessac-medium'
        output_path: Path for output WAV
        speech_rate: 'slow' or 'normal' → maps to Piper --length_scale
    """
    exe = _get_piper_exe()
    voice_path = _get_voice_path(voice_name)
    config_path = voice_path + ".json"

    if not os.path.exists(voice_path):
        raise PiperError(
            f"Piper 音色文件不存在: {voice_path}。请确认音色已下载。",
            exit_code=-1,
        )

    # Rate mapping: Piper uses --length_scale (1.0=normal, >1.0=slower)
    length_scale = "1.3" if speech_rate == "slow" else "1.0"

    cmd = [
        exe,
        "--model", voice_path,
        "--config", config_path,
        "--length_scale", length_scale,
        "--output_file", output_path,
    ]

    try:
        proc = subprocess.run(
            cmd,
            input=text,
            capture_output=True,
            text=True,
            timeout=_get_timeout(),
            # No shell=True
        )
    except subprocess.TimeoutExpired:
        raise PiperError(
            f"Piper 超时（{_get_timeout()}秒）。句子: {text[:80]}",
            exit_code=-1,
        )
    except FileNotFoundError:
        raise PiperError(
            f"找不到 Piper 可执行文件 ({exe})。请确认 Piper 已安装。",
            exit_code=-1,
        )

    if proc.returncode != 0:
        raise PiperError(
            f"Piper 退出码 {proc.returncode}: {proc.stderr[:300]}",
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise PiperError(
            f"Piper 未生成有效音频文件: {output_path}",
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )


def _create_silence_wav(duration_sec: float, sample_rate: int, output_path: str) -> None:
    """Create a WAV file containing silence of given duration."""
    import struct
    num_samples = int(sample_rate * duration_sec)
    with wave.open(output_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(b'\x00' * (num_samples * 2))


def _merge_wavs(input_paths: list[str], output_path: str) -> None:
    """Concatenate WAV files into one. All must have same sample rate/channels/width."""
    if not input_paths:
        raise PiperError("没有音频片段可供合并。")

    # Read params from first file
    with wave.open(input_paths[0], "rb") as ref:
        params = ref.getparams()

    with wave.open(output_path, "wb") as out:
        out.setparams(params)
        for path in input_paths:
            with wave.open(path, "rb") as wf:
                if wf.getparams()[:3] != params[:3]:
                    raise PiperError(f"音频参数不匹配: {path}")
                out.writeframes(wf.readframes(wf.getnframes()))


def _wav_duration_sec(path: str) -> float:
    with wave.open(path, "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def _get_sample_rate(wav_path: str) -> int:
    with wave.open(wav_path, "rb") as wf:
        return wf.getframerate()


class PiperGenerationResult:
    def __init__(
        self,
        audio_id: str,
        output_path: str,
        duration_sec: float,
        segment_count: int,
        voice_a: str,
        voice_b: str,
        speech_rate: str,
        pause_seconds: float,
        source_script_version: str,
    ) -> None:
        self.audio_id = audio_id
        self.output_path = output_path
        self.duration_sec = duration_sec
        self.segment_count = segment_count
        self.voice_a = voice_a
        self.voice_b = voice_b
        self.speech_rate = speech_rate
        self.pause_seconds = pause_seconds
        self.source_script_version = source_script_version


def generate_audio(script: DialogueScript, task_id: str, *,
                   speech_rate: str = "normal",
                   pause_seconds: float | None = None) -> PiperGenerationResult:
    """
    Generate audio for a confirmed script.

    1. Per-turn TTS via Piper (A→lessac, B→ryan)
    2. Insert silence pauses between turns
    3. Merge into dialogue_v{script_version}.wav

    Raises PiperError on any failure. No partial success — all or nothing.
    """
    if script.status != "confirmed":
        raise PiperError("脚本未确认，无法生成音频。请先确认脚本。")

    cfg = get_config().get("piper", {})
    voices = cfg.get("voices", {})
    voice_a = voices.get("female", "en_US-lessac-medium")
    voice_b = voices.get("male", "en_US-ryan-medium")
    pause = pause_seconds if pause_seconds is not None else _get_pause_seconds()

    assets = _assets_dir(task_id)
    segments_dir = assets / "audio_segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    voice_map = {"A": voice_a, "B": voice_b}

    # Step 1: Generate per-turn WAVs
    segment_paths: list[str] = []
    for turn in script.dialogue:
        voice = voice_map.get(turn.speaker_id, voice_a)
        seg_path = str(segments_dir / f"turn_{turn.turn_id:02d}_{turn.speaker_id}.wav")
        try:
            _speak(turn.text, voice, seg_path, speech_rate)
        except PiperError:
            # Clean up any segments already created
            for p in segment_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass
            raise
        segment_paths.append(seg_path)

    # Step 2: Build merge list with silence pauses
    merge_list: list[str] = []
    sample_rate = _get_sample_rate(segment_paths[0])
    silence_path = str(segments_dir / "_silence.wav")
    _create_silence_wav(pause, sample_rate, silence_path)

    for i, seg_path in enumerate(segment_paths):
        merge_list.append(seg_path)
        if i < len(segment_paths) - 1:
            merge_list.append(silence_path)

    # Step 3: Merge
    script_ver = script.script_version.replace(".", "_")
    output_path = str(assets / f"dialogue_{script_ver}.wav")
    _merge_wavs(merge_list, output_path)

    # Step 4: Calculate duration
    duration = _wav_duration_sec(output_path)

    # Clean up silence temp
    try:
        os.unlink(silence_path)
    except OSError:
        pass

    audio_id = f"AUDIO_{task_id}_v{script.script_version}"

    return PiperGenerationResult(
        audio_id=audio_id,
        output_path=output_path,
        duration_sec=round(duration, 2),
        segment_count=len(segment_paths),
        voice_a=voice_a,
        voice_b=voice_b,
        speech_rate=speech_rate,
        pause_seconds=pause,
        source_script_version=script.script_version,
    )


def build_audio_asset(result: PiperGenerationResult, task_id: str) -> AudioAsset:
    """Build an AudioAsset model from generation result."""
    now = _now_iso()
    # Make path relative for URL serving
    assets_root = get_config().get("assets", {}).get("rootDir", "storage")
    rel_path = os.path.relpath(result.output_path, assets_root).replace("\\", "/")
    return AudioAsset(
        audio_id=result.audio_id,
        audio_url=f"/assets/{rel_path}",
        audio_duration_actual_sec=result.duration_sec,
        audio_source_script_version=result.source_script_version,
        speaker_profiles={
            "A": result.voice_a,
            "B": result.voice_b,
            "speech_rate": result.speech_rate,
            "pause_seconds": result.pause_seconds,
        },
        generation_status=AssetStatus.SUCCESS,
        is_outdated=False,
        model_name="Piper TTS",
        model_version="1.0",
        prompt_version="v1.0",
        generation_latency_ms=0,
        estimated_cost=0.0,
    )
