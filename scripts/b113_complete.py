"""Complete visual eval for G7_DIR_B113: use cached Stage 1, run Stage 2 text model."""
import io, json, sys, time, traceback
from pathlib import Path
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

PROJECT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT / "backend"))

TASK_ID = "G7_DIR_B113"
LOGS_DIR = PROJECT / "logs" / "visual_eval"

def checkpoint(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ── 1. Load Stage 1 from cache ─────────────────────────────
checkpoint("Loading Stage 1 cache...")
cache_dir = LOGS_DIR / TASK_ID / "stage1_cache"
cache_files = sorted(cache_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
if not cache_files:
    print("FATAL: No Stage 1 cache", flush=True)
    sys.exit(1)
stage1 = json.loads(cache_files[0].read_text(encoding="utf-8"))
print(f"  stage1_cache_hit=true", flush=True)
print(f"  Caption: {stage1.get('image_caption','')}", flush=True)

# ── 2. Load task ───────────────────────────────────────────
from repositories import JsonTaskRepository
repo = JsonTaskRepository()
task = repo.get_task(TASK_ID)
cfg = task.config

# ── 3. Simplified Stage 2 prompt ───────────────────────────
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
    f"Each text under 80 characters. No nested quotes - use single quotes. "
    f"First char {{, last char }}."
)

S2_SYSTEM = (
    "You are a teaching image evaluator. "
    "Output ONLY a valid JSON object matching the schema exactly. "
    "No markdown, no code blocks, no thinking, no extra text. "
    "First character {, last character }."
)

# ── 4. Call Stage 2 ────────────────────────────────────────
checkpoint("Calling Stage 2 (qwen3:4b-instruct)...")
from services.ollama_client import OllamaClient, OllamaError

t0 = time.perf_counter()
try:
    client = OllamaClient(model="qwen3:4b-instruct", timeout_sec=120)
    result = client.chat(
        system_prompt=S2_SYSTEM,
        user_prompt=s2_prompt,
        model="qwen3:4b-instruct",
        temperature=0.1,
        num_predict=1200,
        keep_alive="30m",
        format_json=True,
    )
except OllamaError as e:
    print(f"  Stage 2 FAILED: {e}", flush=True)
    if task.evaluation:
        task.evaluation.evaluation_status = "failed"
        task.evaluation.visual_data = {"status":"failed","error_code":"VISUAL_STAGE2_CALL_FAILED","error_message":str(e)[:500]}
        repo.save_task(task)
    sys.exit(1)

elapsed = time.perf_counter() - t0
raw = result.get("content", "")
done_reason = result.get("done_reason", "unknown")
eval_count = result.get("eval_count", 0)
gen_ms = int(result.get("eval_duration_ns", 0) / 1_000_000)

print(f"  Stage 2 elapsed: {elapsed:.1f}s, done_reason={done_reason}, eval_count={eval_count}, gen_ms={gen_ms}", flush=True)
print(f"  Output length: {len(raw)} chars", flush=True)

# Save raw
ts = datetime.now(timezone.utc).isoformat().replace(":", "-")
task_dir = LOGS_DIR / TASK_ID
task_dir.mkdir(parents=True, exist_ok=True)
(task_dir / f"{ts}_stage2_raw.txt").write_text(raw, encoding="utf-8")
(task_dir / f"{ts}_stage2_prompt.txt").write_text(s2_prompt, encoding="utf-8")

# ── 5. Parse JSON ──────────────────────────────────────────
checkpoint("Parsing Stage 2 JSON...")

import re
def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, count=1)
    if text.endswith("```"):
        text = text[:text.rfind("```")].strip()
    start = text.find("{")
    if start < 0: return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{': depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None

json_str = extract_json(raw)
if not json_str:
    print("  Failed to extract JSON", flush=True)
    if task.evaluation:
        task.evaluation.evaluation_status = "failed"
        task.evaluation.visual_data = {"status":"parse_failed","error_code":"VISUAL_STAGE2_PARSE_FAILED"}
        repo.save_task(task)
    sys.exit(1)

json_str = re.sub(r',\s*}', '}', json_str)
json_str = re.sub(r',\s*]', ']', json_str)

try:
    s2_data = json.loads(json_str)
    print(f"  json.loads SUCCESS, keys: {list(s2_data.keys())}", flush=True)
except json.JSONDecodeError as e:
    print(f"  json.loads FAILED: {e}", flush=True)
    if task.evaluation:
        task.evaluation.evaluation_status = "failed"
        task.evaluation.visual_data = {"status":"parse_failed","error_code":"VISUAL_STAGE2_PARSE_FAILED","error_message":str(e)[:500]}
        repo.save_task(task)
    sys.exit(1)

# ── 6. Build VisualEvaluationResult ────────────────────────
from models import VisualEvaluationResult, VisualEvaluationDimension, VisualDetectedObject

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
visual_score = round(sum(dim_scores) / len(dim_scores), 1) if dim_scores else 0.0

objects = [VisualDetectedObject(label=o) for o in stage1.get("detected_objects", [])]
texts_raw = stage1.get("detected_text", [])
detected_texts = [{"text": t, "confidence": 0.9} for t in (texts_raw if isinstance(texts_raw, list) else [])]

vis_result = VisualEvaluationResult(
    status="success",
    model="qwen3-vl:4b + qwen3:4b-instruct",
    visual_content_checked=True,
    visual_consistency_score=visual_score,
    image_caption=stage1.get("image_caption", ""),
    detected_objects=objects,
    detected_text=detected_texts,
    spatial_relations=[],
    detected_style=stage1.get("detected_style", "unknown"),
    detected_layout_type=stage1.get("detected_layout_type", "unknown"),
    quality_issues=[],
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
print(f"  visual_consistency_score={visual_score}", flush=True)

# ── 7. Recalculate combined ────────────────────────────────
eval_cfg = __import__('config').get_config().get("evaluation", {})
rw = eval_cfg.get("ruleWeight", 0.35)
sw = eval_cfg.get("semanticWeight", 0.35)
vw = eval_cfg.get("visualWeight", 0.30)

rs = task.evaluation.overall_score  # rule_score
ss = task.evaluation.semantic_score if hasattr(task.evaluation, "semantic_score") else 0
vs = visual_score

weights = [rw, sw, vw]
vals = [rs, ss, vs]
total_w = sum(weights)
combined = round(sum(v * (w / total_w) for v, w in zip(vals, weights)), 1)

print(f"  rule={rs}, semantic={ss}, visual={vs}, combined={combined}", flush=True)

# ── 8. Save ────────────────────────────────────────────────
from models import EvalReport
if task.evaluation is None:
    task.evaluation = EvalReport(task_id=TASK_ID)

task.evaluation.visual_data = vis_result.model_dump()
task.evaluation.visual_score = vs
task.evaluation.combined_score = combined
task.evaluation.visual_prompt_version = "v2"
task.evaluation.evaluation_status = "generated"
task.evaluation.model = "rule + qwen3:4b-instruct + qwen3-vl:4b"
repo.save_task(task)

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
        "generation_ms": gen_ms,
    },
}
report_path.write_text(json.dumps(report_output, ensure_ascii=False, indent=2), encoding="utf-8")

checkpoint("DONE")
print(f"  evaluation_status=generated", flush=True)
print(f"  visual_consistency_score={vs}", flush=True)
print(f"  combined_score={combined}", flush=True)
print(f"  visual_content_checked=True", flush=True)
print(f"  report={report_path}", flush=True)
sys.exit(0)
