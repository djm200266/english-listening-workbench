# 实施进度记录

> 项目：七年级英语听说课多模态生成与质量评测工作台 V0.1

---

## 阶段1 ✅ 完成 — 创建前后端基础工程

**日期**: 2026-07-13

### 输出

| 类别 | 内容 | 状态 |
|------|------|------|
| 根目录 | `README.md`, `config.json` | ✅ |
| 前端脚手架 | Vite + React 18 + TypeScript + Tailwind CSS | ✅ |
| 后端脚手架 | FastAPI + Pydantic + Uvicorn | ✅ |
| 数据模型 | `backend/models/` — Task, TaskConfig, DialogueScript, ImageAsset, AudioAsset, QuestionSet, EvaluationItem, EvalReport 等 Pydantic 模型 | ✅ |
| 数据存储 | `backend/repositories/` — Repository 抽象层 + JSON 实现（原子写入、独立目录） | ✅ |
| 业务层 | `backend/services/` — TaskService（CRUD，通过 Repository 解耦） | ✅ |
| API路由 | `backend/api/` — 健康检查 + 5个任务 CRUD 端点 | ✅ |
| 类型定义 | `frontend/src/types/` — 完整 TypeScript 类型（枚举 + 数据模型） | ✅ |
| 配置加载 | `backend/config.py` + `config.json` — 统一配置，前后端可读 | ✅ |

### 验收结果

- [x] `npm run build` 通过（46 modules, 906ms）
- [x] FastAPI 模块导入通过（6 routes）
- [x] `GET /api/health` → 200 `{"status":"ok","mode":"mock"}`
- [x] `GET /api/v1/tasks` → 200 `[]`
- [x] `POST /api/v1/tasks` → 201 (task_id generated)
- [x] 前端 7 页面路由可访问

### 关键技术决策落地

- Repository/Service 层隔离 JSON 读写，页面和 API 不直接操作文件
- Mock/Real 模式通过 `config.json` → `mode` 字段统一控制
- 原子写入（temp file + os.replace）防止写入中断损坏

---

## 阶段2 ✅ 完成 — 七页 Mock 模式

**日期**: 2026-07-13

### 输出

| 页面 | 文件 | Mock 数据覆盖 | 状态 |
|------|------|-------------|------|
| 任务中心 | `TaskCenter.tsx` | 5个示例任务（draft/generating/needs_fix/approved/exported），状态筛选，搜索，删除确认 | ✅ |
| 新建任务 | `TaskNew.tsx` | 完整表单（基础信息+语言约束+音频设置+题目设置+补充说明），实时校验，冲突检测，保存草稿 | ✅ |
| 脚本审核 | `ScriptReview.tsx` | 8轮双角色对话渲染，编辑弹窗，文本评分面板，确认/锁定版本，下游按钮条件启用 | ✅ |
| 多模态结果 | `MultiModalAssets.tsx` | 三卡片独立状态（图片/音频/题目），过期标记，失败不隐藏成功，局部重生成按钮 | ✅ |
| 评测报告 | `EvaluationReport.tsx` | 总分+五维分项进度条，门禁条件清单，S3/S4筛选，跳转BC详情 | ✅ |
| Bad Case详情 | `BadCaseDetail.tsx` | 错误位置+类型+证据+根因+修复建议，跳转编辑器，教师反馈标记（认可/误报/已修复） | ✅ |
| 审核导出 | `ExportReview.tsx` | 审核清单，导出阻止原因列表，最终预览，ZIP格式说明，教师确认checkbox，免责声明 | ✅ |
| 共享组件 | `Layout.tsx`, `StatusBadge.tsx` | 顶栏导航，Mock/Real开关，服务状态指示灯，10种状态标签，S0-S4严重度标签 | ✅ |

### 验收结果

- [x] Mock 模式端到端流程：任务中心 → 新建 → 脚本审核 → 多模态 → 评测 → BC详情 → 导出（7页完整可走通）
- [x] 状态筛选正确过滤（全部/草稿/生成中/待评测/存在问题/待审核/已导出/失败）
- [x] S3/S4任务红色左边框标识
- [x] 新建任务表单校验生效（缺失高亮、越界提示、约束冲突警告）
- [x] 脚本未确认时下游生成按钮灰色禁用
- [x] 过期素材显示警告标记
- [x] 评测报告门禁条件正确判定（总分/严重错误/素材完整/版本一致/安全合规）
- [x] Bad Case详情页面可跳转回编辑器
- [x] 导出被S3/S4/未审核/过期素材阻止，阻止原因完整展示
- [x] Mock/Real 开关可切换，Real 模式调用空 API 有 connect 状态显示

---

## 已创建文件清单

```
english-listening-workbench/
├── README.md
├── config.json
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx                (Router + mode context)
│       ├── index.css              (Tailwind + status/severity classes)
│       ├── types/index.ts         (完整 TS 类型)
│       ├── services/api.ts        (Mock/Real 分支 API client)
│       ├── mock/data.ts           (5个seed任务 + 全部Mock数据)
│       ├── components/
│       │   ├── Layout.tsx         (顶栏+导航+模式开关+服务状态)
│       │   └── StatusBadge.tsx    (状态/严重度/素材状态+确认弹窗)
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
│   ├── main.py                    (FastAPI entry + lifespan)
│   ├── config.py                  (config.json loader)
│   ├── models/__init__.py         (Pydantic models + enums)
│   ├── repositories/__init__.py   (Repository ABC + JSON impl)
│   ├── services/__init__.py       (TaskService)
│   └── api/
│       ├── __init__.py            (任务CRUD路由)
│       └── health.py             (健康检查)
├── data/                          (运行时JSON存储)
├── storage/{images,audio,exports}/
├── prompts/                       (Prompt模板目录)
└── eval_sets/                     (评测集目录)
```

---

## 下一步：阶段3 — 接入 Ollama

**预估**: 3天

### 前置条件
- [ ] 本地安装 Ollama
- [ ] `ollama pull qwen3:4b-instruct`
- [ ] 验证 `POST http://127.0.0.1:11434/api/generate` 可用

### 待开发
1. `backend/services/ollama_client.py` — Ollama API 封装
2. `backend/services/script_service.py` — P-SCRIPT 调用 + JSON 解析
3. `backend/services/question_service.py` — P-QUESTION 调用
4. `backend/services/eval_service.py` — P-SCRIPT-EVAL + P-QUESTION-EVAL + P-BC-EXPLAIN
5. `backend/api/script_routes.py` — 脚本生成/编辑/确认端点
6. `backend/api/question_routes.py` — 题目生成端点
7. `backend/api/eval_routes.py` — 评测端点
8. `prompts/P-SCRIPT.md + .json` 等7个 Prompt 模板
9. `backend/config.py` — Real模式检测Ollama可用性

---

## 遇到的问题

1. **编码问题**：Windows 终端对中文路径支持不稳定，通过 UTF-8 文件读写绕过
2. **后端模块导入**：`api/__init__.py` 中 `router` 和 `set_task_service` 需分别导入，不能通过 `router.set_task_service` 调用
