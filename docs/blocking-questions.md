# 阻塞性问题清单

> 从54条Open Questions中筛选真正阻塞首版开发的10个问题

---

## 筛选原则

- 只收录**不确认就无法开工**的问题（技术选型类、接口依赖类）
- 已有合理默认方案的问题、可边做边校准的问题，全部移入 `default-decisions.md`
- 编号保持可追溯性

---

| # | 原编号 | 问题 | 为什么阻塞 | 推荐默认方案 | 不确认时的处理方式 |
|---|--------|------|-----------|-------------|------------------|
| BQ-01 | OQ-01 | 前端框架是否用 React + TypeScript？ | 脚手架搭建、组件编写、类型定义全部依赖此决策 | **React + Vite + TypeScript**。理由：TS类型安全适合评测数据结构复杂的场景；Vite开发体验好；与现有 `schedule-app/` 技术栈一致 | 若选Vue，需重新评估组件库和状态管理方案，增加约1周 |
| BQ-02 | OQ-02 | 后端框架是否用 Python FastAPI？ | API定义、模型调用、任务编排全部依赖此决策 | **Python FastAPI**。理由：AI/ML生态原生支持（Ollama/Whisper/Piper的Python调用最方便）；自动生成OpenAPI文档 | 若选Node.js，Piper和Whisper需通过子进程调用，增加集成复杂度 |
| BQ-03 | OQ-03 | 数据存储是否接受MVP用JSON文件？ | 数据读写逻辑、版本管理、并发策略全部不同 | **MVP用本地JSON文件**。理由：单用户场景无需数据库；JSON可直接作为导出格式参考；迁移到SQLite/PostgreSQL成本低 | 若坚持用数据库，需增加SQLite集成+Migration框架，约+3天 |
| BQ-04 | OQ-06 | 脚本和题目生成LLM是否用 qwen3:4b-instruct？ | Prompt设计、JSON Schema约束、评测精度全部依赖具体模型能力 | **Ollama + qwen3:4b-instruct**。理由：本地运行免费用；4B参数对结构化对话足够；Ollama统一API降低接入成本 | 若换模型，需重新测试JSON Schema遵从率和生成质量；换云端API需考虑费用和网络依赖 |
| BQ-05 | OQ-08 | TTS是否用 Piper？ | 音频生成方案、音色配置、调用方式全部不同 | **Piper TTS**。理由：离线运行、低延迟、支持多音色、Python绑定方便 | 若换Azure/Google TTS，需网络+费用+API集成，但音质可能更好 |
| BQ-06 | OQ-09 | ASR是否用 Whisper base.en？ | 音频回转比对精度、部署方式和资源占用不同 | **Whisper base.en**。理由：英语专用base模型轻量、离线运行、Python生态好 | 若用更大模型(tiny/small/medium)，精度提升但资源消耗增加；若换云端ASR需网络+费用 |
| BQ-07 | OQ-07 | 图像生成是否用 ComfyUI + SDXL Base 1.0？ | 图像生成的技术栈、工作流设计、Prompt格式全部不同 | **ComfyUI + SDXL Base 1.0**。理由：工作流可配置、支持多个checkpoint、API成熟、本地运行 | 若换DALL-E/Midjourney API，需网络+费用，但空间关系可控性可能更好；若换Flux，需调整工作流 |
| BQ-08 | OQ-18 | 导出格式先支持哪几种？ | 导出打包逻辑、文件命名、前端UI全部依赖此决策 | **ZIP包**，内含：`script.txt`、`image.png`、`audio.mp3`、`questions.json`、`report.json`、`manifest.json` | 若增加PDF/DOCX，需额外集成生成库，增加约3天 |
| BQ-09 | OQ-14 | `dialogue_script` JSON Schema 能否先定一版？ | 脚本生成Prompt输出格式、前端编辑器渲染、评测规则解析全部依赖Schema | 见下方推荐Schema | 若不定Schema，LLM输出格式不稳定，前端解析频繁出错 |

### BQ-09 推荐 Schema

```json
{
  "speakers": [{"id": "A", "name": "Student"}, {"id": "B", "name": "Librarian"}],
  "turns": [
    {"index": 1, "speaker": "A", "text": "Excuse me, where is the library?", "target_vocab": ["library"], "target_pattern": "Where is...?"}
  ]
}
```

| # | 原编号 | 问题 | 为什么阻塞 | 推荐默认方案 | 不确认时的处理方式 |
|---|--------|------|-----------|-------------|------------------|
| BQ-10 | OQ-41 | S2问题是否允许教师知情后跳过？ | 门禁逻辑、前端交互、状态流转全部不同 | **允许跳过S2但记录**。S3/S4强制修复不可跳过。前端展示S2警告+跳过理由输入框。理由：S2为"需修改"，不应等同于S3的"不可使用" | 若S2也强制修复，首次通过率会很低，教师体验差，且与PRD的S2定义矛盾 |

---

## 已排除的阻塞问题说明

以下类型的问题**不阻塞首版开发**，已移入 `default-decisions.md`：

- **阈值类**（OQ-29~37）：全部放入配置文件，用PRD暂定值，后续校准
- **供应商细节**（OQ-10）：多模态模型MVP不接入，问题自动消除
- **产品角色**（OQ-11~13）：不影响工程开工
- **PRD内部歧义**（OQ-20~22）：已在本表中给出默认解释（如OQ-41）
- **原型图细节**（OQ-23~28）：Mock模式开发过程中自然对齐
- **技术预研**（OQ-43~47）：Phase 3-5接入时逐个验证
- **架构细节**（OQ-48~51）：已在 `default-decisions.md` 中给出默认方案
- **合规**（OQ-52~54）：导出页免责声明即可，详细合规留待上线前
