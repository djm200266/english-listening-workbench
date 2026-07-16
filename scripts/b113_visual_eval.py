"""Run visual evaluation for G7_DIR_B113 — Stage 1 + Stage 2, then save."""
import io, json, sys, time, traceback
from pathlib import Path
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

PROJECT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT / "backend"))

TASK_ID = "G7_DIR_B113"

def checkpoint(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ── Load task ──────────────────────────────────────────────
checkpoint("Loading task...")
from repositories import JsonTaskRepository
repo = JsonTaskRepository()
task = repo.get_task(TASK_ID)
print(f"  task_id={task.task_id}, status={task.status}", flush=True)
print(f"  image_url={task.image.image_url}", flush=True)
print(f"  evaluation_status={task.evaluation.evaluation_status if task.evaluation else 'none'}", flush=True)

# ── Run Stage 2 style visual evaluation ────────────────────
# Use the same approach as stage2_retry.py: reuse simplified prompt,
# call qwen3-vl for Stage 1, then qwen3:4b-instruct for Stage 2

from services.visual_evaluation_service import evaluate_image_visual
from config import get_config

cfg = get_config().get("evaluation", {})
print(f"  visualModel={cfg.get('visualModel','qwen3-vl:4b')}", flush=True)
print(f"  visualSingleModel={cfg.get('visualSingleModel', False)}", flush=True)

checkpoint("Running Stage 1 (qwen3-vl:4b) + Stage 2 (qwen3:4b-instruct)...")
t0 = time.perf_counter()

try:
    result = evaluate_image_visual(task, force_regenerate=False, single_model=False)
except Exception as e:
    print(f"FATAL: evaluate_image_visual crashed: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)

elapsed = time.perf_counter() - t0
print(f"  Total elapsed: {elapsed:.1f}s", flush=True)
print(f"  Status: {result.status}", flush=True)

if result.status != "success":
    print(f"  ERROR: {result.error_code}: {result.error_message}", flush=True)
    # Save failed
    if task.evaluation is None:
        from models import EvalReport
        task.evaluation = EvalReport(task_id=TASK_ID)
    task.evaluation.visual_data = result.model_dump()
    task.evaluation.evaluation_status = "failed"
    repo.save_task(task)
    print("  Saved failed status", flush=True)
    sys.exit(1)

# ── Recalculate combined score ─────────────────────────────
rw = cfg.get("ruleWeight", 0.35)
sw = cfg.get("semanticWeight", 0.35)
vw = cfg.get("visualWeight", 0.30)

rs = task.evaluation.overall_score  # actually rule_score
ss = task.evaluation.semantic_score if hasattr(task.evaluation, "semantic_score") else 0
vs = result.visual_consistency_score

sem_ok = task.evaluation.semantic_data and task.evaluation.semantic_data.get("status") == "success"
vis_ok = True

active_weights = [rw]
scores_list = [rs]
if sem_ok:
    active_weights.append(sw)
    scores_list.append(ss)
active_weights.append(vw)
scores_list.append(vs)

total_w = sum(active_weights)
combined = round(sum(s * (w / total_w) for s, w in zip(scores_list, active_weights)), 1)

print(f"  rule_score={rs}, semantic_score={ss}, visual_score={vs}", flush=True)
print(f"  combined_score={combined}", flush=True)

# ── Save ───────────────────────────────────────────────────
task.evaluation.visual_data = result.model_dump()
task.evaluation.visual_score = vs
task.evaluation.combined_score = combined
task.evaluation.visual_prompt_version = cfg.get("visualPromptVersion", "v1")
task.evaluation.evaluation_status = "generated"
task.evaluation.asset_fingerprint = "regenerated"
task.evaluation.model = "rule + qwen3:4b-instruct + qwen3-vl:4b"
repo.save_task(task)

checkpoint("SAVED")
print(f"  evaluation_status=generated", flush=True)
print(f"  visual_consistency_score={vs}", flush=True)
print(f"  combined_score={combined}", flush=True)
print(f"  visual_content_checked={result.visual_content_checked}", flush=True)
print(f"  image_caption={result.image_caption[:80]}...", flush=True)
print("DONE", flush=True)
sys.exit(0)
