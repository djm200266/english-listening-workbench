# ComfyUI 工作流修正方案

> 基于 `backend/workflows/sdxl_cartoon_api.json` 实际 JSON 分析 | 2026-07-13

---

## 一、逐节点连接分析

### 活跃节点（有正确连接）

```
[4] CheckpointLoaderSimple (sd_xl_base_1.0.safetensors)
 ├─ output[0] MODEL  → [10].inputs.model         ✅
 ├─ output[0] MODEL  → [6].inputs.clip            ✅ (via [4,0])
 ├─ output[1] CLIP   → [6].inputs.clip            ✅ (via [4,1])
 ├─ output[1] CLIP   → [7].inputs.clip            ✅ (via [4,1])
 └─ output[1] CLIP   → [7].inputs.clip            ✅

[5] EmptyLatentImage (1024×1024)
 └─ output[0] LATENT → [10].inputs.latent_image   ✅

[6] CLIPTextEncode (positive BASE)
 └─ output[0] COND   → [10].inputs.positive       ✅

[7] CLIPTextEncode (negative BASE)
 └─ output[0] COND   → [10].inputs.negative       ✅

[10] KSamplerAdvanced (BASE: steps 0→20, noise=enable, leftover=enable)
 └─ output[0] LATENT → [11].inputs.latent_image   → to REFINER

[12] CheckpointLoaderSimple (sd_xl_base_1.0.safetensors) ⚠️ SAME AS [4]
 ├─ output[0] MODEL  → [11].inputs.model          ✅
 ├─ output[1] CLIP   → [15].inputs.clip           ✅
 ├─ output[1] CLIP   → [16].inputs.clip           ✅
 └─ output[2] VAE    → [17].inputs.vae            ✅

[15] CLIPTextEncode (positive REFINER)
 └─ output[0] COND   → [11].inputs.positive       ✅

[16] CLIPTextEncode (negative REFINER)
 └─ output[0] COND   → [11].inputs.negative       ✅

[11] KSamplerAdvanced (REFINER: steps 20→10000, noise=disable, leftover=disable)
 └─ output[0] LATENT → [17].inputs.samples        ✅

[17] VAEDecode
 └─ output[0] IMAGE  → [19].inputs.images         ✅

[19] SaveImage (filename_prefix="ComfyUI")
```

### 孤立节点（无任何节点引用其输出）

| 节点ID | class_type | ckpt_name | 被引用次数 |
|--------|-----------|-----------|-----------|
| **53** | CheckpointLoaderSimple | sd_xl_base_1.0.safetensors | 0 |
| **54** | CheckpointLoaderSimple | sd_xl_base_1.0.safetensors | 0 |
| **55** | CheckpointLoaderSimple | sd_xl_base_1.0.safetensors | 0 |

> 验证：全文搜索 `"53"`、`"54"`、`"55"` 仅出现在各自节点定义的 key 和 `_meta.title` 中，没有任何其他节点的 `inputs` 引用它们。

---

## 二、REFINER 模型检查

### 发现

| 节点 | 标签 | ckpt_name |
|------|------|-----------|
| [4] | Load Checkpoint - BASE | `sd_xl_base_1.0.safetensors` |
| [12] | Load Checkpoint - REFINER | `sd_xl_base_1.0.safetensors` |

**节点 4 和 12 加载的是同一个模型文件。**

### SDXL 标准流程说明

SDXL 官方架构为两阶段：

| 阶段 | 模型 | 用途 |
|------|------|------|
| BASE | `sd_xl_base_1.0.safetensors` | 从纯噪声生成初始 Latent（高噪声→低噪声的前半段） |
| REFINER | `sd_xl_refiner_1.0.safetensors` | 在 BASE 输出的带残留噪声的 Latent 上做精细去噪（低噪声→无噪声的后半段） |

当前工作流的问题：
- 节点 12 加载的是 `sd_xl_base_1.0.safetensors`，而非 `sd_xl_refiner_1.0.safetensors`
- 用同一模型跑两遍 KSamplerAdvanced ≠ 真正的 SDXL refiner
- 第二遍采样（节点 11）在 step 20→10000 不加噪运行，本质上是继续去噪过程，但因为模型相同，效果等同于单阶段 KSampler 跑更多步数

### 建议：改为单阶段 BASE-only

理由：
1. **MVP 范围**：英语听说课情境图的核心需求是场景清晰、实体可辨、风格一致，单阶段 SDXL Base 完全满足
2. **避免虚假配置**：用 base 模型冒充 refiner 不如诚实使用单阶段
3. **降低复杂度**：减少 5 个节点（11/12/15/16 + 3 个孤儿），工作流更易调试
4. **降低显存**：只加载一次 checkpoint
5. **效果等价**：将节点 10 的 `end_at_step` 从 20 改为 10000，步数从 25 增到 30，单阶段输出质量 ≥ 虚假双阶段

---

## 三、修正操作

### 操作 1：删除孤立节点

从 JSON 中删除 key `"53"`, `"54"`, `"55"`。

### 操作 2：删除 REFINER 阶段节点

从 JSON 中删除 key `"11"`, `"12"`, `"15"`, `"16"`。

删除这些节点后，需要重新路由：
- 原 `[17].inputs.samples → ["11", 0]` 改为 `[17].inputs.samples → ["10", 0]`

### 操作 3：修正节点 10 的 KSampler 参数

当前（双阶段 BASE）：
```json
"start_at_step": 0,
"end_at_step": 20,
"return_with_leftover_noise": "enable"
```

改为（单阶段，全步数去噪）：
```json
"start_at_step": 0,
"end_at_step": 10000,
"return_with_leftover_noise": "disable"
```

同时将 `steps` 从 25 增加到 30（单阶段需要更多步数补偿）。

### 操作 4：修正节点 11 的 noise_seed

节点 11 已随 REFINER 阶段删除，此问题自然解决。原本 `noise_seed: 0` 硬编码不再存在。

### 保留不变的节点

| 节点ID | class_type | 保留原因 |
|--------|-----------|----------|
| 4 | CheckpointLoaderSimple | BASE checkpoint 加载 |
| 5 | EmptyLatentImage | Latent 尺寸定义 |
| 6 | CLIPTextEncode | 正向 Prompt |
| 7 | CLIPTextEncode | 负向 Prompt |
| 10 | KSamplerAdvanced | 采样（参数修正后） |
| 17 | VAEDecode | VAE 解码 |
| 19 | SaveImage | 输出保存 |

---

## 四、修正后数据流

```
[4] CheckpointLoaderSimple (sd_xl_base_1.0.safetensors)
 ├─ MODEL  → [10].model
 ├─ CLIP   → [6].clip, [7].clip
 └─ VAE    → [17].vae                         ← 改：原来从 [12] 取 VAE

[5] EmptyLatentImage → [10].latent_image

[6] CLIPTextEncode (+) → [10].positive

[7] CLIPTextEncode (-) → [10].negative

[10] KSamplerAdvanced (steps 0→10000, 30 steps)   ← 改：全步数
 └─ LATENT → [17].samples                      ← 改：原来从 [11] 取

[17] VAEDecode → [19] SaveImage
```

---

## 五、动态替换字段（修正后）

| 字段 | 节点ID | 说明 |
|------|--------|------|
| `inputs.text` (正向) | **6** | 从 P-IMAGE Prompt 动态注入 |
| `inputs.text` (负向) | **7** | 从固定模板 + style 微调 |
| `inputs.noise_seed` | **10** | 随机 seed |
| `inputs.width` | **5** | 1024 |
| `inputs.height` | **5** | 1024 |
| `inputs.filename_prefix` | **19** | `{task_id}_{style}_{seed}` |

相比原工作流减少 3 个动态替换点（原来 6、7、10、11、15、16 共 6 个 Prompt/Seed 替换，现在只需 6、7、10 共 3 个）。

### VAE 路由变化

修正后，VAE 从节点 4（BASE checkpoint）获取，而非节点 12（已删除）。BASE checkpoint 的 VAE 与 REFINER checkpoint 的 VAE 在 SDXL 中是一致的，无影响。

---

## 六、修正后的后端替换参数总结

```python
REPLACEMENTS = {
    "6": {"inputs.text": "<positive_prompt>"},      # 正向
    "7": {"inputs.text": "<negative_prompt>"},      # 负向
    "10": {"inputs.noise_seed": "<random_seed>"},   # seed
    "5": {"inputs.width": 1024, "inputs.height": 1024},  # 分辨率
    "19": {"inputs.filename_prefix": "<task_id>_<style>"}, # 输出前缀
}
```

---

## 七、如果后续要恢复真 REFINER

当 `sd_xl_refiner_1.0.safetensors` 就位后：

1. 恢复节点 12、15、16、11（从 `sdxl_cartoon_api.json` 原始版本取回）
2. 将节点 12 的 `ckpt_name` 改为 `sd_xl_refiner_1.0.safetensors`
3. 恢复节点 10 为 `end_at_step: 20, return_with_leftover_noise: enable`
4. 恢复节点 11 为 `start_at_step: 20, add_noise: disable`
5. 恢复节点 17 的 VAE 引用为 `["12", 2]`
6. 恢复节点 17 的 samples 引用为 `["11", 0]`
7. 同步更新动态替换字段覆盖节点 15、16、11
