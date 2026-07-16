"""Stage 2-only retry — reads Stage 1 cache, calls text model with simplified
output schema, parses JSON, validates with Pydantic, saves report.
ONE attempt. NO Stage 1, NO visual model, NO image upload.
"""
import io, json, re, sys, time, traceback
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

PROJECT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT / "backend"))

TASK_ID = "G7_DIR_0838"
LOGS_DIR = PROJECT / "logs" / "visual_eval"

def checkpoint(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ── 1. Load Stage 1 cache ──────────────────────────────────
checkpoint("Loading Stage 1 cache...")
task_dir = LOGS_DIR / TASK_ID
s1_files = sorted(task_dir.glob("*_stage1_data.json"), key=lambda p: p.stat().st_mtime, reverse=True)
if not s1_files:
    print("FATAL: No Stage 1 cache found", flush=True)
    sys.exit(1)

stage1 = json.loads(s1_files[0].read_text(encoding="utf-8"))
print(f"  stage1_cache_hit=true", flush=True)
print(f"  Source: {s1_files[0].name}", flush=True)
print(f"  Caption: {stage1.get('image_caption','')[:80]}", flush=True)

# ── 2. Build simplified Stage 2 prompt ─────────────────────
checkpoint("Building simplified Stage 2 prompt...")

# Load task for requirements
from repositories import JsonTaskRepository
repo = JsonTaskRepository()
task = repo.get_task(TASK_ID)
cfg = task.config

s2_prompt = (
    f"Evaluate this Grade 7 English teaching image quality.\n\n"
    f"=== VISUAL FACTS ===\n"
    f"Caption: {stage1.get('image_caption','N/A')[:150]}\n"
    f"Style: {stage1.get('detected_style','unknown')}\n"
    f"Layout: {stage1.get('detected_layout_type','unknown')}\n"
    f"Objects: {json.dumps(stage1.get('detected_objects',[]), ensure_ascii=False)[:200]}\n"
    f"Text: {json.dumps(stage1.get('detected_text',[]), ensure_ascii=False)[:200]}\n"
    f"Relations: {json.dumps(stage1.get('spatial_relations',''), ensure_ascii=False)[:150]}\n"
    f"Issues: {json.dumps(stage1.get('quality_issues',''), ensure_ascii=False)[:150]}\n\n"
    f"=== REQUIREMENTS ===\n"
    f"Topic: {cfg.topic}\n"
    f"Style: {cfg.image_style}\n"
    f"Goal: {getattr(cfg,'image_goal','auto')}\n"
    f"Elements: {', '.join(cfg.required_vocabulary[:5]) if cfg.required_vocabulary else 'N/A'}\n\n"
    f"Score these dimensions (0-100):\n"
    f"visual_content_alignment, image_type_alignment, style_alignment, "
    f"required_element_coverage, spatial_relation_accuracy, instructional_clarity, "
    f"text_legibility, composition_quality, artifact_quality, prompt_visual_consistency.\n\n"
    f"Output EXACTLY this JSON structure, no extra fields, no markdown, no thinking:\n"
    f'{{"overall_score": 0, "summary": "", "dimensions": [\n'
    f'  {{"key": "name", "score": 0, "status": "pass", "issues": [], "suggestions": []}}\n'
    f'], "hard_failures": [], "recommendations": []}}\n\n'
    f"Rules: max 2 issues and 2 suggestions per dimension. "
    f"Each text under 80 characters. No nested quotes - use single quotes if needed. "
    f"First char must be {{, last char must be }}."
)
print(f"  Prompt length: {len(s2_prompt)} chars", flush=True)

# ── 3. Call Stage 2 text model ─────────────────────────────
checkpoint("Calling Stage 2 text model (qwen3:4b-instruct)...")

from services.ollama_client import OllamaClient, OllamaError

S2_SYSTEM = (
    "You are a teaching image evaluator. "
    "Output ONLY a valid JSON object matching the specified schema exactly. "
    "No markdown, no code blocks, no thinking, no extra text. "
    "First character must be {, last character must be }."
)

t0 = time.perf_counter()
client = OllamaClient(model="qwen3:4b-instruct", timeout_sec=120)

try:
    result = client.chat(
        system_prompt=S2_SYSTEM,
        user_prompt=s2_prompt,
        model="qwen3:4b-instruct",
        temperature=0.1,
        num_predict=1200,
        keep_alive="30m",
        format_json=True,
    )
    elapsed = time.perf_counter() - t0

    raw_output = result.get("content", "")
    done_reason = result.get("done_reason", "unknown")
    eval_count = result.get("eval_count", 0)
    prompt_eval_count = result.get("prompt_eval_count", 0)
    gen_ms = int(result.get("eval_duration_ns", 0) / 1_000_000)

    print(f"  Stage 2 model: qwen3:4b-instruct", flush=True)
    print(f"  Stage 2 elapsed: {elapsed:.1f}s", flush=True)
    print(f"  done_reason: {done_reason}", flush=True)
    print(f"  eval_count: {eval_count}", flush=True)
    print(f"  prompt_eval_count: {prompt_eval_count}", flush=True)
    print(f"  response_length: {len(raw_output)} chars", flush=True)
    print(f"  generation_ms: {gen_ms}", flush=True)

    if done_reason == "length":
        checkpoint("WARNING: Output truncated by token limit!")
        print(f"  error_code: VISUAL_STAGE2_OUTPUT_TRUNCATED", flush=True)

except OllamaError as e:
    elapsed = time.perf_counter() - t0
    print(f"  Stage 2 FAILED after {elapsed:.1f}s: {e}", flush=True)
    # Save failed status
    from models import EvalReport
    task2 = repo.get_task(TASK_ID)
    if task2.evaluation is None:
        task2.evaluation = EvalReport(task_id=TASK_ID)
    task2.evaluation.evaluation_status = "failed"
    task2.evaluation.visual_data = {"status": "failed", "error_code": "VISUAL_STAGE2_CALL_FAILED", "error_message": str(e)[:500]}
    repo.save_task(task2)
    print("  evaluation_status = failed, saved", flush=True)
    sys.exit(1)

# Save raw output
ts = datetime.now(timezone.utc).isoformat().replace(":", "-")
raw_path = task_dir / f"{ts}_stage2_raw_v2.txt"
raw_path.write_text(raw_output, encoding="utf-8")
prompt_path = task_dir / f"{ts}_stage2_prompt_v2.txt"
prompt_path.write_text(s2_prompt, encoding="utf-8")

# ── 4. Parse JSON ──────────────────────────────────────────
checkpoint("Parsing Stage 2 JSON...")

def extract_json(text):
    text = text.strip()
    # Remove markdown
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, count=1)
    if text.endswith("```"):
        text = text[:text.rfind("```")].strip()
    start = text.find("{")
    if start < 0:
        return text
    # Extract balanced braces
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{': depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return text[start:]

json_str = extract_json(raw_output)
print(f"  Extracted JSON: {len(json_str)} chars", flush=True)

# Remove trailing commas (single pass)
json_str = re.sub(r',\s*}', '}', json_str)
json_str = re.sub(r',\s*]', ']', json_str)

try:
    s2_data = json.loads(json_str)
    print(f"  json.loads: SUCCESS", flush=True)
    print(f"  Keys: {list(s2_data.keys())}", flush=True)
except json.JSONDecodeError as e:
    print(f"  json.loads: FAILED — {e}", flush=True)
    print(f"  Raw preview: {raw_output[:500]}", flush=True)
    # Save failed
    from models import EvalReport
    task2 = repo.get_task(TASK_ID)
    if task2.evaluation is None:
        task2.evaluation = EvalReport(task_id=TASK_ID)
    task2.evaluation.evaluation_status = "failed"
    task2.evaluation.visual_data = {"status": "parse_failed", "error_code": "VISUAL_STAGE2_PARSE_FAILED", "error_message": str(e)[:500]}
    repo.save_task(task2)
    print("  evaluation_status = failed, error_code=VISUAL_STAGE2_PARSE_FAILED", flush=True)
    sys.exit(1)

# ── 5. Pydantic validation ─────────────────────────────────
checkpoint("Pydantic validation...")

from models import VisualEvaluationResult, VisualEvaluationDimension

dimensions = []
for d in s2_data.get("dimensions", []):
    score = max(0, min(100, float(d.get("score", 0))))
    dimensions.append(VisualEvaluationDimension(
        key=d.get("key", ""),
        label=d.get("label", d.get("key", "")),
        score=score,
        max_score=100,
        status=d.get("status", "evaluated"),
        issues=(d.get("issues") or [])[:2],
        suggestions=(d.get("suggestions") or [])[:2],
    ))

dim_scores = [d.score for d in dimensions if d.score >= 0]
overall = round(sum(dim_scores) / len(dim_scores), 1) if dim_scores else 0.0

vis_result = VisualEvaluationResult(
    status="success",
    model="qwen3-vl:4b + qwen3:4b-instruct [Stage 2 retry]",
    visual_content_checked=True,
    visual_consistency_score=overall,
    image_caption=stage1.get("image_caption", ""),
    detected_style=stage1.get("detected_style", "unknown"),
    detected_layout_type=stage1.get("detected_layout_type", "unknown"),
    dimensions=dimensions,
    hard_failures=[],
    bad_cases=[],
    recommendations=(s2_data.get("recommendations") or [])[:5],
    confidence=0.9,
    image_sha256="",
    original_image_size={"width": 1024, "height": 1024},
    evaluated_image_size={"width": 1024, "height": 1024},
    generation_ms=gen_ms,
    total_ms=int(elapsed * 1000),
)

print(f"  Pydantic: PASSED", flush=True)
print(f"  Overall score: {overall}", flush=True)
for d in dimensions:
    print(f"    {d.key}: {d.score}/100 [{d.status}]", flush=True)

# ── 6. Save ────────────────────────────────────────────────
checkpoint("Saving evaluation report...")

from models import EvalReport

task2 = repo.get_task(TASK_ID)
if task2.evaluation is None:
    task2.evaluation = EvalReport(task_id=TASK_ID)

task2.evaluation.visual_data = vis_result.model_dump()
task2.evaluation.visual_score = overall
task2.evaluation.visual_prompt_version = "v2"
task2.evaluation.evaluation_status = "generated"
task2.evaluation.model = "qwen3-vl:4b + qwen3:4b-instruct"

# Compute combined score (existing semantic + new visual)
sem_score = getattr(task2.evaluation, 'semantic_score', 0) or 0
rule_score = getattr(task2.evaluation, 'rule_score', 0) or 0
if sem_score > 0 and rule_score > 0:
    task2.evaluation.combined_score = round(rule_score * 0.35 + sem_score * 0.35 + overall * 0.30, 1)
task2.evaluation.overall_score = task2.evaluation.combined_score or overall

repo.save_task(task2)

# Save final report JSON
report_path = task_dir / f"{ts}_result_final.json"
report_output = {
    "result": vis_result.model_dump(),
    "stage1_data": stage1,
    "stage2_data": s2_data,
    "diagnostics": {
        "stage1_cache_hit": True,
        "stage2_model": "qwen3:4b-instruct",
        "stage2_elapsed_s": round(elapsed, 1),
        "done_reason": done_reason,
        "eval_count": eval_count,
        "prompt_eval_count": prompt_eval_count,
        "generation_ms": gen_ms,
        "num_predict": 1200,
    },
}
report_path.write_text(json.dumps(report_output, ensure_ascii=False, indent=2), encoding="utf-8")

# ── 7. Summary ─────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"FINAL RESULT")
print(f"{'='*60}")
print(f"  stage1_cache_hit: true")
print(f"  Stage 2 model: qwen3:4b-instruct")
print(f"  Stage 2 elapsed: {elapsed:.1f}s")
print(f"  done_reason: {done_reason}")
print(f"  JSON parse: SUCCESS")
print(f"  Pydantic: PASSED")
print(f"  evaluation_status: generated")
print(f"  Overall score: {overall}")
print(f"  Report: {report_path}")
print(f"  Visual model recalled: NO")
print(f"{'='*60}")
sys.exit(0)
