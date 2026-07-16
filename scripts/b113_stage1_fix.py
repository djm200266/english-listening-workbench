"""Retry Stage 1 for G7_DIR_B113 — direct prompt, format_json, strip thinking."""
import io, json, re, sys, time, traceback
from pathlib import Path
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

PROJECT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT / "backend"))
LOGS_DIR = PROJECT / "logs" / "visual_eval"
TASK_ID = "G7_DIR_B113"

def checkpoint(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

checkpoint("Loading task...")
from repositories import JsonTaskRepository
repo = JsonTaskRepository()
task = repo.get_task(TASK_ID)

# Resolve image
from config import get_config
cfg = get_config()
assets_root = Path(cfg.get("assets", {}).get("rootDir", "storage")).resolve()
img_rel = task.image.image_url.lstrip("/")
if img_rel.startswith("assets/"):
    img_rel = img_rel[len("assets/"):]
img_path = (assets_root / img_rel).resolve()
print(f"  Image: {img_path} (exists={img_path.exists()}, size={img_path.stat().st_size})", flush=True)

# Preprocess
from services.visual_evaluation_service import _preprocess_image, _compute_sha256, _max_size_for_task
max_size = _max_size_for_task(task)
img_bytes, orig_size, eval_size = _preprocess_image(img_path, task.task_id, max_size)
print(f"  Image: {orig_size} -> {eval_size}", flush=True)

# Build ultra-direct prompt - no room for thinking
STAGE1_PROMPT = (
    "This Grade 7 English teaching image. "
    "Output ONLY this JSON, no thinking, no explanation, no markdown:\n"
    '{"image_caption":"", "detected_objects":[], "detected_text":[], '
    '"spatial_relations":"", "detected_style":"", "detected_layout_type":"", "quality_issues":""}\n'
    "Fill in the values. First char {, last char }."
)

user_prompt = (
    f"Describe this Grade 7 English location_reference_map image in textbook_cartoon style.\n"
    f"Fill in the JSON template above with actual observations. Be brief."
)

print(f"  Stage1 prompt: {len(STAGE1_PROMPT)} chars sys + {len(user_prompt)} chars user", flush=True)

# Call Stage 1
from services.ollama_client import OllamaClient, OllamaError

checkpoint("Calling qwen3-vl:4b for Stage 1...")
t0 = time.perf_counter()

try:
    client = OllamaClient(model="qwen3-vl:4b", timeout_sec=180)
    result = client.chat_with_images(
        STAGE1_PROMPT, user_prompt,
        image_bytes_list=[img_bytes],
        temperature=0.3,  # slightly higher to break thinking loops
        num_predict=500,
        keep_alive="30m",
        format_json=True,
        timeout_sec=180,
    )
except OllamaError as e:
    print(f"  Stage 1 FAILED: {e}", flush=True)
    sys.exit(1)

elapsed = time.perf_counter() - t0
raw = result["content"]
print(f"  Stage 1 elapsed: {elapsed:.1f}s", flush=True)
print(f"  Output length: {len(raw)} chars", flush=True)
print(f"  Output preview: {raw[:200]}", flush=True)

# Save raw
ts = datetime.now(timezone.utc).isoformat().replace(":", "-")
task_dir = LOGS_DIR / TASK_ID
task_dir.mkdir(parents=True, exist_ok=True)
(task_dir / f"{ts}_stage1_raw.txt").write_text(raw, encoding="utf-8")

# Try to extract JSON - if output is thinking, find JSON within it
def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, count=1)
    if text.endswith("```"):
        text = text[:text.rfind("```")].strip()
    # Find { to matching }
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{': depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None

json_str = extract_json(raw)

if json_str is None:
    # Look for any JSON-like blocks in the thinking
    print("  No JSON found with extract_json, searching for JSON blocks...", flush=True)
    # Try to find array/object patterns
    for pattern in [r'\{[^{}]*"image_caption"[^{}]*\}', r'\{[^{}]*"detected_objects"[^{}]*\[.*?\][^{}]*\}']:
        m = re.search(pattern, raw, re.DOTALL)
        if m:
            json_str = m.group()
            print(f"  Found potential JSON block: {json_str[:100]}...", flush=True)
            break

if json_str:
    print(f"  JSON extracted: {len(json_str)} chars", flush=True)
    # Fix common issues
    json_str = re.sub(r',\s*}', '}', json_str)
    json_str = re.sub(r',\s*]', ']', json_str)
    try:
        s1_data = json.loads(json_str)
        print(f"  json.loads SUCCESS, keys: {list(s1_data.keys())}", flush=True)
        # Save as stage1 cache
        from services.visual_evaluation_service import _compute_sha256, _stage1_cache_key, _save_stage1_cache
        img_hash = _compute_sha256(img_path)
        s1_key = _stage1_cache_key(task, img_hash, "qwen3-vl:4b", "v2")
        _save_stage1_cache(TASK_ID, s1_key, s1_data)
        print(f"  Stage 1 cache SAVED, key={s1_key}", flush=True)
        print("STAGE1_SUCCESS", flush=True)
        sys.exit(0)
    except json.JSONDecodeError as e:
        print(f"  json.loads FAILED: {e}", flush=True)
else:
    print("  No JSON found at all in output", flush=True)

# Fallback: if no JSON, try format_json without the template - just ask for JSON directly
print("\nSTAGE1_NO_JSON - trying fallback without template...", flush=True)

checkpoint("Retry Stage 1 without JSON template constraint...")
t0 = time.perf_counter()

# Ultra-minimal approach
SYS2 = "Output ONLY valid JSON. No thinking. First character {. Last character }."
USER2 = (
    f"Describe this Grade 7 English textbook cartoon location_reference_map image in JSON:\n"
    f'{{"image_caption":"brief description","detected_objects":["obj1","obj2"],'
    f'"detected_text":["text1"],"spatial_relations":"description",'
    f'"detected_style":"textbook_cartoon","detected_layout_type":"location_reference_map",'
    f'"quality_issues":"any issues or empty string"}}'
)

try:
    client2 = OllamaClient(model="qwen3-vl:4b", timeout_sec=180)
    result2 = client2.chat_with_images(
        SYS2, USER2,
        image_bytes_list=[img_bytes],
        temperature=0.3,
        num_predict=500,
        keep_alive="30m",
        format_json=True,
        timeout_sec=180,
    )
except OllamaError as e:
    print(f"  Fallback Stage 1 FAILED: {e}", flush=True)
    sys.exit(1)

elapsed2 = time.perf_counter() - t0
raw2 = result2["content"]
print(f"  Fallback elapsed: {elapsed2:.1f}s", flush=True)
print(f"  Output length: {len(raw2)} chars", flush=True)
print(f"  Output: {raw2[:300]}", flush=True)

(task_dir / f"{ts}_stage1_raw_v2.txt").write_text(raw2, encoding="utf-8")

json_str2 = extract_json(raw2)
if json_str2:
    json_str2 = re.sub(r',\s*}', '}', json_str2)
    json_str2 = re.sub(r',\s*]', ']', json_str2)
    try:
        s1_data = json.loads(json_str2)
        print(f"  Fallback json.loads SUCCESS, keys: {list(s1_data.keys())}", flush=True)
        from services.visual_evaluation_service import _compute_sha256, _stage1_cache_key, _save_stage1_cache
        img_hash = _compute_sha256(img_path)
        s1_key = _stage1_cache_key(task, img_hash, "qwen3-vl:4b", "v2")
        _save_stage1_cache(TASK_ID, s1_key, s1_data)
        print(f"  Stage 1 cache SAVED, key={s1_key}", flush=True)
        print("STAGE1_SUCCESS", flush=True)
        sys.exit(0)
    except json.JSONDecodeError as e:
        print(f"  Fallback json.loads FAILED: {e}", flush=True)

print("STAGE1_FAILED - both attempts produced no valid JSON", flush=True)
sys.exit(1)
