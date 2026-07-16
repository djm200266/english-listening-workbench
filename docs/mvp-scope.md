# MVP 范围定义（V0.1）

> 收敛自 PRD V0.1 + 需求分析 | 首版主题：Asking for and Giving Directions

---

## 一、七个页面（MVP必做）

| # | 页面 | 路由 | 核心职责 | Mock模式 | Real模式 |
|---|------|------|----------|----------|----------|
| P1 | 任务中心 | `/` | 任务列表+状态筛选+快捷操作 | 本地JSON读写 | API直连Ollama |
| P2 | 新建任务 | `/task/new` | 收集约束+校验+Prompt建议 | 前端校验规则 | POST /api/tasks |
| P3 | 脚本审核 | `/task/:id/script` | 编辑对话+文本门禁+确认版本 | 内嵌示例JSON | Ollama生成+评测 |
| P4 | 多模态结果 | `/task/:id/assets` | 图片/音频/题目预览+局部重生成 | 本地占位素材 | ComfyUI+Piper+Ollama |
| P5 | 评测报告 | `/task/:id/report` | 总分+五维分项+问题列表 | 内置模拟评测JSON | 规则引擎+模型评测 |
| P6 | Bad Case详情 | `/task/:id/badcase/:bcid` | 错误定位+证据对照+修复建议 | 固定示例BC | P-BC-EXPLAIN生成 |
| P7 | 审核导出 | `/task/:id/export` | 审核清单+预览+打包下载 | 本地文件拼接 | 完整素材包导出 |

---

## 二、主流程（8步）

```
1. 新建任务 → 填写约束 → 校验通过 → 生成 task_id
2. 提交生成脚本 → Ollama (qwen3:4b) → 结构化对话JSON
3. 查看文本评测 → 编辑修改 → 文本门禁通过 → 确认脚本版本
4. 并行生成图片(ComfyUI) + 音频(Piper) + 题目(Ollama)
5. 各模块独立展示 → 失败的不隐藏成功的
6. 规则评测 + 跨模态检查 → 生成评测报告
7. 局部修复Bad Case → 仅重做出错模块 → 回归评测
8. 审核清单全绿 → 教师确认 → 导出素材包
```

> **核心原则**：生成成功 ≠ 质量通过 ≠ 教师审核通过。三种状态分离。

---

## 三、核心字段（MVP最小集）

### 任务配置（18字段）

| 字段 | 类型 | 必填 | MVP默认/约束 |
|------|------|------|-------------|
| task_id | string | 是 | `G7_DIR_{序号}`，系统生成 |
| task_name | string | 是 | 教师编辑 |
| grade | enum | 是 | 固定 `grade_7` |
| lesson_type | enum | 是 | 固定 `listening_speaking` |
| topic | string | 是 | `Asking for Directions` |
| scenario | string | 是 | 教师填写，如"学生询问图书馆位置" |
| required_vocabulary | string[] | 是 | 至少1个 |
| optional_vocabulary | string[] | 否 | — |
| target_patterns | string[] | 是 | 至少1个 |
| dialogue_turns | integer | 是 | 6–12，默认8 |
| speaker_count | integer | 是 | 固定2 |
| audio_duration_target_sec | integer | 是 | 30–90，默认50 |
| speech_rate | enum | 是 | `slow` / `normal`，默认`normal` |
| question_type | enum | 是 | 固定 `single_choice` |
| question_count | integer | 是 | 2–5，默认3 |
| additional_instruction | text | 否 | — |
| created_by | string | 是 | 系统记录 |
| created_at | datetime | 是 | 系统时间戳 |

### 生成结果（每个模态10字段）

| 通用字段 | 图片特有 | 音频特有 | 题目特有 |
|----------|----------|----------|----------|
| `{modality}_id` | `image_url` | `audio_url` | `questions` (JSON[]) |
| `source_script_version` | | `audio_duration_actual_sec` | |
| `generation_status` | | `speaker_profiles` (JSON) | |
| `model_name` | | | |
| `model_version` | | | |
| `prompt_version` | | | |
| `generation_latency_ms` | | | |
| `estimated_cost` | | | |

### 评测记录（最小集）

`evaluation_id`, `target_type`, `target_id`, `overall_score`, `pass_status`, `severity`(S0–S4), `error_type`, `error_location`, `evidence`, `repair_suggestion`, `evaluator_type`, `teacher_feedback`

---

## 四、状态流转

```
draft → generating → evaluating → pending_review → approved → exported
              ↘ partial_success → (retry) ↗
              ↘ failed → (retry) ↗
evaluating → needs_fix → (fix+retry) ↗
any → outdated (脚本版本变更时，下游素材)
```

| 状态 | 含义 | MVP允许操作 |
|------|------|------------|
| `draft` | 未提交或脚本未确认 | 编辑、删除、提交 |
| `generating` | 生成中 | 查看进度、取消 |
| `partial_success` | 部分模块失败 | 查看结果、局部重试 |
| `evaluating` | 评测中 | 查看进度 |
| `failed` | 不可恢复失败 | 重试、查看原因 |
| `needs_fix` | 门禁未通过 | 查看Bad Case、修复 |
| `outdated` | 基于旧脚本版本 | 重新生成 |
| `pending_review` | 自动评测通过 | 教师审核、退回 |
| `approved` | 教师确认 | 导出 |
| `exported` | 已导出 | 下载、再次导出 |

---

## 五、Mock模式

### 设计原则
- Mock模式 = 零外部依赖，纯前端可运行全部7页
- 与Real模式共享同一组件树，通过顶层 `mode` 状态切换
- Mock数据内嵌在组件或独立 mock/ 目录中

### Mock数据范围

| 页面 | Mock内容 |
|------|----------|
| 任务中心 | 3-5个示例任务，覆盖 draft/generating/needs_fix/approved/exported 状态 |
| 新建任务 | 预填示例约束（问路主题） |
| 脚本审核 | 内嵌一段8轮双角色对话JSON |
| 多模态结果 | 本地PNG占位图 + 静默音频占位 + 3道示例选择题 |
| 评测报告 | 模拟评测JSON（总分85，1个S2警告） |
| Bad Case详情 | 1个示例BC：答案错误，附证据和修复建议 |
| 审核导出 | 模拟文件列表 + 导出按钮（实际下载一个JSON） |

### 切换方式
- 顶部全局开关：`Mock 模式 / Real 模式`
- 配置文件 `config.json` 记录默认模式
- Mock模式下所有API调用替换为本地函数返回Promise

---

## 六、Real模式接口占位

所有Real模式接口使用统一前缀 `/api/v1`。

| 方法 | 路径 | 用途 | Mock返回 |
|------|------|------|----------|
| GET | `/api/v1/tasks` | 任务列表 | mock-tasks.json |
| POST | `/api/v1/tasks` | 创建任务 | 生成task_id |
| GET | `/api/v1/tasks/{id}` | 任务详情 | mock-task-detail.json |
| PUT | `/api/v1/tasks/{id}` | 更新配置 | 更新后的task |
| DELETE | `/api/v1/tasks/{id}` | 删除任务 | `{ok: true}` |
| POST | `/api/v1/tasks/{id}/script/generate` | 生成脚本 | mock-script.json |
| PUT | `/api/v1/tasks/{id}/script` | 保存编辑 | 更新后的script |
| POST | `/api/v1/tasks/{id}/script/confirm` | 确认脚本 | `{script_version: 2}` |
| POST | `/api/v1/tasks/{id}/image/generate` | 生成图片 | mock-image-url |
| POST | `/api/v1/tasks/{id}/audio/generate` | 生成音频 | mock-audio-url |
| POST | `/api/v1/tasks/{id}/questions/generate` | 生成题目 | mock-questions.json |
| POST | `/api/v1/tasks/{id}/evaluate` | 运行评测 | mock-evaluation.json |
| GET | `/api/v1/tasks/{id}/evaluations` | 评测结果 | mock-evaluation.json |
| GET | `/api/v1/tasks/{id}/badcases` | BC列表 | mock-badcases.json |
| GET | `/api/v1/tasks/{id}/badcases/{bcid}` | BC详情 | mock-bc-detail.json |
| PUT | `/api/v1/tasks/{id}/badcases/{bcid}/feedback` | 教师反馈 | `{ok: true}` |
| POST | `/api/v1/tasks/{id}/export` | 导出 | 文件流 |

---

## 七、模型接入范围

| 模型/服务 | 用途 | 接入方式 | MVP范围 |
|-----------|------|----------|---------|
| **Ollama + qwen3:4b-instruct** | 脚本生成、题目生成 | `POST /api/generate` (Ollama API) | P-SCRIPT + P-QUESTION 两个Prompt |
| **Ollama + qwen3:4b-instruct** | 文本评测、题目评测、BC解释 | `POST /api/generate` | P-SCRIPT-EVAL + P-QUESTION-EVAL + P-BC-EXPLAIN |
| **ComfyUI + SDXL Base 1.0** | 情境图生成 | ComfyUI API (`/prompt` + `/history`) | P-IMAGE Prompt，5种风格可选 |
| **Piper TTS** | 双角色音频合成 | 命令行调用或Python binding | 2个音色（男性+女性），语速参数 |
| **Whisper base.en** | ASR音频回转校验 | Python binding 或 CLI | 转写文本 + 与脚本比对 |
| **前端** | 多模态评测（图片关系判断） | MVP暂不接入 | V0.1用规则+LLM替代，多模态模型列为P1 |

> **Prompt清单**（7个，全部初始版本 v1.0）：P-SCRIPT, P-SCRIPT-EVAL, P-IMAGE, P-IMAGE-EVAL, P-QUESTION, P-QUESTION-EVAL, P-BC-EXPLAIN

---

## 八、评测和Bad Case最小闭环

### 规则评测（MVP必须，纯代码实现）

| 检查项 | 实现方式 | 严重度 |
|--------|----------|--------|
| 必填字段完整 | 前端校验 + 后端校验 | 缺失阻止生成 |
| 对话轮次 = 配置值 | 计数JSON数组 | S2 |
| 词汇覆盖率 100% | 字符串包含匹配（词形归一化后） | S2 |
| 句型覆盖率 100% | 正则/子串匹配 | S2 |
| 文件可播放 | 音频文件头校验 + 时长>0 | S3 |
| 时长偏差 ≤20% | `|actual - target| / target` | S2 |
| 题目数量 = 配置值 | 计数 | S2 |
| 每题有唯一答案 | JSON结构校验 | S3 |
| 素材完整率 100% | 5项素材全部存在 | <100%不可导出 |
| 版本一致 | `source_script_version == current_script_version` | S3 |

### 模型评测（MVP通过Ollama实现）

| 评测对象 | 评测维度 | LLM Judge | 输出 |
|----------|----------|-----------|------|
| 脚本 | 语法正确性 + 难度适配 + 连贯性 | P-SCRIPT-EVAL | 0-5分 + 错误句/超纲词 + 理由 |
| 题目 | 可答性 + 答案唯一性 | P-QUESTION-EVAL | 通过/不通过 + 证据 |
| Bad Case | 错误诊断+修复建议 | P-BC-EXPLAIN | 错误/原因/建议 |

### 跨模态评测（规则实现，不用模型）

| 检查 | 方法 | 严重度 |
|------|------|--------|
| 音频-脚本一致 | ASR转写 vs 脚本字符串比对 | S3 |
| 版本一致 | `source_script_version` 比对 | S3 |

> MVP暂不实现跨模态图文关系评测（需多模态模型），列为P1。

### Bad Case最小闭环

```
评测发现问题 → 生成BC记录(severity/type/location/evidence)
→ 前端BC详情页展示 → 教师标记 agree/false_positive/fixed
→ 如fixed → 局部重生成 → 仅触发相关规则评测
→ 教师确认修复 → 门禁通过
```

### 门禁条件（简化版）

| 条件 | 要求 |
|------|------|
| 综合得分 | 总分 ≥ 80（配置项，可调） |
| 严重错误 | 无 S3/S4 |
| 素材完整 | 5项素材全部存在 |
| 答案正确率 | 100% |
| 版本一致 | 全部基于当前脚本版本 |
| **一票否决** | 答案与音频相反、音频不可播放、版本错配 |

---

## 九、首版明确不做的功能

| 不做 | 原因 | 版本计划 |
|------|------|----------|
| 多模态图文评测 | 需多模态模型，模型选型未定 | V0.2 |
| 图像空间关系自动检查 | 同上 + 技术难度高 | V0.2 |
| 上传已有脚本（P1-01） | P1优先级 | V0.2 |
| 上传已有素材质检（P1-02） | P1优先级 | V0.2 |
| 任务模板（P1-03） | P1优先级 | V0.2 |
| 多模型对比（P1-04） | P1优先级 | V0.2 |
| 批量任务（P1-05） | P1优先级 | V0.2 |
| 自定义Rubric（P1-06） | P1优先级 | V0.2 |
| 团队共享（P1-07） | P1优先级 | V0.2 |
| 学生端/课堂互动 | 非目标用户 | 不计划 |
| 学校管理/LMS集成 | 非目标场景 | 不计划 |
| 自训练模型 | 超出MVP范围 | 不计划 |
| 多语言支持 | 首版英语 | V1.0 |
| 全年级/全学科 | MVP聚焦七年级 | V1.0 |
| 无教师审核自动发布 | 安全红线 | 不计划 |
| 数据库（MySQL/PostgreSQL） | MVP用JSON文件 | V0.2 |
| 用户认证系统 | MVP单用户 | V0.2 |

---

## 十、MVP验收标准（10条）

| # | 验收项 | 标准 |
|---|--------|------|
| AC-01 | 7页面Mock模式可走通 | 全部页面可渲染、可交互，无白屏/报错 |
| AC-02 | 任务CRUD | 可创建、查看、编辑、删除任务 |
| AC-03 | 脚本生成+审核 | Mock返回结构化对话；Real模式Ollama返回合法JSON |
| AC-04 | 多模态生成 | 三个模块独立状态，失败不隐藏成功 |
| AC-05 | 规则评测10项 | 全部10项规则可执行并返回结果 |
| AC-06 | 门禁判定 | S3/S4 阻止导出，版本不一致标记outdated |
| AC-07 | Bad Case闭环 | 可查看BC详情 → 标记反馈 → 局部重生成 → 回归评测 |
| AC-08 | 版本绑定 | 脚本修改 → 下游素材自动 outdated |
| AC-09 | 导出 | 可打包下载（Mock模式下载JSON，Real模式下载ZIP） |
| AC-10 | 模式切换 | Mock/Real 开关可正常切换，Real模式下接口不可用时给出友好提示 |
