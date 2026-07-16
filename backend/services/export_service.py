"""Export service: generate ZIP package with all task assets."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import get_config
from models import Task
from repositories import JsonTaskRepository


def _compute_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _build_manifest(task: Task, files: list[dict]) -> dict:
    grade_val = getattr(task.config.grade, "value", str(task.config.grade)) if hasattr(task.config.grade, "value") else str(task.config.grade)
    grade_labels = {"grade_7": "七年级", "grade_8": "八年级", "grade_9": "九年级"}
    return {
        "task_id": task.task_id,
        "task_name": task.task_name,
        "grade": grade_val,
        "grade_label": grade_labels.get(grade_val, "七年级"),
        "package_version": "v1.0",
        "script_version": task.script.script_version if task.script else "none",
        "image_version": task.image.prompt_version if task.image else "none",
        "audio_version": task.audio.prompt_version if task.audio else "none",
        "question_version": task.questions.prompt_version if task.questions else "none",
        "evaluation_version": task.evaluation.evaluation_version if task.evaluation else "none",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "teacher_confirmed": True,
        "vocabulary_constraint_source": getattr(task.config, "vocabulary_constraint_source", "user"),
        "target_pattern_source": getattr(task.config, "target_pattern_source", "user"),
        "required_vocabulary": task.config.required_vocabulary,
        "effective_vocabulary": task.config.effective_vocabulary or [],
        "target_patterns": task.config.target_patterns,
        "effective_target_patterns": task.config.effective_target_patterns or [],
        "files": files,
    }


def generate_export_zip(task_id: str) -> tuple[bytes, str, int]:
    """Generate ZIP package for the given task.

    Returns:
        (zip_bytes, suggested_filename, zip_size)
    Raises:
        FileNotFoundError, ValueError
    """
    repo = JsonTaskRepository()
    task = repo.get_task(task_id)
    if task is None:
        raise ValueError(f"任务 {task_id} 不存在")

    cfg = get_config()
    assets_root = Path(cfg.get("assets", {}).get("rootDir", "storage")).resolve()

    buf = io.BytesIO()
    files_added: list[dict] = []

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:

        # 1. Script
        if task.script:
            script_text = json.dumps(task.script.model_dump(), ensure_ascii=False, indent=2)
            script_bytes = script_text.encode("utf-8")
            zf.writestr("script.txt", script_bytes)
            files_added.append({
                "name": "script.txt",
                "type": "script",
                "size": len(script_bytes),
                "sha256": _compute_sha256(script_bytes),
            })

        # 2. Image
        if task.image and task.image.image_url:
            rel = task.image.image_url.lstrip("/")
            if rel.startswith("assets/"):
                rel = rel[len("assets/"):]
            img_path = (assets_root / rel).resolve()
            try:
                img_path.relative_to(assets_root)
            except ValueError:
                alt = assets_root / Path(task.image.image_url).name
                if alt.exists():
                    img_path = alt
            if img_path.exists():
                img_bytes = img_path.read_bytes()
                ext = img_path.suffix or ".png"
                zf.writestr(f"image{ext}", img_bytes)
                files_added.append({
                    "name": f"image{ext}",
                    "type": "image",
                    "size": len(img_bytes),
                    "sha256": _compute_sha256(img_bytes),
                })

        # 3. Audio
        if task.audio and task.audio.audio_url:
            rel = task.audio.audio_url.lstrip("/")
            if rel.startswith("assets/"):
                rel = rel[len("assets/"):]
            aud_path = (assets_root / rel).resolve()
            try:
                aud_path.relative_to(assets_root)
            except ValueError:
                alt = assets_root / Path(task.audio.audio_url).name
                if alt.exists():
                    aud_path = alt
            if aud_path.exists():
                aud_bytes = aud_path.read_bytes()
                ext = aud_path.suffix or ".mp3"
                zf.writestr(f"audio{ext}", aud_bytes)
                files_added.append({
                    "name": f"audio{ext}",
                    "type": "audio",
                    "size": len(aud_bytes),
                    "sha256": _compute_sha256(aud_bytes),
                })

        # 4. Questions
        if task.questions:
            q_json = json.dumps(task.questions.model_dump(), ensure_ascii=False, indent=2)
            q_bytes = q_json.encode("utf-8")
            zf.writestr("questions.json", q_bytes)
            files_added.append({
                "name": "questions.json",
                "type": "questions",
                "size": len(q_bytes),
                "sha256": _compute_sha256(q_bytes),
            })

        # 5. Report
        if task.evaluation:
            r_json = json.dumps(task.evaluation.model_dump(), ensure_ascii=False, indent=2)
            r_bytes = r_json.encode("utf-8")
            zf.writestr("report.json", r_bytes)
            files_added.append({
                "name": "report.json",
                "type": "report",
                "size": len(r_bytes),
                "sha256": _compute_sha256(r_bytes),
            })

        # 6. Manifest
        manifest = _build_manifest(task, files_added)
        m_json = json.dumps(manifest, ensure_ascii=False, indent=2)
        m_bytes = m_json.encode("utf-8")
        zf.writestr("manifest.json", m_bytes)
        files_added.append({
            "name": "manifest.json",
            "type": "manifest",
            "size": len(m_bytes),
            "sha256": _compute_sha256(m_bytes),
        })

    zip_bytes = buf.getvalue()

    # Sanitized filename
    task_name_safe = task.task_name.replace("/", "-").replace("\\", "-")[:30]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{task.task_id}_{task_name_safe}_素材包_{ts}.zip"

    return zip_bytes, filename, len(zip_bytes)


def sanitize_filename(name: str) -> str:
    """Remove Windows-illegal characters from filename."""
    illegal = r'[\\/:*?"<>|]'
    import re
    name = re.sub(illegal, '', name)
    name = name.strip()
    if not name:
        name = "export"
    if not name.lower().endswith('.zip'):
        name += '.zip'
    # Prevent .zip.zip
    name = re.sub(r'\.zip\.zip$', '.zip', name, flags=re.IGNORECASE)
    # Truncate to safe length
    if len(name) > 200:
        name = name[:196] + '.zip'
    return name
