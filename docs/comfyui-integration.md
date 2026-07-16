# ComfyUI 图片生成集成文档

> 基于 PRD V0.1 | 实现日期：2026-07-13

---

## 一、配置项说明

### config.json → comfyui

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | `true` | 是否启用图片生成 |
| `baseUrl` | string | `http://127.0.0.1:8188` | ComfyUI API 地址 |
| `workflowPath` | string | `backend/workflows/sdxl_cartoon_api.fixed.json` | 工作流模板路径（相对项目根目录） |
| `checkpoint` | string | `sd_xl_base_1.0.safetensors` | SDXL checkpoint 名称 |
| `width` | int | `1024` | 生成图片宽度 |
| `height` | int | `1024` | 生成图片高度 |
| `batchSize` | int | `1` | 每批生成数量 |
| `steps` | int | `30` | 采样步数 |
| `cfg` | float | `8.0` | CFG scale |
| `sampler` | string | `euler` | 采样器名称 |
| `scheduler` | string | `normal` | 调度器名称 |
| `timeoutSec` | int | `120` | 生成超时秒数 |
| `pollIntervalSec` | float | `2.0` | 轮询间隔秒数 |
| `maxRetries` | int | `1` | 最大重试次数 |
| `styles` | string[] | 5种 | 可用图片风格 |

---

## 二、工作流替换逻辑

### 模板加载

优先使用 `sdxl_cartoon_api.fixed.json`（单阶段修正版），如不存在则回退到 `sdxl_cartoon_api.json`。

### 动态替换字段

| 节点ID | 字段路径 | 替换来源 | 示例值 |
|--------|----------|----------|--------|
| **6** | `inputs.text` | 正向 Prompt（场景+实体+风格） | `English teaching illustration..., scene of asking for directions to the library, showing library and bank, cartoon style...` |
| **7** | `inputs.text` | 负向 Prompt（基础模板+风格微调） | `blurry, low quality, distorted...` |
| **10** | `inputs.noise_seed` | `random.randint(0, 2**63-1)` | `884729103847261` |
| **5** | `inputs.width` | config `comfyui.width` | `1024` |
| **5** | `inputs.height` | config `comfyui.height` | `1024` |
| **19** | `inputs.filename_prefix` | `{task_id}_{style}` | `G7_DIR_001_cartoon` |

### 工作流节点（7 节点单阶段）

```
[4] CheckpointLoaderSimple → MODEL + CLIP + VAE
[5] EmptyLatentImage (1024×1024) → LATENT
[6] CLIPTextEncode (+) → CONDITIONING
[7] CLIPTextEncode (-) → CONDITIONING
[10] KSamplerAdvanced (30 steps, euler) → LATENT
[17] VAEDecode → IMAGE
[19] SaveImage → output PNG
```

### Prompt 构造规则

**正向 Prompt**：
```
[Grade 7 prefix], [scene description], [place entities], [style suffix], [character description]
```

**负向 Prompt**：
```
blurry, low quality, distorted, ugly, bad anatomy, extra fingers,
missing fingers, deformed hands, text, watermark, signature,
complex background, cluttered, dark, scary, nsfw
```

**5 种风格映射**：

| style | 正向 Prompt 后缀 |
|-------|-----------------|
| `cartoon` | cartoon style, bright colors, simple lines, cute characters, flat shading |
| `children_book` | children's book illustration, warm colors, storybook style, hand-drawn feel |
| `flat` | flat design, minimalist, clean lines, vector illustration style |
| `watercolor` | watercolor painting, soft edges, artistic, gentle colors |
| `realistic` | photorealistic, detailed, natural lighting, realistic proportions |

---

## 三、API 调用链

### 新增接口

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/v1/images/tasks/{task_id}/generate` | 生成图片 |
| GET | `/api/v1/images/tasks/{task_id}` | 查询任务图片列表 |

### POST generate 流程

```
1. 校验 mode=real（否则 400）
2. 从 Repository 读取 Task
3. 构建正向/负向 Prompt（从 config + script 提取实体）
4. 加载工作流模板 JSON
5. 替换节点 6/7/10/5/19 的动态字段
6. POST ComfyUI /prompt  → 获取 prompt_id
7. 轮询 GET /history/{prompt_id} → 等待完成
8. GET /view?filename=... → 下载图片
9. 保存到 {assets.rootDir}/{task_id}/images/
10. 更新 Task.image → 保存
```

### 错误码

| 状态码 | error_code | 说明 |
|--------|-----------|------|
| 400 | NOT_REAL_MODE | Mock 模式下调用 |
| 404 | TASK_NOT_FOUND | 任务不存在 |
| 503 | COMFYUI_ERROR | ComfyUI 无法连接 |
| 500 | COMFYUI_ERROR | 生成超时或其他错误 |

---

## 四、任务素材目录结构

```
{assets.rootDir}/
└── {task_id}/
    ├── images/
    │   └── G7_DIR_001_cartoon_00001_.png    ← ComfyUI 输出
    ├── audio_segments/
    │   ├── turn_01_A.wav
    │   └── ...
    ├── dialogue_v1_0.wav
    └── asr_output/
        ├── dialogue_v1.txt
        └── dialogue_v1.json
```

---

## 五、测试步骤

### 前置条件
1. ComfyUI 已启动（`http://127.0.0.1:8188`）
2. `sd_xl_base_1.0.safetensors` 已放入 ComfyUI models 目录
3. `config.json` 中 `mode: "real"`

### 测试 1：健康检查
```bash
curl http://127.0.0.1:8000/api/health
# 期望: "comfyui": true
```

### 测试 2：生成图片
```bash
# 先生成脚本并确认
curl -X POST http://127.0.0.1:8000/api/v1/script/generate \
  -H "Content-Type: application/json" \
  -d '{"task_name":"Image Test","scenario":"student asking for the library","required_vocabulary":["library"],"target_patterns":["Where is..."],"topic":"Asking for Directions","dialogue_turns":4,"audio_duration_target_sec":25,"question_count":2}'

# 确认脚本
curl -X POST http://127.0.0.1:8000/api/v1/script/confirm \
  -H "Content-Type: application/json" \
  -d '{"task_id":"G7_DIR_xxxx"}'

# 生成图片
curl -X POST http://127.0.0.1:8000/api/v1/images/tasks/G7_DIR_xxxx/generate \
  -H "Content-Type: application/json" \
  -d '{"style":"cartoon"}'
```

### 测试 3：验证图片文件
```bash
ls D:/english_eval/assets/G7_DIR_xxxx/images/
# 期望: G7_DIR_xxxx_cartoon_00001_.png
```

### 测试 4：Mock 模式
```bash
# config.json mode="mock"
curl -X POST http://127.0.0.1:8000/api/v1/images/tasks/test/generate
# 期望: 400 NOT_REAL_MODE
```

---

## 六、新增/修改文件清单

| 文件 | 操作 | 用途 |
|------|------|------|
| `config.json` | 修改 | 新增 comfyui 配置块（enabled, workflowPath, width, height 等） |
| `backend/services/comfyui_client.py` | **新增** | ComfyUI API 客户端：submit_workflow, wait_for_result, download_image, health_check |
| `backend/services/image_workflow_service.py` | **新增** | Prompt 构造 + 工作流模板替换 + ComfyUI 调用编排 |
| `backend/api/image_routes.py` | **新增** | POST generate + GET list 端点 |
| `backend/api/health.py` | 修改 | 新增 ComfyUI 健康检查 |
| `backend/main.py` | 修改 | 注册 image_router |
