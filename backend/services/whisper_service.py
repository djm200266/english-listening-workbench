"""
Whisper ASR service. Loads model once, transcribes audio files.

Returns structured transcription with segments, timestamps, and language.
Never returns empty text as success.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import get_config


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_python() -> str:
    return get_config().get("whisper", {}).get("pythonPath", "python")


def _get_model() -> str:
    return get_config().get("whisper", {}).get("model", "base.en")


def _get_timeout() -> int:
    return int(get_config().get("whisper", {}).get("timeoutSec", 60))


def _assets_dir(task_id: str) -> Path:
    root = get_config().get("assets", {}).get("rootDir", "storage")
    d = Path(root) / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


class WhisperError(Exception):
    def __init__(self, message: str, stderr: str = "", exit_code: int = -1) -> None:
        super().__init__(message)
        self.stderr = stderr
        self.exit_code = exit_code


class WhisperTranscription:
    def __init__(
        self,
        text: str,
        segments: list[dict[str, Any]],
        language: str,
        asr_model: str,
        source_audio_path: str,
        latency_sec: float,
        transcript_path: str,
    ) -> None:
        self.text = text
        self.segments = segments
        self.language = language
        self.asr_model = asr_model
        self.source_audio_path = source_audio_path
        self.latency_sec = latency_sec
        self.transcript_path = transcript_path


def transcribe(audio_path: str, task_id: str, *,
               model: str | None = None,
               language: str = "en") -> WhisperTranscription:
    """
    Transcribe an audio file using Whisper via subprocess.

    Uses a standalone Python script to avoid loading Whisper in the FastAPI process.
    Returns WhisperTranscription with full text, segments, and timestamps.

    Raises WhisperError on any failure.
    """
    if not os.path.exists(audio_path):
        raise WhisperError(f"音频文件不存在: {audio_path}")

    use_model = model or _get_model()
    python_exe = _get_python()
    start = __import__("time").perf_counter()

    # Write a temporary Python script that loads Whisper and transcribes
    script_content = f'''
import json, sys, os
audio_path = {json.dumps(os.path.abspath(audio_path))}
model_name = {json.dumps(use_model)}
lang = {json.dumps(language)}

try:
    import whisper
except ImportError:
    print(json.dumps({{"error": "Whisper not installed in this Python environment"}}))
    sys.exit(1)

try:
    model = whisper.load_model(model_name)
    result = model.transcribe(audio_path, language=lang)
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
    sys.exit(1)

print(json.dumps({{
    "text": result["text"].strip(),
    "segments": result.get("segments", []),
    "language": result.get("language", lang),
}}))
'''

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(script_content)
        script_path = f.name

    try:
        proc = subprocess.run(
            [python_exe, script_path],
            capture_output=True,
            text=True,
            timeout=_get_timeout(),
        )
    except subprocess.TimeoutExpired:
        os.unlink(script_path)
        raise WhisperError(
            f"Whisper 转写超时（{_get_timeout()}秒）。",
            exit_code=-1,
        )
    except FileNotFoundError:
        os.unlink(script_path)
        raise WhisperError(
            f"找不到 Python ({python_exe})。请确认 Whisper Python 环境路径正确。",
            exit_code=-1,
        )
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass

    if proc.returncode != 0:
        raise WhisperError(
            f"Whisper 退出码 {proc.returncode}。",
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )

    # Parse output
    stdout = proc.stdout.strip()
    if not stdout:
        raise WhisperError("Whisper 返回空输出。", stderr=proc.stderr)

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        raise WhisperError(
            f"Whisper 输出不是合法 JSON: {stdout[:300]}",
            stderr=proc.stderr,
        )

    if "error" in data:
        raise WhisperError(
            f"Whisper 错误: {data['error']}",
            stderr=proc.stderr,
        )

    text = data.get("text", "").strip()
    if not text:
        raise WhisperError(
            "Whisper 转写结果为空。",
            stderr=json.dumps(data, ensure_ascii=False),
        )

    latency = __import__("time").perf_counter() - start

    # Save transcript files
    assets = _assets_dir(task_id)
    asr_dir = assets / "asr_output"
    asr_dir.mkdir(parents=True, exist_ok=True)

    txt_path = str(asr_dir / "dialogue_v1.txt")
    json_path = str(asr_dir / "dialogue_v1.json")

    Path(txt_path).write_text(text, encoding="utf-8")
    Path(json_path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return WhisperTranscription(
        text=text,
        segments=data.get("segments", []),
        language=data.get("language", "en"),
        asr_model=use_model,
        source_audio_path=audio_path,
        latency_sec=round(latency, 2),
        transcript_path=txt_path,
    )
