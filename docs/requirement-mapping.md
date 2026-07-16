# 需求映射表

> 基于 PRD V0.1 | 当前实现状态：**无代码实现**（项目仅有 PRD 文档和原型参考图）

---

## 一、功能需求映射（P0）

| 需求编号 | 需求描述 | 所属页面 | 前端组件 | 后端接口 | 数据字段 | 正常流程 | 异常流程 | 验收标准 | 实现状态 |
|----------|----------|----------|----------|----------|----------|----------|----------|----------|----------|
| AC-F01 | 任务创建：填写并提交全部P0配置字段 | 新建任务 | TaskForm（表单）、FieldValidator（校验）、PromptAssistant（Prompt建议） | POST /api/tasks | task_id, task_name, grade, lesson_type, topic, scenario, required_vocabulary, optional_vocabulary, target_patterns, dialogue_turns, speaker_count, audio_duration_target_sec, speech_rate, question_type, question_count, additional_instruction | 填写字段→实时校验→提交→生成task_id | 必填缺失（阻止+高亮）、参数越界（恢复合法值+提示）、约束冲突（提示+建议值）、敏感信息（阻止+脱敏） | 提交后生成唯一task_id，所有P0字段可填写保存 | ❌ 未实现 |
| AC-F02 | 输入校验：缺失/越界/冲突时阻止生成 | 新建任务 | FieldValidator（字段级校验）、ConflictDetector（冲突检测）、SensitiveInfoFilter（敏感信息过滤） | POST /api/tasks/validate | 全部任务配置字段 | 字段级实时校验→冲突检测→通过后允许提交 | 必填缺失/参数越界/约束冲突/敏感信息→分别处理 | 全异常组合通过测试，每项正确阻止+定位 | ❌ 未实现 |
| AC-F03 | 脚本生成：结构化双角色英语对话 | 脚本审核 | ScriptEditor（结构化编辑器）、ScriptPreview（预览）、VersionBadge（版本标签） | POST /api/tasks/{id}/script/generate | script_id, script_version, dialogue_script(JSON), script_status, model_name, model_version, prompt_version, generation_latency_ms, estimated_cost | 调用LLM生成→返回JSON→渲染对话→版本记录 | JSON格式错误（自动修复1次→重试主模型→备用模型→失败标记） | JSON可解析，轮次与配置一致，角色不少于配置数 | ❌ 未实现 |
| AC-F04 | 脚本门禁：未确认脚本前禁止下游生成 | 脚本审核 | TextGateBarrier（门禁状态）、GenerateButton（条件启用）、ConfirmButton（确认按钮） | PUT /api/tasks/{id}/script/confirm | script_status(draft→confirmed) | 脚本通过文本评测→教师确认→script_status=confirmed→启用下游 | S3/S4内容阻止确认，人工编辑后需重新评测 | 未确认前下游生成按钮不可用，状态权限正确 | ❌ 未实现 |
| AC-F05 | 多模态生成：图片+双角色音频+题目+答案 | 多模态结果 | ImageCard（图片预览/放大/重生成）、AudioCard（播放/波型/下载）、QuestionCard（题干/选项编辑）、GenerationProgressBar（进度） | POST /api/tasks/{id}/image/generate, POST /api/tasks/{id}/audio/generate, POST /api/tasks/{id}/questions/generate | image_id/url/source_script_version, audio_id/url/duration_actual_sec/source_script_version/speaker_profiles, question_set_id/questions(JSON)/source_script_version, generation_status, model_name, model_version, prompt_version | 确认脚本→并行调用图片/音频/题目生成→各模块独立状态展示 | 图片超时（自动重试1次→保留其他成功）、音频不可播放（重新调用TTS→校验→标记）、题目不完整（结构化修复→重生成→标记失败） | 每个模块有独立状态，任一失败不隐藏其他成功结果 | ❌ 未实现 |
| AC-F06 | 自动评测：分项分数+总分+通过状态+证据 | 评测报告 | ScoreDashboard（总分仪表盘）、DimensionBreakdown（五维分项）、PassStatusBadge（通过/不通过）、EvidencePanel（证据展示） | POST /api/tasks/{id}/evaluate | evaluation_id, evaluation_version, target_type, target_id, overall_score, dimension_scores(JSON), pass_status, error_type, severity, error_location, evidence, suspected_cause, repair_suggestion, evaluator_type, evaluator_model, evaluated_at | 各模态评测→跨模态评测→汇总总分→生成门禁判断→展示报告 | 评测器超时（重试→标记"未完成评测"）、结论冲突（人工复核）、证据缺失（不进入一票否决） | 报告可追溯到素材版本，不能只显示总分不展示S3/S4证据 | ❌ 未实现 |
| AC-F07 | Bad Case：错误位置+类型+等级+原因+修复建议 | Bad Case详情 | BadCaseDetail（错误详览）、ErrorEvidenceComparison（原内容vs证据对照）、RepairSuggestionPanel（修复建议）、JumpToEditorButton（跳转编辑） | GET /api/tasks/{id}/badcases | error_type, severity(S0-S4), error_location, evidence, suspected_cause, repair_suggestion, target_type, target_id | 点击评测问题→进入Bad Case详情→查看证据+原因→执行修复/跳转编辑 | 无 | 支持跳转对应模块编辑位置 | ❌ 未实现 |
| AC-F08 | 局部重生成：单一模块不清空其他模块 | 多模态结果/评测报告 | RegenerateButton（局部重生成）、RegenerationProgress（进度+影响范围提示） | POST /api/tasks/{id}/{module}/regenerate | 仅更新目标模块的generation_status和相关评测 | 选择模块→触发重生成→仅影响当前模块→相关评测重新运行 | 生成失败不覆盖旧版本→保留原素材 | 仅触发相关评测，不清空其他成功模块 | ❌ 未实现 |
| AC-F09 | 版本绑定：脚本修改→旧素材标记outdated | 全局 | OutdatedBadge（过期标记）、VersionMismatchWarning（版本不一致警告）、ExportBlocker（导出阻塞） | PUT /api/tasks/{id}/script → 级联更新 | source_script_version vs current_script_version, generation_status=outdated | 脚本保存→script_version++→扫描下游source_script_version→不一致=outdated | 版本来源缺失（阻止跨模态评测→要求重生成）、并发覆盖（提示冲突→保留双草稿）、回滚依赖错误（重算依赖→标记不一致） | 过期素材不可导出，旧版本保留用于审计和回滚 | ❌ 未实现 |
| AC-F10 | 审核导出：质量门禁+教师审核→打包导出 | 最终审核导出 | AuditChecklist（审核清单）、FinalPreview（最终预览）、ExportFormatSelector（格式选择）、DisclaimerNotice（免责声明） | POST /api/tasks/{id}/export | 导出包：脚本+图片+音频+题目+答案+评测报告+版本清单 | 审核清单全绿→教师确认→导出→生成文件包 | S3/S4（阻止导出→展示阻断原因）、未完成审核（阻止→提示补全）、打包失败（保留状态→可重试）、文件缺失（列出缺失→不生成不完整包） | 仅当门禁通过+教师终审后允许导出，导出包完整 | ❌ 未实现 |

---

## 二、P0功能维度映射（F01-F12）

| 需求编号 | 需求描述 | 所属页面 | 前端组件 | 后端接口 | 数据字段 | 正常流程 | 异常流程 | 验收标准 | 实现状态 |
|----------|----------|----------|----------|----------|----------|----------|----------|----------|----------|
| F01 | 创建课程任务 | 新建任务 | TaskForm | POST /api/tasks | task_id, task_name, grade, lesson_type, topic, scenario, required_vocabulary, optional_vocabulary, target_patterns, dialogue_turns, speaker_count, audio_duration_target_sec, speech_rate, question_type, question_count, additional_instruction | 填写约束→提交 | 必填缺失/参数越界/约束冲突/敏感信息 | task_id生成 | ❌ 未实现 |
| F02 | 完整性与参数校验 | 新建任务 | FieldValidator, ConflictDetector | POST /api/tasks/validate | 同F01 | 实时校验→通过→允许提交 | 按6.1异常流程表处理 | 阻止无效调用 | ❌ 未实现 |
| F03 | 双角色英语对话脚本生成 | 脚本审核 | ScriptEditor, VersionBadge | POST /api/tasks/{id}/script/generate | script_id, script_version, dialogue_script(JSON), script_status, model_name, model_version, prompt_version, generation_latency_ms, estimated_cost | LLM生成→JSON渲染 | JSON格式错误/服务不可用 | 结构化输出 | ❌ 未实现 |
| F04 | 编辑+重生成+确认脚本 | 脚本审核 | ScriptEditor, TextGate, AIEditButton | PUT /api/tasks/{id}/script, POST /api/tasks/{id}/script/confirm | script_status(draft↔confirmed), script_version(递增) | 编辑→评测→确认→锁定 | 高风险内容阻止确认 | 版本锁定+门禁 | ❌ 未实现 |
| F05 | 情境图生成 | 多模态结果 | ImageCard | POST /api/tasks/{id}/image/generate | image_id, image_url, image_source_script_version, generation_status | 基于确认脚本生成 | 超时（自动重试1次） | 图片可查看 | ❌ 未实现 |
| F06 | 双角色听力音频生成 | 多模态结果 | AudioCard(播放/波形/下载) | POST /api/tasks/{id}/audio/generate | audio_id, audio_url, audio_duration_actual_sec, audio_source_script_version, speaker_profiles | 基于确认脚本+音色/语速生成 | 不可播放（重新调用TTS校验） | 音频可播放 | ❌ 未实现 |
| F07 | 选择题+答案生成 | 多模态结果 | QuestionCard(题干/选项/答案/编辑) | POST /api/tasks/{id}/questions/generate | question_set_id, questions(JSON), question_source_script_version | 基于确认脚本生成N道单选 | 数量不足/缺答案（结构化修复→重生成） | 每题有唯一正确答案 | ❌ 未实现 |
| F08 | 单模态质量检查 | 评测报告 | DimensionBreakdown, EvidencePanel | POST /api/tasks/{id}/evaluate | evaluation_id, target_type, overall_score, dimension_scores, pass_status, error_type, severity, evidence, evaluator_type | 规则+LLM评测各模态 | 评测器超时/结论冲突/证据缺失 | 分项分数+证据 | ❌ 未实现 |
| F09 | 跨模态关系检查 | 评测报告 | CrossModalCheckResult | POST /api/tasks/{id}/evaluate/cross-modal | target_type=cross_modal, evidence(关系对照), severity | 检查7种跨模态关系 | 任何不一致→对应S2/S3 | 降低组合错误 | ❌ 未实现 |
| F10 | 问题定位与解释 | Bad Case详情 | BadCaseDetail, EvidenceComparison, RepairSuggestion, JumpToEditor | GET /api/tasks/{id}/badcases | error_type, severity, error_location, evidence, suspected_cause, repair_suggestion | 展示错误→原因→修复建议 | 无 | 可跳转编辑 | ❌ 未实现 |
| F11 | 局部编辑/重生成 | 多模态结果 | RegenerateButton, ImpactScopeIndicator | POST /api/tasks/{id}/{module}/regenerate | 仅更新目标模块版本+相关评测 | 选择模块→局部重生成→回归评测 | 失败保留原版本 | 不清空其他模块 | ❌ 未实现 |
| F12 | 终审+素材打包 | 最终审核导出 | AuditChecklist, FinalPreview, ExportFormatSelector, Disclaimer | POST /api/tasks/{id}/export | 导出包（全部素材+评测报告+版本清单） | 审核→确认→打包→导出 | S3/S4/未审核/打包失败/文件缺失 | 完整可交付 | ❌ 未实现 |

---

## 三、P1功能维度映射（优先级较低）

| 需求编号 | 需求描述 | 所属页面 | 前端组件 | 后端接口 | 实现状态 |
|----------|----------|----------|----------|----------|----------|
| P1-01 | 上传已有脚本 | 新建任务/脚本审核 | ScriptUploader (文本粘贴/文件上传) | POST /api/tasks/{id}/script/upload | ❌ 未实现 |
| P1-02 | 上传已有素材质检 | 新建任务 | AssetUploader (图片/音频/题目上传) | POST /api/tasks/{id}/assets/upload | ❌ 未实现 |
| P1-03 | 任务模板 | 新建任务 | TemplateSelector, TemplateSaver | GET/POST /api/templates | ❌ 未实现 |
| P1-04 | 多模型对比 | 评测报告 | ModelComparisonTable | POST /api/tasks/{id}/compare | ❌ 未实现 |
| P1-05 | 批量任务 | 任务中心 | BatchTaskCreator, BatchProgressView | POST /api/tasks/batch | ❌ 未实现 |
| P1-06 | 自定义Rubric | 新建任务 | RubricEditor | PUT /api/rubric | ❌ 未实现 |
| P1-07 | 团队共享 | 任务中心 | ShareDialog, SharedTaskView | POST /api/tasks/{id}/share | ❌ 未实现 |

---

## 四、页面→组件→接口映射

| 页面 | 核心前端组件 | 核心后端接口 |
|------|-------------|-------------|
| 任务中心 | TaskList, TaskCard, StatusFilter, SearchBar, QuickActions(Continue/Copy/Delete/ReExport) | GET /api/tasks, DELETE /api/tasks/{id}, POST /api/tasks/{id}/copy, PUT /api/tasks/{id}/export |
| 新建任务 | TaskForm, FieldValidator, ConflictDetector, PromptAssistant, DraftSaver | POST /api/tasks, POST /api/tasks/validate, GET /api/prompts |
| 脚本审核 | ScriptEditor, ScorePanel, VersionBadge, TextGate, RegenerateButton, ConfirmButton | GET /api/tasks/{id}/script, PUT /api/tasks/{id}/script, POST /api/tasks/{id}/script/confirm, POST /api/tasks/{id}/script/evaluate |
| 多模态结果 | ImageCard, AudioCard(Player+Waveform), QuestionCard, GenerationProgressBar, OutdatedBadge | GET /api/tasks/{id}/assets, POST /api/tasks/{id}/{module}/generate, POST /api/tasks/{id}/{module}/regenerate |
| 评测报告 | ScoreDashboard, DimensionBreakdown(5 tabs), PassStatusBadge, ProblemList(filterable), GateConditionCheck | GET /api/tasks/{id}/evaluations, POST /api/tasks/{id}/evaluate |
| Bad Case详情 | BadCaseDetail, EvidenceComparison, RepairSuggestion, JumpToEditor, HistoryTimeline, TeacherFeedbackButton | GET /api/tasks/{id}/badcases/{id}, PUT /api/tasks/{id}/badcases/{id}/feedback, POST /api/tasks/{id}/{module}/regenerate |
| 最终审核导出 | AuditChecklist, FinalPreview(Tabs), ExportFormatSelector, DisclaimerNotice, ExportButton | GET /api/tasks/{id}/export-check, POST /api/tasks/{id}/export |

---

## 五、状态流转映射

| 当前状态 | 触发操作 | 目标状态 | 条件 |
|----------|----------|----------|------|
| (空) | 提交配置 | draft | 校验通过 |
| draft | 提交生成 | generating | 配置完整 |
| generating | 全部成功 | evaluating | 所有模块生成完毕 |
| generating | 部分失败 | partial_success | 至少一个模块失败 |
| partial_success | 局部重试成功 | evaluating | 失败模块恢复 |
| partial_success | 全部失败 | failed | 不可恢复 |
| evaluating | 评测完成(通过) | pending_review | 门禁通过 |
| evaluating | 评测完成(不通过) | needs_fix | 存在S2-S4 |
| needs_fix | 修复完成+重新评测 | pending_review | 门禁通过 |
| needs_fix | 脚本修改 | outdated(downstream) | 下游素材过期 |
| pending_review | 教师审核通过 | approved | 教师确认 |
| pending_review | 教师退回 | needs_fix | 教师发现问题 |
| approved | 导出成功 | exported | 打包成功 |
| * | 脚本版本变化 | outdated(下游素材) | source_script_version != current |
