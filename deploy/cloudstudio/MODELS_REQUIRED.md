# 模型文件清单 — English Listening Workbench

> 以下模型需要人工下载或通过对应工具拉取。setup-cloudstudio.sh **不会**自动下载这些文件。

---

## 一、Ollama 模型

使用 Ollama 拉取，命令示例：

```bash
ollama pull <model_name>
```

| 用途 | 模型名 | 大小（约） | 备注 |
|------|--------|-----------|------|
| 文本评测 / 脚本生成 | `qwen3:4b-instruct` | ~2.4 GB | 核心模型，必须 |
| 视觉评测（Stage 1 事实提取 + Stage 2 评分） | `qwen3-vl:4b` | ~2.4 GB | 图片评测用，可选 |

**拉取命令：**

```bash
ollama pull qwen3:4b-instruct
ollama pull qwen3-vl:4b
```

---

## 二、ComfyUI 模型

ComfyUI 安装目录：`/workspace/ComfyUI`（环境变量 `COMFYUI_DIR`）

### Checkpoint（底模）

| 文件名 | 大小 | 用途 |
|--------|------|------|
| `sd_xl_base_1.0.safetensors` | ~6.9 GB | SDXL 1.0 Base，卡通教学图生成 |

**目标路径：**

```
/workspace/ComfyUI/models/checkpoints/sd_xl_base_1.0.safetensors
```

**下载方式：**

```bash
# 方式一：从 HuggingFace
cd /workspace/ComfyUI/models/checkpoints/
wget https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors

# 方式二：从 CivitAI (需注册)
# https://civitai.com/models/133679/sdxl-base-10
```

### VAE

**不需要单独下载。** SDXL Base 1.0 自带 VAE（工作流使用 CheckpointLoaderSimple 的内置 VAE）。

### LoRA

当前工作流 **不使用 LoRA**，无需下载。

---

## 三、工作流文件

setup-cloudstudio.sh 会自动将工作流从 `backend/workflows/` 复制到 `/workspace/workflows/`。

| 文件 | 路径 |
|------|------|
| sdxl_cartoon_api.fixed.json | `/workspace/workflows/sdxl_cartoon_api.fixed.json` |

---

## 四、Piper TTS 模型

Piper 语音合成，来自 [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)。

| 音色 | 模型文件 | 配置文件 | 大小（约） |
|------|---------|----------|-----------|
| 女声 (A 角色) | `en_US-lessac-medium.onnx` | `en_US-lessac-medium.onnx.json` | ~50 MB |
| 男声 (B 角色) | `en_US-ryan-medium.onnx` | `en_US-ryan-medium.onnx.json` | ~50 MB |

**目标路径：**

```
/workspace/models/piper/en_US-lessac-medium.onnx
/workspace/models/piper/en_US-lessac-medium.onnx.json
/workspace/models/piper/en_US-ryan-medium.onnx
/workspace/models/piper/en_US-ryan-medium.onnx.json
```

**Piper 可执行文件：**

```bash
# 从 GitHub Releases 下载
# https://github.com/rhasspy/piper/releases
# 选择 Linux x86_64 版本，解压后将 piper 放入 PATH
```

---

## 五、Whisper 模型

| 模型 | 大小 | 用途 |
|------|------|------|
| `base.en` | ~142 MB | 英语语音转文字（音频校验用） |

**首次使用时会自动下载**到 `~/.cache/whisper/`，无需手动下载。

但需确保 openai-whisper 已安装：

```bash
pip install openai-whisper
```

---

## 六、模型下载状态检查清单

| 模型 | 路径 | 已下载？ |
|------|------|----------|
| qwen3:4b-instruct | Ollama (自动管理) | ⬜ |
| qwen3-vl:4b | Ollama (自动管理) | ⬜ |
| sd_xl_base_1.0.safetensors | /workspace/ComfyUI/models/checkpoints/ | ⬜ |
| en_US-lessac-medium | /workspace/models/piper/ | ⬜ |
| en_US-ryan-medium | /workspace/models/piper/ | ⬜ |
| whisper base.en | ~/.cache/whisper/ (自动) | ⬜ |
| 工作流 JSON | /workspace/workflows/ | ⬜ (自动复制) |

---

## 七、缺少部分模型的影响

项目设计为**渐进降级**，部分模型缺失不影响核心功能：

| 缺失模型 | 影响 |
|----------|------|
| 全部 Ollama 模型 | 无法生成脚本/评测/题目，**核心功能不可用** |
| qwen3:4b-instruct | 无法做语义评测和脚本生成 |
| qwen3-vl:4b | 无法做图片视觉评测，规则评测仍可用 |
| sd_xl_base_1.0.safetensors | 无法生成图片，其他功能正常 |
| Piper 两个音色 | 无法生成音频，其他功能正常 |
| Whisper base.en | 无法做音频校验（转写），其他功能正常 |
