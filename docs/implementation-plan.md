# 实施计划

> 7个阶段，每个阶段产出可独立验证 | 当前状态：零代码

---

## 阶段总览

```
阶段1: 前后端基础工程         ████░░░░░░░░░░  (2天)
阶段2: 七页Mock模式           ██████████░░░░  (4天)
阶段3: 接入Ollama             ████████████░░  (3天)
阶段4: 接入Piper + Whisper    ██████████████  (3天)
阶段5: 接入ComfyUI            ██████████████  (2天)
阶段6: 规则评测+Bad Case闭环  ██████████████  (3天)
阶段7: 真实流程测试+README    ██████████████  (2天)
                              ────────────────
                              预估总计: ~19天
```

---

## 阶段1：创建前后端基础工程

### 输入
- `docs/default-decisions.md`（技术栈默认方案）
- `docs/mvp-scope.md`（路由和接口清单）

### 输出
| 类型 | 内容 |
|------|------|
| 前端 | Vite + React + TypeScript 脚手架，Tailwind CSS配置，7个空页面路由，共享组件骨架 |
| 后端 | FastAPI 项目骨架，`/api/v1/` 路由前缀，CORS配置，`config.json` 加载 |
| 配置 | `config.json`（包含所有📐标记项），`prompts/` 目录（7个Prompt空模板） |

### 修改/创建文件

```
english-listening-workbench/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx                 (Router + mode state)
│       ├── config.ts              (读取 config.json)
│       ├── types.ts               (Task, Script, Evaluation 等类型)
│       ├── index.css              (Tailwind + 自定义主题色)
│       ├── api/
│       │   └── client.ts          (fetch 封装，Mock/Real 分支)
│       ├── mock/
│       │   └── data.ts            (Mock数据集中导出)
│       └── pages/
│           ├── TaskCenter.tsx
│           ├── TaskNew.tsx
│           ├── ScriptReview.tsx
│           ├── MultiModalAssets.tsx
│           ├── EvaluationReport.tsx
│           ├── BadCaseDetail.tsx
│           └── ExportReview.tsx
├── backend/
│   ├── requirements.txt
│   ├── main.py                    (FastAPI app入口)
│   ├── config.py                  (config.json加载)
│   ├── api/
│   │   └── router.py              (所有路由注册)
│   └── services/
│       └── task_service.py        (JSON文件读写)
├── config.json                    (全局配置)
├── prompts/                       (7个Prompt占位文件)
│   ├── P-SCRIPT.md
│   ├── P-SCRIPT-EVAL.md
│   ├── P-IMAGE.md
│   ├── P-IMAGE-EVAL.md
│   ├── P-QUESTION.md
│   ├── P-QUESTION-EVAL.md
│   └── P-BC-EXPLAIN.md
├── data/                          (任务JSON存储)
├── storage/                       (生成文件存储)
│   ├── images/
│   ├── audio/
│   └── exports/
└── eval_sets/                     (评测集存储)
```

### 验收标准
- [ ] `npm run dev` 启动前端，5173端口可访问，7个页面路由可切换（白屏可接受）
- [ ] `python main.py` 启动后端，8000端口 `/docs` 可访问Swagger
- [ ] 前端调用 `GET /api/v1/tasks`（Mock模式）返回空数组 `[]`
- [ ] `config.json` 被前后端正确加载
- [ ] 7个Prompt目录存在结构正确的占位文件

### 风险
- 低：纯脚手架，无外部依赖

---

## 阶段2：完成七页Mock模式

### 输入
- 阶段1脚手架
- `docs/mvp-scope.md`（页面模块+Mock数据范围+状态定义）
- `docs/prototype-reference.png`（视觉参考）

### 输出
7个页面全部可交互，Mock数据驱动，状态流转正确，无外部依赖。

### 修改/创建文件

```
frontend/src/
├── types.ts                        (完善所有类型)
├── App.tsx                         (mode切换 + 状态管理)
├── api/client.ts                   (完善Mock返回)
├── mock/data.ts                    (5个示例任务 + 全部Mock JSON)
├── components/                     (共享组件)
│   ├── Layout.tsx                  (顶栏+导航+Mock/Real开关)
│   ├── StatusBadge.tsx             (10种状态标签)
│   ├── SeverityTag.tsx             (S0-S4 颜色标签)
│   ├── LoadingSpinner.tsx
│   └── ConfirmDialog.tsx
├── pages/
│   ├── TaskCenter.tsx              (任务卡片列表+状态筛选+快捷操作)
│   ├── TaskNew.tsx                 (表单+实时校验+冲突检测+Prompt建议)
│   ├── ScriptReview.tsx            (左侧编辑+右侧评分+版本标签+确认)
│   ├── MultiModalAssets.tsx        (图片卡+音频卡+题目卡+过期标记)
│   ├── EvaluationReport.tsx        (总分+五维分项+问题列表+门禁状态)
│   ├── BadCaseDetail.tsx           (错误详情+证据对照+修复建议+反馈)
│   └── ExportReview.tsx            (审核清单+预览+导出+免责声明)
```

### 验收标准
- [ ] 任务中心：5个示例任务卡片显示，状态筛选可用，删除有二次确认
- [ ] 新建任务：表单校验生效（缺失高亮、越界提示），保存草稿→task_id生成
- [ ] 脚本审核：内嵌对话正确渲染，编辑可保存，确认后版本锁定
- [ ] 多模态结果：三卡片独立展示，其中一个设为failed确认不隐藏其他的
- [ ] 评测报告：总分+五维分项展示，S3问题红色标识，有Mock证据
- [ ] Bad Case详情：点击问题→跳转详情，展示位置/证据/建议，可标记反馈
- [ ] 审核导出：S3/S4任务导出按钮灰色+提示；通过任务可点击导出下载JSON
- [ ] Mock/Real开关可切换，Real模式调用空API时给出友好提示

### 风险
- 低：纯前端，不依赖外部服务

---

## 阶段3：接入Ollama

### 输入
- 阶段2的Mock模式前端
- 本地运行的 Ollama + `qwen3:4b-instruct`

### 输出
脚本生成、题目生成、文本评测、题目评测、BC解释共5个Real接口可用。

### 修改/创建文件

```
backend/
├── requirements.txt               (追加 ollama)
├── config.py                      (Ollama URL + model name)
├── services/
│   ├── ollama_client.py           (Ollama API封装)
│   ├── script_service.py          (P-SCRIPT调用+JSON解析+版本管理)
│   ├── question_service.py        (P-QUESTION调用+JSON解析)
│   └── eval_service.py            (P-SCRIPT-EVAL, P-QUESTION-EVAL, P-BC-EXPLAIN)
├── api/
│   ├── script_routes.py           (生成+编辑+确认)
│   ├── question_routes.py         (题目生成)
│   └── eval_routes.py             (评测触发)
prompts/
├── P-SCRIPT.md → P-SCRIPT.json    (System Prompt + JSON Schema 模板)
├── P-SCRIPT-EVAL.md → .json
├── P-QUESTION.md → .json
├── P-QUESTION-EVAL.md → .json
└── P-BC-EXPLAIN.md → .json
frontend/src/
├── api/client.ts                  (Real模式对接新接口)
```

### 验收标准
- [ ] `POST /api/v1/tasks/{id}/script/generate` 返回合法 `dialogue_script` JSON
- [ ] 生成的脚本轮次、角色与配置一致
- [ ] `POST /api/v1/tasks/{id}/questions/generate` 返回N道单选（题干+4选项+答案）
- [ ] 文本评测返回 `0-5` 分 + 错误句/超纲词列表
- [ ] 题目评测返回 通过/不通过 + 证据
- [ ] BC解释返回 JSON（错误+原因+建议）
- [ ] 超时60s后自动重试1次，仍失败返回友好错误

### 风险
- **中**：`qwen3:4b-instruct` JSON Schema遵从率未验证，Prompt可能需要迭代调优
- **缓解**：结构化输出约束（在Prompt中强调JSON格式）+ 解析层容错（提取```json```块、修复尾部逗号）

---

## 阶段4：接入Piper和Whisper

### 输入
- 阶段3的Ollama集成
- 本地安装的 Piper TTS + Whisper `base.en`

### 输出
音频生成（双角色TTS）、音频回转校验（ASR）、文音一致性评测接口可用。

### 修改/创建文件

```
backend/
├── requirements.txt               (追加 piper-tts, openai-whisper 或 faster-whisper)
├── services/
│   ├── tts_service.py             (Piper调用：文本→音频文件)
│   ├── asr_service.py             (Whisper调用：音频→转写文本)
│   └── audio_eval_service.py      (ASR文本 vs 脚本比对)
├── api/
│   └── audio_routes.py            (音频生成+评测)
frontend/src/
├── components/
│   └── AudioPlayer.tsx            (音频播放器+波形显示)
```

### 验收标准
- [ ] `POST /api/v1/tasks/{id}/audio/generate` 生成双角色音频文件
- [ ] 两个音色可区分（男/女或高/低）
- [ ] 音频 `duration > 0` 且时长偏差在配置范围内
- [ ] ASR回转生成转写文本
- [ ] 文音一致性比对返回差异列表（漏读/错读/多余词）
- [ ] 音频失败时标记 `audio: failed`，不影响图片和题目状态

### 风险
- **中**：Piper音色自然度可能不够（英语合成效果待验证）；Whisper base.en对TTS合成语音的转写准确率待测
- **缓解**：提供多个Piper音色备选；若Whisper base.en准确率不足，改用small.en

---

## 阶段5：接入ComfyUI

### 输入
- 阶段4的音频集成
- 本地运行的 ComfyUI + SDXL Base 1.0

### 输出
情境图生成接口可用，5种风格可选。

### 修改/创建文件

```
backend/
├── services/
│   ├── comfyui_client.py          (ComfyUI API: /prompt → /history → 下载图片)
│   └── image_service.py           (P-IMAGE Prompt构建+工作流参数)
├── api/
│   └── image_routes.py            (图片生成+列表)
comfyui_workflows/
│   └── sdxl_simple.json           (基础文生图工作流)
frontend/src/
├── components/
│   └── ImageCard.tsx              (图片预览+放大+风格标签)
```

### 验收标准
- [ ] `POST /api/v1/tasks/{id}/image/generate` 生成情境图
- [ ] 5种风格（cartoon/children_book/flat/watercolor/realistic）可切换
- [ ] 图片保存到 `storage/images/`，返回可访问URL
- [ ] 超时120s后自动重试1次
- [ ] 图片失败时标记 `image: failed`，不影响音频和题目状态

### 风险
- **中**：SDXL对空间关系的控制力弱（"library across from bank"可能不如预期）；ComfyUI工作流首次配置复杂
- **缓解**：MVP不自动检查空间关系（P1功能）；提供基础文生图工作流JSON模板；5种风格选择让教师挑最佳效果

---

## 阶段6：完成规则评测与Bad Case闭环

### 输入
- 阶段3-5的所有生成接口
- `docs/mvp-scope.md` 第八章（10项规则评测 + 门禁条件）

### 输出
完整评测流程（规则+模型+门禁），Bad Case生成→修复→回归闭环。

### 修改/创建文件

```
backend/
├── services/
│   ├── rule_evaluator.py          (10项规则评测引擎)
│   ├── gate_service.py            (门禁判定: 总分+S3S4检查+一票否决)
│   ├── badcase_service.py         (BC聚合+解释生成+修复追踪)
│   └── export_service.py          (素材打包ZIP)
├── api/
│   ├── eval_routes.py             (完善: 触发全量评测)
│   ├── badcase_routes.py          (BC列表+详情+反馈)
│   └── export_routes.py           (导出检查+打包)
frontend/src/
├── pages/
│   ├── EvaluationReport.tsx       (完善: 五维分项+问题筛选+门禁面板)
│   ├── BadCaseDetail.tsx          (完善: 跳转编辑+局部重生成+修复历史)
│   └── ExportReview.tsx           (完善: 强制门禁检查+导出下载)
```

### 验收标准
- [ ] 10项规则评测全部可执行并返回结构化结果
- [ ] 总分公式正确计算（权重从config.json读取）
- [ ] S3/S4问题阻止导出（红色提示+按钮灰色）
- [ ] 一票否决逻辑生效（答案错/音频不可播放/版本错配→直接不过）
- [ ] Bad Case列表展示+按模态/严重度筛选
- [ ] BC详情 → 可直接跳转到脚本编辑器/图片卡/音频卡/题目卡
- [ ] 局部重生成：只更新目标模块，不清空其他模块
- [ ] 版本级联：脚本修改→版本递增→下游素材自动outdated
- [ ] 导出包包含：脚本.txt + 图片.png + 音频.mp3 + 题目.json + 报告.json + manifest.json
- [ ] 教师反馈（agree/false_positive/fixed）可保存

### 风险
- **中**：评测器准确率未经验证（Precision/Recall未知）；版本级联逻辑需充分测试
- **缓解**：阶段7用注入错误样本测试评测器；版本级联写单元测试

---

## 阶段7：完成真实流程测试和README

### 输入
- 阶段1-6全部功能
- 80条评测样本（按PRD Table 37：30正常+15复杂+10边界+5信息不全+15注入错误+5异常）

### 输出
端到端测试报告 + README + 录制Demo流程。

### 修改/创建文件

```
├── README.md                      (项目说明+启动步骤+配置说明+技术栈)
├── eval_sets/
│   ├── dev_set_v1.0.json          (开发集: 可反复使用)
│   ├── test_set_v1.0.json         (测试集: 冻结)
│   └── regression_set_v1.0.json   (回归集: 从BC回流)
├── docs/
│   └── test-report-v0.1.md        (阶段7测试报告)
```

### 验收标准
- [ ] Mock模式：7页端到端流程完整可走通（配置→脚本→多模态→评测→BC修复→导出）
- [ ] Real模式：完成至少5个真实任务（不同词汇/句型组合）
- [ ] 评测器在15条注入错误样本上的检测结果可量化
- [ ] 所有S3/S4注入错误被检出（Recall目标100%）
- [ ] README包含：
  - 项目介绍（一句话+核心功能列表）
  - 环境要求（Python 3.12, Node 18+, Ollama, ComfyUI, Piper, Whisper）
  - 安装步骤（前后端依赖安装+模型下载）
  - 配置说明（config.json字段解释）
  - Mock模式使用指南
  - Real模式前置条件
  - API文档链接
  - 项目结构说明

### 风险
- **低**：收尾阶段，主要是文档和测试

---

## 关键依赖链

```
阶段1 ──→ 阶段2 ──→ 阶段3 ──→ 阶段4 ──→ 阶段5 ──→ 阶段6 ──→ 阶段7
  │                            │          │          │
  └─ 脚手架                   └─ LLM     └─ TTS/ASR └─ 图像
```

- 阶段2 不依赖任何后端，可独立开发
- 阶段3/4/5 之间不互相依赖（Ollama/Piper+Whisper/ComfyUI可并行接入）
- 阶段6 依赖阶段3+4（评测需要生成结果）
- 阶段5（ComfyUI）与阶段6可并行——评测不依赖图像评测（MVP跳过多模态评测）

### 可并行化建议

```
阶段2 (前端Mock) ──────────────────────────────┐
阶段3 (Ollama)   ──┐                           │
阶段4 (Piper/Whisper) ├── 可并行 ──→ 阶段6 ──→ 阶段7
阶段5 (ComfyUI)  ──┘                           │
```

如果多人协作：前端开发专注阶段2，后端开发分别攻坚阶段3/4/5，然后在阶段6汇合。
