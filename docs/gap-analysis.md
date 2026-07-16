# 差距分析（Gap Analysis）

> 基于 PRD V0.1  vs 当前项目现状 | 日期：2026-07-13

---

## 一、当前项目现状

### 已存在文件

```
english-listening-workbench/
└── docs/
    ├── PRD_v1.0.docx           ← 原始PRD（二进制）
    └── prototype-reference.png  ← 原型参考图
```

### 关键发现

**项目当前为零代码状态。** 仓库中仅有 PRD 文档和原型参考图，没有任何前后端代码、配置文件、或项目脚手架。

对比 CLAUDE.md 中引用的 `schedule-app/` 项目（日程清单打卡软件），`english-listening-workbench/` 是完全独立的新项目，尚未开始编码。

---

## 二、PRD要求 vs 当前现状总览

| 维度 | PRD要求 | 当前现状 | 差距等级 |
|------|---------|----------|----------|
| 产品文档 | PRD V0.1 已完成 | ✅ 已有（DOCX格式） | 无差距 |
| 原型设计 | 有参考原型图 | ⚠️ 有PNG图，待详细解析 | 需深入分析 |
| 前端框架 | 待选定（React/Vue等） | ❌ 无 | 🔴 阻塞 |
| 后端框架 | 待选定（Node/Python等） | ❌ 无 | 🔴 阻塞 |
| 数据库 | 待选定（SQLite/PostgreSQL等） | ❌ 无 | 🔴 阻塞 |
| LLM接入 | 文本生成+评测+Bad Case解释 | ❌ 无 | 🔴 阻塞 |
| TTS/ASR接入 | 双角色音频生成+回转校验 | ❌ 无 | 🔴 阻塞 |
| 图像生成接入 | 情境图生成+多模态评测 | ❌ 无 | 🔴 阻塞 |
| 7个页面 | 任务中心/新建/审核/多模态/报告/BC详情/导出 | ❌ 无 | 🔴 阻塞 |
| 12个P0功能 | F01-F12 | ❌ 无 | 🔴 阻塞 |
| 评测体系 | 规则+模型+跨模态+门禁 | ❌ 无 | 🔴 阻塞 |
| Prompt管理 | 7个Prompt版本化管理 | ❌ 无 | 🔴 阻塞 |
| 版本依赖 | source_script_version级联机制 | ❌ 无 | 🔴 阻塞 |
| 导出 | 素材打包 | ❌ 无 | 🔴 阻塞 |

---

## 三、前端缺失内容

### 3.1 技术选型与脚手架
| 项目 | 缺失内容 | 建议 |
|------|----------|------|
| 框架 | 未选定 | React + TypeScript（参考 schedule-app 的技术栈） |
| 构建工具 | 未配置 | Vite（参考 schedule-app） |
| UI组件库 | 未选定 | Tailwind CSS + Headless UI 或 Ant Design |
| 路由 | 未配置 | React Router（7个页面路由） |
| 状态管理 | 未选定 | React Context / Zustand |
| HTTP客户端 | 未配置 | Axios / Fetch |

### 3.2 页面组件（7页 × N组件）
| 页面 | 缺失组件 | 数量 |
|------|----------|------|
| 任务中心 | TaskList, TaskCard, StatusFilter, SearchBar, QuickActions | ~5 |
| 新建任务 | TaskForm, FieldValidator, ConflictDetector, PromptAssistant, DraftSaver | ~5 |
| 脚本审核 | ScriptEditor, ScorePanel, VersionBadge, TextGate, AIEditButton | ~5 |
| 多模态结果 | ImageCard, AudioCard(Player+Waveform), QuestionCard, ProgressBar, OutdatedBadge | ~5 |
| 评测报告 | ScoreDashboard, DimensionBreakdown(5 tabs), PassStatusBadge, ProblemList, GateCheck | ~5 |
| Bad Case详情 | BadCaseDetail, EvidenceComparison, RepairSuggestion, JumpToEditor, HistoryTimeline | ~5 |
| 审核导出 | AuditChecklist, FinalPreview, ExportSelector, Disclaimer, ExportButton | ~5 |
| **总计** | | **~35个组件** |

### 3.3 共享组件
| 组件 | 用途 | 涉及页面 |
|------|------|----------|
| LoadingSpinner | 生成中/评测中等待状态 | 全部 |
| ErrorBoundary | 错误兜底 | 全部 |
| StatusBadge | 状态标签（10种状态） | 任务中心/各详情页 |
| SeverityIcon | S0-S4严重度图标 | 评测报告/BC详情 |
| ConfirmDialog | 二次确认弹窗 | 任务中心/脚本审核 |
| Toast/Notification | 操作结果通知 | 全部 |
| VersionTag | 版本号展示 | 全部详情页 |

### 3.4 前端关键状态管理
| 状态类型 | 内容 | 复杂度 |
|----------|------|--------|
| 任务状态 | 10种全局状态，状态机流转 | 高 |
| 生成状态 | 4种素材×3种状态(generating/success/failed/outdated) | 高 |
| 评测状态 | 5模态评测×通过/不通过/人工复核 | 高 |
| 版本依赖 | script_version变更→级联outdated | 高 |
| 轮询/Push | 生成中和评测中的进度更新 | 中 |

---

## 四、后端缺失内容

### 4.1 技术选型与基础设施
| 项目 | 缺失内容 | 建议 |
|------|----------|------|
| 语言/框架 | 未选定 | Python (FastAPI) 或 Node.js (Express/Nest) |
| 数据库 | 未选定 | SQLite（MVP）+ 迁移到 PostgreSQL |
| 文件存储 | 未选定 | 本地文件系统（MVP）+ 迁移到 OSS/S3 |
| 任务队列 | 未选定 | Celery / BullMQ（异步生成+评测） |
| API设计 | 未定义 | RESTful API（约20+端点） |
| 认证 | 未设计 | 简单JWT / Session（MVP单用户可省略） |

### 4.2 API端点清单（预估）
| 模块 | 端点 | 方法 | 用途 |
|------|------|------|------|
| 任务 | /api/tasks | GET | 任务列表（分页+筛选） |
| 任务 | /api/tasks | POST | 创建任务 |
| 任务 | /api/tasks/{id} | GET | 任务详情 |
| 任务 | /api/tasks/{id} | PUT | 更新任务配置 |
| 任务 | /api/tasks/{id} | DELETE | 删除任务 |
| 校验 | /api/tasks/validate | POST | 配置校验 |
| 脚本 | /api/tasks/{id}/script/generate | POST | 生成脚本 |
| 脚本 | /api/tasks/{id}/script | PUT | 编辑脚本 |
| 脚本 | /api/tasks/{id}/script/confirm | POST | 确认脚本 |
| 图片 | /api/tasks/{id}/image/generate | POST | 生成图片 |
| 图片 | /api/tasks/{id}/image/regenerate | POST | 局部重生成图片 |
| 音频 | /api/tasks/{id}/audio/generate | POST | 生成音频 |
| 音频 | /api/tasks/{id}/audio/regenerate | POST | 局部重生成音频 |
| 题目 | /api/tasks/{id}/questions/generate | POST | 生成题目 |
| 题目 | /api/tasks/{id}/questions/regenerate | POST | 局部重生成题目 |
| 评测 | /api/tasks/{id}/evaluate | POST | 运行评测 |
| 评测 | /api/tasks/{id}/evaluations | GET | 获取评测结果 |
| Bad Case | /api/tasks/{id}/badcases | GET | Bad Case列表 |
| Bad Case | /api/tasks/{id}/badcases/{bc_id} | GET | BC详情 |
| Bad Case | /api/tasks/{id}/badcases/{bc_id}/feedback | PUT | 教师纠错反馈 |
| 导出 | /api/tasks/{id}/export-check | GET | 导出前提检查 |
| 导出 | /api/tasks/{id}/export | POST | 执行导出 |
| 状态 | /api/tasks/{id}/status | GET | 任务状态/进度 |

### 4.3 后端核心服务
| 服务 | 职责 | 依赖 |
|------|------|------|
| TaskService | 任务CRUD+状态管理 | 数据库 |
| ScriptService | 脚本生成+编辑+版本管理 | LLM API |
| ImageService | 图像生成+存储 | 图像生成API |
| AudioService | TTS合成+ASR回转+存储 | TTS API + ASR API |
| QuestionService | 题目生成+答案校验 | LLM API |
| EvaluationService | 规则评测+模型评测+跨模态检查 | LLM API + ASR API + 多模态模型API |
| BadCaseService | 错误归因+修复建议生成 | LLM API (P-BC-EXPLAIN) |
| ExportService | 素材打包+版本清单 | 文件存储 |
| WorkflowService | 工作流编排+节点状态管理 | 任务队列 |

### 4.4 数据库表设计（预估）
| 表名 | 对应实体 | 关键字段数 |
|------|----------|------------|
| tasks | 任务配置 | ~18字段 |
| scripts | 脚本 | ~5字段+JSON |
| images | 图片 | ~5字段 |
| audios | 音频 | ~7字段+JSON |
| question_sets | 题目集 | ~4字段+JSON数组 |
| evaluations | 评测记录 | ~18字段 |
| workflow_runs | 工作流日志 | ~12字段 |
| prompt_versions | Prompt管理 | ~5字段 |
| eval_datasets | 评测集管理 | ~5字段 |

---

## 五、模型接入依赖

### 5.1 外部模型/服务依赖清单

| 服务类型 | PRD中的用途 | 候选供应商/模型 | 接入复杂度 | 风险 |
|----------|------------|----------------|-----------|------|
| LLM (文本生成) | 脚本生成(P-SCRIPT)、题目生成(P-QUESTION) | Claude/GPT/DeepSeek | 中 | JSON Schema遵从性、幻觉、时延 |
| LLM (语义评测) | 脚本评测(P-SCRIPT-EVAL)、题目评测(P-QUESTION-EVAL)、BC解释(P-BC-EXPLAIN) | 同上 | 中 | 评测一致性、证据充分性 |
| 图像生成 | 情境图(P-IMAGE) | DALL-E/Stable Diffusion/Midjourney API | 中 | 实体准确性、空间关系可控性、风格一致性 |
| 多模态模型 | 图像评测(P-IMAGE-EVAL)、实体/关系检测 | GPT-4V/Claude Vision/Qwen-VL | 高 | 空间关系判断准确率、实体识别 |
| TTS | 双角色音频合成 | Azure Speech/Google Cloud TTS/开源方案 | 中 | 音色可区分性、自然度、语速控制 |
| ASR | 音频回转校验（文音一致性） | Whisper/Azure Speech/Google Speech | 中 | 准确率、口音适应性 |

### 5.2 关键不确定性
- 各模型API的**成本**暂未估算（PRD中 model_version 和 estimated_cost 字段已有定义但数值待定）
- **时延**指标（P50/P95）需基线测试后设定
- 多模态模型对**空间关系**的判断准确率需要验证
- TTS的**中文产品界面+英语生成**的混合场景支持

---

## 六、实现优先级

### 第一优先级：核心闭环（P0）

```
Phase 1: 项目脚手架 + 任务配置 + 脚本生成 + 脚本审核
  → 验证LLM接入 + 结构化输出 + 版本管理

Phase 2: 多模态生成 (图片+音频+题目)
  → 验证TTS/图像生成/ASR接入 + 并行生成 + 版本绑定

Phase 3: 评测体系 (规则+模型+跨模态+门禁)
  → 验证评测准确率 + Bad Case诊断 + 证据生成

Phase 4: 局部修复 + 导出 + 端到端闭环
  → 验证修复成功率 + 版本级联 + 导出完整性
```

### 第二优先级：体验提升（P1）

```
Phase 5: 上传已有素材 + 任务模板 + 自定义Rubric
Phase 6: 批量任务 + 多模型对比 + 团队共享
```

### 建议各阶段里程碑

| 阶段 | 目标 | 可交付物 |
|------|------|----------|
| Phase 1 | 用户可创建任务并生成+审核脚本 | 任务中心+新建任务+脚本审核页面可用 |
| Phase 2 | 完整多模态素材生成 | 图片+音频+题目可并行生成，版本绑定生效 |
| Phase 3 | 评测闭环 | 评测报告+Bad Case详情可用，S3/S4召回达目标 |
| Phase 4 | 完整用户闭环 | 局部修复+审核导出可用，端到端流程稳定 |

---

## 七、技术风险

| 风险 | 影响 | 可能性 | 缓解措施 |
|------|------|--------|----------|
| LLM输出格式不稳定（JSON Schema不遵从） | 脚本生成失败率高 | 高 | 结构化输出约束+自动修复+备用模型+规则兜底 |
| 图像生成无法精确控制空间关系 | 跨模态评测大量S3 | 高 | 降低空间关系期望精度；提供手动图片编辑；多轮生成择优 |
| ASR转写准确率不足 | 文音一致性评测不准确 | 中 | 选择高准确率ASR；支持人工抽检；设置合理阈值 |
| TTS音色区分度不够 | 双角色音频混淆 | 中 | 选择差异化明显的音色对；支持自定义音色参数 |
| 外部API不稳定/限流 | 生成中断 | 中 | 重试机制+队列+降级方案+状态恢复 |
| 评测器准确率不达标（Precision<80%/Recall<85%） | 大量误报/漏报 | 中 | 人工标注+阈值调优+评测集迭代+多评测器融合 |
| 生成时延过长 | 用户体验差 | 中 | 并行生成+进度指示+缓存+异步通知 |
| 版本级联逻辑复杂 | 数据一致性bug | 中 | 充分单元测试+并发控制+审计日志 |
| 安全合规（学生隐私/不适龄内容） | 法律风险 | 低 | 输入过滤+内容审核+教师审核门禁+免责声明 |
| 成本不可控 | 运营成本高 | 中 | 成本估算字段+用量限制+模型选择灵活性 |

---

## 八、建议实施顺序

### 推荐开发路线（按依赖关系排序）

```
Week 1-2: 项目初始化
  ├── 技术选型确认（参考 schedule-app 的 Tech Stack）
  ├── 前端脚手架（React+Vite+Tailwind+Router）
  ├── 后端脚手架（数据库+API框架）
  ├── 数据库表设计+Migration
  └── 基础认证（如需要）

Week 3-4: 任务管理 + 脚本工作流
  ├── 任务中心页面
  ├── 新建任务页面（含校验）
  ├── 脚本生成（LLM接入）
  ├── 脚本审核页面
  └── 版本管理基础

Week 5-6: 多模态生成
  ├── TTS接入+音频生成
  ├── 图像生成API接入
  ├── 题目生成（LLM）
  ├── 多模态结果页面
  └── 版本绑定+outdated机制

Week 7-8: 评测体系
  ├── 规则评测引擎
  ├── LLM Judge接入
  ├── ASR回转+文音比对
  ├── 跨模态一致性检查
  ├── 评测报告页面
  └── Bad Case详情页面

Week 9-10: 闭环完善
  ├── 局部重生成
  ├── 最终审核导出页面
  ├── 导出打包（ZIP/文件包）
  ├── 评测集管理基础
  └── 端到端测试+指标收集

Week 11-12: 优化+P1功能
  ├── 性能优化
  ├── 错误处理完善
  ├── 评测指标校准（基线测试+教师标注）
  └── P1功能按需开发
```

> **注意**：以上时间线为粗略估计，实际周期取决于团队规模和模型API联调复杂度。建议先做技术预研（Week 1），验证关键模型API的可用性和基本性能后再进入全面开发。
