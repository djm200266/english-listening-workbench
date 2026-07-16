# ComfyUI 工作流分析：sdxl_cartoon_api.json

> 分析日期：2026-07-13 | 工作流文件：`backend/workflows/sdxl_cartoon_api.json`

---

## 一、格式确认

✅ 是标准 ComfyUI API 格式。

- 顶层 key 为字符串数字（节点 ID）；
- 每个节点含 `class_type`、`inputs`、`_meta`；
- 节点间引用使用 `[node_id, output_index]` 数组格式。

---

## 二、完整节点清单

| 节点ID | class_type | 用途 | 连接 |
|--------|-----------|------|------|
| **4** | `CheckpointLoaderSimple` | 加载 SDXL Base 1.0（BASE 阶段） | → 6.clip, 7.clip, 10.model |
| **5** | `EmptyLatentImage` | 空 Latent 1024×1024 | → 10.latent_image |
| **6** | `CLIPTextEncode` | 正向 Prompt 编码（BASE） | → 10.positive |
| **7** | `CLIPTextEncode` | 负向 Prompt 编码（BASE） | → 10.negative |
| **10** | `KSamplerAdvanced` | BASE 采样器（step 0→20，加噪） | → 11.latent_image |
| **12** | `CheckpointLoaderSimple` | 加载 SDXL Base 1.0（REFINER 阶段） | → 11.model, 15.clip, 16.clip, 17.vae |
| **15** | `CLIPTextEncode` | 正向 Prompt 编码（REFINER） | → 11.positive |
| **16** | `CLIPTextEncode` | 负向 Prompt 编码（REFINER） | → 11.negative |
| **11** | `KSamplerAdvanced` | REFINER 采样器（step 20→10000，不加噪） | → 17.samples |
| **17** | `VAEDecode` | VAE 解码 Latent → 图像 | → 19.images |
| **19** | `SaveImage` | 保存输出图像 | — |
| **53** | `CheckpointLoaderSimple` | ⚠️ 孤立节点（无连接） | 无 |
| **54** | `CheckpointLoaderSimple` | ⚠️ 孤立节点（无连接） | 无 |
| **55** | `CheckpointLoaderSimple` | ⚠️ 孤立节点（无连接） | 无 |

---

## 三、节点分类识别

### Checkpoint 加载节点

| 节点ID | 状态 | 模型文件 |
|--------|------|----------|
| **4** | ✅ 活跃（BASE） | `sd_xl_base_1.0.safetensors` |
| **12** | ✅ 活跃（REFINER） | `sd_xl_base_1.0.safetensors` |
| 53 | ❌ 孤立 | `sd_xl_base_1.0.safetensors` |
| 54 | ❌ 孤立 | `sd_xl_base_1.0.safetensors` |
| 55 | ❌ 孤立 | `sd_xl_base_1.0.safetensors` |

### 正向 Prompt 节点

| 节点ID | 阶段 | 当前示例内容 |
|--------|------|-------------|
| **6** | BASE | `a cute cartoon cat, sitting in a garden, colorful, children's illustration` |
| **15** | REFINER | 同上（当前相同） |

### 负向 Prompt 节点

| 节点ID | 阶段 | 当前示例内容 |
|--------|------|-------------|
| **7** | BASE | `blurry, low quality, distorted, ugly, extra fingers, bad anatomy` |
| **16** | REFINER | 同上（当前相同） |

### 其他节点

| 类型 | 节点ID | 说明 |
|------|--------|------|
| `EmptyLatentImage` | **5** | 分辨率 1024×1024, batch_size=1 |
| `KSamplerAdvanced` (BASE) | **10** | steps 0→20, cfg=8, sampler=euler, noise=enable |
| `KSamplerAdvanced` (REFINER) | **11** | steps 20→10000, cfg=8, sampler=euler, noise=disable |
| `VAEDecode` | **17** | 从 REFINER checkpoint (12) 取 VAE |
| `SaveImage` | **19** | filename_prefix=`ComfyUI` |

---

## 四、需要后端动态替换的字段

| 替换项 | 所在节点 | 字段路径 | 当前值 | 替换来源 |
|--------|----------|----------|--------|----------|
| **正向 Prompt** | 6 | `inputs.text` | `a cute cartoon cat...` | P-IMAGE Prompt + task config（topic, scenario, entities） |
| **正向 Prompt** | 15 | `inputs.text` | 同上（当前相同） | 同上 |
| **负向 Prompt** | 7 | `inputs.text` | `blurry, low quality...` | 固定模板（可按 style 微调） |
| **负向 Prompt** | 16 | `inputs.text` | 同上 | 同上 |
| **Seed** | 10 | `inputs.noise_seed` | `997412778096133` | `random.randint(0, 2**63)` 每次调用 |
| **Seed** | 11 | `inputs.noise_seed` | `0` | `random.randint(0, 2**63)` 每次调用 |
| **宽度** | 5 | `inputs.width` | `1024` | config（固定 1024 for SDXL） |
| **高度** | 5 | `inputs.height` | `1024` | config（固定 1024 for SDXL） |
| **filename_prefix** | 19 | `inputs.filename_prefix` | `ComfyUI` | `{task_id}_{style}_{seed}` |

---

## 五、模型文件验证

| 字段 | 值 | 是否正确 |
|------|-----|----------|
| 节点 4 `ckpt_name` | `sd_xl_base_1.0.safetensors` | ✅ 正确 |
| 节点 12 `ckpt_name` | `sd_xl_base_1.0.safetensors` | ⚠️ 同 BASE（REFINER 通常使用专用 refiner 模型，但 SDXL 1.0 标准工作流中 refiner 也使用 base 模型加载 VAE） |
| 节点 53/54/55 `ckpt_name` | `sd_xl_base_1.0.safetensors` | ⚠️ 孤立节点，可删除 |

---

## 六、工作流结构与问题

### 数据流图

```
[4] CheckpointLoader ──→ [6] CLIPTextEncode(+) ──→ [10] KSamplerAdvanced(BASE)
     │                        [7] CLIPTextEncode(-) ──→        │
     │                        [5] EmptyLatentImage ──→         │
     │                                                         ↓
     │                                              [11] KSamplerAdvanced(REFINER)
     │                                                   ↑
[12] CheckpointLoader ──→ [15] CLIPTextEncode(+) ──→    │
                          [16] CLIPTextEncode(-) ──→    │
                          [17] VAEDecode ←──────────────┘
                              ↓
                         [19] SaveImage
```

### 发现的问题

| # | 问题 | 严重程度 | 建议 |
|---|------|----------|------|
| 1 | 节点 53/54/55 是孤立 CheckpointLoaderSimple，无任何连接 | 低 | 从工作流中删除，减少 API 调用时的加载开销 |
| 2 | REFINER 阶段（节点 12）使用与 BASE 相同的 `sd_xl_base_1.0.safetensors` | 中 | SDXL 标准流程中 REFINER 通常使用专用 refiner 模型。如果 ComfyUI 的 `sd_xl_base_1.0.safetensors` 同时包含 base + refiner，则无问题；否则 REFINER 阶段的 KSampler 输出质量可能受影响 |
| 3 | BASE 和 REFINER 的正向 Prompt 当前为相同值（节点 6 和 15） | 信息 | SDXL 两阶段通常使用相同 prompt，此为正常做法 |
| 4 | REFINER 的 `noise_seed` 当前为 `0` | 中 | 应改为随机值。REFINER 阶段通常应继承 BASE 的 seed 或使用独立随机 seed |
| 5 | 缺少 `PreviewImage` 节点 | 低 | API 模式下不需要预览，可接受。如需调试可添加 |

---

## 七、后端替换伪代码

```python
def build_workflow(
    positive_prompt: str,
    negative_prompt: str | None = None,
    seed: int | None = None,
    width: int = 1024,
    height: int = 1024,
    filename_prefix: str = "ComfyUI",
) -> dict:
    import random, copy, json
    from pathlib import Path

    workflow_path = Path("backend/workflows/sdxl_cartoon_api.json")
    workflow = json.loads(workflow_path.read_text())

    if seed is None:
        seed = random.randint(0, 2**63 - 1)

    # 删除孤立节点
    for orphan in ["53", "54", "55"]:
        workflow.pop(orphan, None)

    # 替换正向 Prompt（节点 6 和 15）
    workflow["6"]["inputs"]["text"] = positive_prompt
    workflow["15"]["inputs"]["text"] = positive_prompt

    # 替换负向 Prompt（节点 7 和 16）
    neg = negative_prompt or "blurry, low quality, distorted, ugly, bad anatomy, extra fingers"
    workflow["7"]["inputs"]["text"] = neg
    workflow["16"]["inputs"]["text"] = neg

    # 替换 Seed
    workflow["10"]["inputs"]["noise_seed"] = seed
    workflow["11"]["inputs"]["noise_seed"] = seed  # REFINER 继承 BASE seed

    # 替换分辨率
    workflow["5"]["inputs"]["width"] = width
    workflow["5"]["inputs"]["height"] = height

    # 替换输出前缀
    workflow["19"]["inputs"]["filename_prefix"] = filename_prefix

    return workflow
```

### ComfyUI API 调用流程

```
POST http://127.0.0.1:8188/prompt
Body: { "prompt": workflow, "client_id": "english-workbench" }
Response: { "prompt_id": "xxx-xxx-xxx" }

→ 轮询 GET http://127.0.0.1:8188/history/{prompt_id}
→ 获取 outputs["19"]["images"][0]["filename"]
→ 下载: GET http://127.0.0.1:8188/view?filename={filename}&subfolder={subfolder}
→ 保存到 storage/images/{task_id}/
```

---

## 八、风格 Prompt 映射（5 种）

| style | 正向 Prompt 后缀 | 说明 |
|-------|-----------------|------|
| `cartoon` | `cartoon style, bright colors, simple lines, cute` | 卡通 |
| `children_book` | `children's book illustration, warm colors, storybook style` | 儿童绘本 |
| `flat` | `flat design, minimalist, clean lines, vector style` | 扁平 |
| `watercolor` | `watercolor painting, soft edges, artistic, gentle colors` | 水彩 |
| `realistic` | `photorealistic, detailed, natural lighting, realistic` | 写实 |
