# MVP默认决策

> **重要声明**：以下所有决策均为"暂定，可配置或后续校准"，不是已验证的最终结论。
> 任何标记为 📐 的数值项在 `config.json` 中集中管理，无需改代码即可调整。

---

## 一、技术栈

| 决策项 | 默认值 | 备注 |
|--------|--------|------|
| 前端框架 | React 18 + Vite + TypeScript | 与 `schedule-app/` 技术栈一致 |
| UI样式 | Tailwind CSS | 参考原项目 |
| 前端端口 | 5173 | Vite默认 |
| 后端框架 | Python 3.12 + FastAPI | AI/ML生态原生支持 |
| 后端端口 | 8000 | FastAPI默认 |
| 数据存储 | 本地JSON文件（`data/` 目录） | 单用户MVP，后续迁移SQLite |
| 文件存储 | 本地 `storage/` 目录（images/audio/exports） | 后续迁移OSS |
| 前后端通信 | REST API + JSON | `/api/v1/` 前缀 |
| API文档 | FastAPI自动生成的 OpenAPI (Swagger) | `/docs` 端点 |
| 包管理 | npm（前端）+ pip/uv（后端） | — |

## 二、模型接入

| 决策项 | 默认值 | 备注 |
|--------|--------|------|
| LLM服务 | Ollama（本地） | 端口 `11434` |
| 脚本/题目模型 | `qwen3:4b-instruct` | 4B参数，结构化输出能力好 |
| 评测/BC解释模型 | `qwen3:4b-instruct` | 复用同一模型，减少显存占用 |
| 图像生成 | ComfyUI（本地） | 端口 `8188` |
| 图像底模 | SDXL Base 1.0 | 开源，生态成熟 |
| 图片风格 | `cartoon`, `children_book`, `flat`, `watercolor`, `realistic` | 可在新建任务中选择 |
| TTS引擎 | Piper TTS（本地） | Python binding，离线运行 |
| TTS音色 | `en_US-lessac-low`（女声）+ `en_US-ryan-high`（男声） | 暂定，可在配置中换音色 |
| ASR引擎 | Whisper `base.en`（本地） | 英语专用，轻量 |
| 多模态评测模型 | **MVP不接入** | 用规则+LLM替代，V0.2评估 |

## 三、评测与门禁

| 决策项 | 默认值 | 备注 |
|--------|--------|------|
| 总分公式权重 | 📐 文本20% + 音频20% + 图片15% + 题目20% + 跨模态25% | PRD原值，`config.json` |
| 总分通过线 | 📐 ≥ 80 | `config.json`，校准后调整 |
| Bad Case Precision目标 | 📐 ≥ 80% | `config.json` |
| Bad Case Recall目标 | 📐 ≥ 85% | `config.json` |
| 音频时长偏差阈值 | 📐 ≤ 20% | `config.json` |
| LLM生成超时 | 📐 60s | `config.json` |
| 图像生成超时 | 📐 120s | `config.json` |
| TTS生成超时 | 📐 30s | `config.json` |
| 评测超时 | 📐 30s/项 | `config.json` |
| 自动重试次数 | 1次 | 失败保留成功结果 |
| S2处理 | 允许教师知情跳过（需填写理由） | S3/S4强制修复 |
| 一票否决 | 答案与音频相反、音频不可播放、版本错配 | 不依赖阈值，代码硬逻辑 |
| S3/S4阻止导出 | ✅ 阻止 | 展示阻断原因 |
| 教师审核后才能导出 | ✅ 强制 | 无审核=导出按钮灰色 |

## 四、版本与数据

| 决策项 | 默认值 | 备注 |
|--------|--------|------|
| 脚本版本号 | 从1递增的整数 | `script_version` |
| 版本过期规则 | `source_script_version ≠ current` → `outdated` | 自动标记 |
| 评测记录绑定 | 绑定具体素材版本 | 不模糊引用"最新" |
| 评测集格式 | JSON/YAML 文件，放在 `eval_sets/` | 开发集/测试集/回归集 |
| 评测集版本号 | `eval_v1.0`, `eval_v1.1`... | 记录变更内容 |

## 五、Prompt管理

| 决策项 | 默认值 | 备注 |
|--------|--------|------|
| Prompt存储 | `prompts/` 目录，每个Prompt一个 `.md` 文件 + 一个 `.json` 模板 | 版本化+可追溯 |
| System Prompt语言 | English（模型输入）+ 中文注释（给开发者看） | — |
| 输出格式 | 强制 JSON Schema | 字段缺失视为失败 |
| 初始版本号 | 全部 `v1.0` | 变更后递增 |

## 六、前端交互默认

| 决策项 | 默认值 | 备注 |
|--------|--------|------|
| Mock模式 | 默认开启（首次运行） | `config.json` 中 `"mode": "mock"` |
| 生成中进度展示 | 轮询 `/api/v1/tasks/{id}/status`，间隔 📐 2s | 后续可改为WebSocket |
| 红色标识 | S3/S4问题以红色标记 | 任务卡片+评测报告 |
| 删除确认 | 二次确认弹窗 | 已导出任务保留版本记录 |
| 字段冲突展示 | 展示原因+建议值 | — |
| 过期素材提示 | 显示"基于旧脚本版本" | 灰色+禁止进入终审 |
| 导出免责声明 | 导出页底部固定显示 | "AI生成内容需经教师审核后使用" |

## 七、安全与合规默认

| 决策项 | 默认值 | 备注 |
|--------|--------|------|
| 用户认证 | MVP不加登录 | 单用户场景 |
| 敏感信息过滤 | 输入检测学生姓名/联系方式/成绩→提示脱敏 | 前端+后端双检 |
| 不适龄内容 | S4标记+阻止导出 | LLM评测输出 |
| 审计日志 | 保留 model/prompt/version/operator/timestamp | JSON日志文件 |
| 免责声明 | 导出页固定展示 | — |

---

## 默认值汇总速查

```
前端端口:     5173
后端端口:     8000
Ollama端口:   11434
ComfyUI端口:  8188

脚本模型:     qwen3:4b-instruct (Ollama)
题目模型:     qwen3:4b-instruct (Ollama)
评测模型:     qwen3:4b-instruct (Ollama)
图像生成:     SDXL Base 1.0 (ComfyUI)
TTS:          Piper TTS
ASR:          Whisper base.en

数据存储:     本地JSON文件
图片存储:     storage/images/
音频存储:     storage/audio/
导出存储:     storage/exports/
Prompt存储:   prompts/
评测集存储:   eval_sets/

评测阈值:     全部在 config.json 中，使用PRD暂定值
门禁:         S3/S4 阻止导出，S2 允许跳过
导出:         教师审核后才能导出
版本:         脚本修改→下游标记outdated
```
