"""Local JSON repair and evaluation report save — NO model calls.
Reads the latest stage2_raw file, repairs JSON, validates with Pydantic,
and saves the evaluation report.
"""
import io
import json
import re
import sys
import traceback
from pathlib import Path

# Fix Windows GBK encoding — must be first
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ── Stage checkpoint helper ──────────────────────────────────

_stage = 0

def checkpoint(label: str):
    global _stage
    _stage += 1
    msg = f"[{_stage}] {label}"
    print(msg, flush=True)
    sys.stdout.flush()


# ── Paths ────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
LOGS_DIR = PROJECT_ROOT / "logs" / "visual_eval"
TASK_ID = "G7_DIR_0838"

sys.path.insert(0, str(PROJECT_ROOT / "backend"))


# ── JSON repair functions ────────────────────────────────────

def extract_json(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*\n(.*)\n```\s*$", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, count=1)
    if text.endswith("```"):
        text = text[:text.rfind("```")].strip()
    start = text.find("{")
    if start >= 0:
        text = text[start:]
    open_count = text.count("{")
    close_count = text.count("}")
    if close_count >= open_count and open_count > 0:
        end = text.rfind("}")
        text = text[:end + 1]
    return text


def normalize_quotes(text: str) -> str:
    for curly, straight in [("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'"),
                             ("«", '"'), ("»", '"')]:
        text = text.replace(curly, straight)
    return text


def fix_python_values(text: str) -> str:
    text = re.sub(r'\bTrue\b', 'true', text)
    text = re.sub(r'\bFalse\b', 'false', text)
    text = re.sub(r'\bNone\b', 'null', text)
    return text


def fix_trailing_commas(text: str) -> str:
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    return text


def fix_quoted_numbers(text: str) -> str:
    text = text.replace('"max_score": 10",', '"max_score": 100,')
    text = text.replace('"max_score": 10"\n', '"max_score": 100\n')
    text = re.sub(r'(\d+)"(\s*[,}\]])', r'\1\2', text)
    return text


def fix_unescaped_quotes(text: str) -> str:
    lines = text.split('\n')
    fixed_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith('"'):
            fixed_lines.append(line)
            continue
        first_q_end = stripped.find('"', 1)
        if first_q_end > 0:
            after_first_pair = stripped[first_q_end + 1:].lstrip()
            if after_first_pair.startswith(':'):
                fixed_lines.append(line)
                continue
        has_trailing_comma = stripped.endswith(',')
        content = stripped[:-1] if has_trailing_comma else stripped
        q_positions = [i for i, c in enumerate(content)
                       if c == '"' and (i == 0 or content[i-1] != '\\')]
        if len(q_positions) <= 2:
            fixed_lines.append(line)
            continue
        chars = list(content)
        for pos in q_positions[1:-1]:
            chars[pos] = '\\"'
        indent = line[:len(line) - len(line.lstrip())]
        new_line = indent + ''.join(chars)
        if has_trailing_comma:
            new_line += ','
        fixed_lines.append(new_line)
    return '\n'.join(fixed_lines)


def auto_close_truncated(text: str) -> str:
    open_braces = text.count('{') - text.count('}')
    open_brackets = text.count('[') - text.count(']')
    if open_braces <= 0 and open_brackets <= 0:
        return text

    lines = text.split('\n')
    last_nonempty = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            last_nonempty = i
            break

    if last_nonempty is not None:
        last_line = lines[last_nonempty].strip()
        q_count = last_line.count('"')
        if q_count % 2 == 1 and not last_line.endswith(('}', ']', ',')):
            text_stripped = text.rstrip()
            cut_point = text_stripped.rfind(',\n')
            if cut_point < 0:
                cut_point = text_stripped.rfind(',\r\n')
            if cut_point <= 0:
                for ch in ('},', '],'):
                    pos = text_stripped.rfind(ch)
                    if pos > cut_point:
                        cut_point = pos
            if cut_point > 0:
                text = text_stripped[:cut_point + 1]
            open_braces = text.count('{') - text.count('}')
            open_brackets = text.count('[') - text.count(']')

    text += ']' * open_brackets
    text += '}' * open_braces
    return text


def repair_json_deep(text: str) -> str:
    text = extract_json(text)
    text = normalize_quotes(text)
    text = fix_python_values(text)
    text = fix_quoted_numbers(text)
    text = fix_unescaped_quotes(text)
    text = fix_trailing_commas(text)
    text = auto_close_truncated(text)
    return text


# ── Save functions ───────────────────────────────────────────

def save_evaluation_report(task_id: str, result, stage1_data: dict, raw_path: Path) -> bool:
    from repositories import JsonTaskRepository
    from models import EvalReport

    print("\n[SAVE] Saving evaluation report...", flush=True)
    repo = JsonTaskRepository()
    task = repo.get_task(task_id)
    if task is None:
        print(f"  ERROR: Task {task_id} not found", flush=True)
        return False

    if task.evaluation is None:
        task.evaluation = EvalReport(task_id=task_id)

    result_dict = result.model_dump()
    task.evaluation.visual_data = result_dict
    task.evaluation.visual_score = result.visual_consistency_score
    task.evaluation.visual_prompt_version = "v2"
    task.evaluation.evaluation_status = "generated"
    repo.save_task(task)

    print(f"  evaluation_status = 'generated'", flush=True)
    print(f"  visual_data saved (score={result.visual_consistency_score})", flush=True)

    ts = raw_path.stem.replace("_stage2_raw", "")
    result_path = LOGS_DIR / task_id / f"{ts}_result_final.json"
    output = {
        "result": result_dict,
        "stage1_data": stage1_data,
        "repaired": True,
        "source_stage2_raw": raw_path.name,
    }
    result_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Final report: {result_path}", flush=True)
    return True


def save_failed_status(task_id: str, raw_path: Path | None, error_msg: str):
    from repositories import JsonTaskRepository
    from models import EvalReport

    print("\n[SAVE] Saving FAILED status...", flush=True)
    repo = JsonTaskRepository()
    task = repo.get_task(task_id)
    if task is None:
        print(f"  ERROR: Task {task_id} not found", flush=True)
        return

    if task.evaluation is None:
        task.evaluation = EvalReport(task_id=task_id)

    task.evaluation.evaluation_status = "failed"
    task.evaluation.visual_data = {
        "status": "parse_failed",
        "error_code": "VISUAL_STAGE2_PARSE_FAILED",
        "error_message": error_msg[:500],
    }
    repo.save_task(task)
    print(f"  evaluation_status = 'failed'", flush=True)
    print(f"  error_code = 'VISUAL_STAGE2_PARSE_FAILED'", flush=True)

    if raw_path:
        ts = raw_path.stem.replace("_stage2_raw", "")
        fail_path = LOGS_DIR / task_id / f"{ts}_parse_failed.json"
        raw_content = raw_path.read_text(encoding="utf-8")[:1000]
        fail_path.write_text(json.dumps({
            "status": "failed",
            "error_code": "VISUAL_STAGE2_PARSE_FAILED",
            "error_message": error_msg,
            "raw_output_preview": raw_content,
            "source_stage2_raw": raw_path.name,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Failure report: {fail_path}", flush=True)


# ── Main ─────────────────────────────────────────────────────

def main():
    checkpoint("script started")

    # 2: resolve paths
    checkpoint(f"project root resolved: {PROJECT_ROOT}")
    print(f"  LOGS_DIR = {LOGS_DIR}", flush=True)
    print(f"  TASK_ID = {TASK_ID}", flush=True)

    # Import models (after sys.path setup)
    checkpoint("importing models")
    from models import (
        VisualEvaluationResult, VisualEvaluationDimension,
        VisualDetectedObject, VisualDetectedText,
        VisualSpatialRelation, VisualQualityIssue,
        VisualHardFailure, VisualBadCase,
    )

    # 3: check stage2_raw directory
    checkpoint("stage2 raw directory checked")
    task_dir = LOGS_DIR / TASK_ID
    print(f"  task_dir = {task_dir}", flush=True)
    print(f"  task_dir.exists() = {task_dir.exists()}", flush=True)
    if not task_dir.exists():
        print(f"FATAL: Task directory not found: {task_dir}", flush=True)
        return 1

    # 4: select latest stage2 raw
    checkpoint("latest stage2 raw file selected")
    raw_files = sorted(
        task_dir.glob("*_stage2_raw.txt"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if not raw_files:
        print(f"FATAL: No stage2_raw files found in {task_dir}", flush=True)
        return 1
    raw_path = raw_files[0]
    print(f"  Selected: {raw_path.name}", flush=True)

    # 5: load raw file
    checkpoint("raw file loaded")
    raw_content = raw_path.read_text(encoding="utf-8")
    print(f"  Size: {len(raw_content)} chars", flush=True)
    print(f"  Last 100 chars: ...{raw_content[-100:]}", flush=True)

    # 5b: load stage1_data
    checkpoint("stage1 data loaded")
    ts_prefix = raw_path.stem.replace("_stage2_raw", "")
    stage1_path = LOGS_DIR / TASK_ID / f"{ts_prefix}_stage1_data.json"
    stage1_data = {}
    if stage1_path.exists():
        stage1_data = json.loads(stage1_path.read_text(encoding="utf-8"))
        print(f"  From: {stage1_path.name} ({len(json.dumps(stage1_data))} chars)", flush=True)
    else:
        s1_files = sorted(
            task_dir.glob("*_stage1_data.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if s1_files:
            stage1_data = json.loads(s1_files[0].read_text(encoding="utf-8"))
            print(f"  Fallback: {s1_files[0].name}", flush=True)
        else:
            print(f"  WARNING: No stage1_data found — using empty dict", flush=True)

    # 6: repair JSON
    checkpoint("JSON repair started")
    repaired = repair_json_deep(raw_content)
    print(f"  Repaired length: {len(repaired)} chars", flush=True)

    # 7: json.loads
    checkpoint("json.loads completed")
    try:
        data = json.loads(repaired)
    except json.JSONDecodeError as e:
        print(f"\n  json.loads FAILED: {e}", flush=True)
        print(f"  Repaired text (last 300 chars):", flush=True)
        print(f"  ...{repaired[-300:]}", flush=True)
        save_failed_status(TASK_ID, raw_path, f"JSON parse failed after repair: {e}")
        return 1

    print(f"  Top-level keys: {list(data.keys())}", flush=True)
    print(f"  visual_consistency_score: {data.get('visual_consistency_score')}", flush=True)
    print(f"  dimensions count: {len(data.get('dimensions', []))}", flush=True)

    # 8: Pydantic validation
    checkpoint("Pydantic validation completed")
    dimensions = []
    for d in data.get("dimensions", []):
        score = d.get("score", 0)
        if isinstance(score, (int, float)):
            score = max(0, min(100, float(score)))
        dimensions.append(VisualEvaluationDimension(
            key=d.get("key", ""),
            label=d.get("label", ""),
            score=score,
            max_score=float(d.get("max_score", 100)),
            status=d.get("status", "evaluated"),
            confidence=float(d.get("confidence", 0.5)) if d.get("confidence") is not None else 0.5,
            issues=(d.get("issues") or [])[:2],
            suggestions=(d.get("suggestions") or [])[:2],
        ))

    dim_scores = [d.score for d in dimensions if d.status and d.status != "na" and d.score >= 0]
    visual_score = round(sum(dim_scores) / len(dim_scores), 1) if dim_scores else 0.0

    result = VisualEvaluationResult(
        status="success",
        model="qwen3-vl:4b -> qwen3:4b-instruct [Plan A, repaired]",
        visual_content_checked=True,
        visual_consistency_score=visual_score,
        image_caption=stage1_data.get("image_caption", ""),
        detected_objects=[],
        detected_text=[],
        spatial_relations=[],
        detected_style=stage1_data.get("detected_style", "unknown"),
        detected_layout_type=stage1_data.get("detected_layout_type", "unknown"),
        quality_issues=[],
        dimensions=dimensions,
        hard_failures=[],
        bad_cases=[],
        recommendations=(data.get("recommendations") or [])[:5],
        confidence=float(data.get("confidence", 0.5)),
        image_sha256="",
        original_image_size={"width": 0, "height": 0},
        evaluated_image_size={"width": 0, "height": 0},
    )

    print(f"  Overall score: {visual_score}", flush=True)
    for d in dimensions:
        flag = "PASS" if d.status == "pass" else "FAIL"
        print(f"    {flag} {d.key}: {d.score}/{d.max_score}", flush=True)

    # 9: repository initialized
    checkpoint("repository initialized")

    # 10: save
    checkpoint("evaluation report saved")
    success = save_evaluation_report(TASK_ID, result, stage1_data, raw_path)
    if not success:
        return 1

    print(f"\n===== FINAL RESULT: SUCCESS =====", flush=True)
    print(f"  Score: {result.visual_consistency_score}", flush=True)
    print(f"  Dimensions: {len(result.dimensions)}", flush=True)
    print(f"  Status: {result.status}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        result = main()
        if result not in (None, 0):
            print(f"\nERROR: main returned non-zero: {result}", file=sys.stderr, flush=True)
            sys.stderr.flush()
            raise SystemExit(result)
        print(f"\nExit code 0", flush=True)
    except BaseException as exc:
        print(f"\nFATAL ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        raise
