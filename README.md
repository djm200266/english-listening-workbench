# 七年级英语听说课多模态生成与质量评测工作台

> MVP V0.1 | 首版主题：Asking for and Giving Directions（问路与指路）

为七年级英语教师提供一套工作台，完成听说课素材（对话脚本 + 情境图 + 听力音频 + 选择题 + 答案）的**生成 → 评测 → 修复 → 导出**全流程。

---

## 本地 Real 模式启动（推荐）

在项目根目录右键 → **使用 PowerShell 运行**：

```
start-real.ps1
```

脚本会自动：
1. 检查 config.json mode 为 real
2. 检查 Ollama（11434）是否运行，未运行则启动
3. 检查 ComfyUI（8188），未运行则提示手动启动
4. 启动 FastAPI 后端（8000）
5. 启动 Vite 前端（5173）
6. 自动打开浏览器到 http://127.0.0.1:5173

停止服务：

```
stop-real.ps1
```

（只停止本项目的前后端，不会停 Ollama/ComfyUI）

---

## 手动启动

### 1. 安装依赖

```bash
cd frontend && npm install
cd backend && pip install -r requirements.txt
```

### 2. 启动外部服务

```bash
ollama serve                    # 或 Ollama 桌面应用
ollama pull qwen3:4b-instruct  # 首次需下载模型
```

ComfyUI 请手动运行其 `run_nvidia_gpu.bat`。

### 3. 启动后端

```bash
cd backend
D:\english_eval\whisper_env\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

### 4. 启动前端

```bash
cd frontend
npm run dev
```

打开 http://127.0.0.1:5173

---

## 常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| 前端打开但显示"后端未启动" | 5173 正常，8000 未启动 | 运行 `start-real.ps1` 或手动启动后端 |
| `{"detail":"Not Found"}` | 访问了 FastAPI 根路径 | 访问 `/api/health` 或 `/docs` |
| 新建任务按钮灰色 | 后端连接失败 | 等待自动重连或点击"重试连接" |
| 服务状态显示灰色"未知" | 后端离线，无法检测 | 后端启动后自动更新 |
| Ollama 生成失败 | 模型未下载 | `ollama pull qwen3:4b-instruct` |

---

## 核心功能

| 功能 | 说明 |
|------|------|
| 任务配置 | 填写主题、词汇、句型、轮次、时长、题数 |
| 脚本生成 | 双角色英语对话（Ollama + qwen3:4b-instruct） |
| 脚本审核 | 编辑 + 文本门禁 + 版本锁定 |
| 多模态生成 | 情境图（ComfyUI）+ 音频（Piper TTS）+ 题目（LLM） |
| 自动评测 | 规则评测 + 模型评测 + 跨模态检查 |
| Bad Case修复 | 错误定位 + 证据展示 + 局部重生成 |
| 审核导出 | 门禁检查 + 教师确认 + 素材打包 |

---

## 环境要求

| 依赖 | 用途 |
|------|------|
| Node.js 18+ | 前端 |
| Python 3.12+ | 后端 |
| Ollama + qwen3:4b-instruct | LLM |
| ComfyUI + SDXL Base 1.0 | 图像生成 |
| Piper TTS | 语音合成 |
| Whisper base.en | 语音转写 |
| ffmpeg | 音频合并 |

---

## 项目结构

```
english-listening-workbench/
├── start-real.ps1               # 一键启动 Real 模式
├── stop-real.ps1                # 安全停止
├── config.json                  # 全局配置
├── README.md
├── docs/                        # 产品文档
├── frontend/                    # React + Vite + TypeScript
│   └── src/
│       ├── config/api.ts        # 统一 API 地址
│       ├── types/               # TypeScript 类型
│       ├── services/api.ts      # API 客户端
│       ├── components/          # 共享组件
│       └── pages/               # 7 个页面
├── backend/                     # FastAPI
│   ├── main.py
│   ├── api/                     # 路由
│   ├── services/                # 业务逻辑
│   └── models/                  # Pydantic 模型
├── data/                        # 任务存储
├── prompts/                     # Prompt 模板
└── eval_sets/                   # 评测集
```

---

## 页面路由

| 路由 | 页面 |
|------|------|
| `/` | 任务中心 |
| `/task/new` | 新建任务 |
| `/task/:id/script` | 脚本审核 |
| `/task/:id/assets` | 多模态结果 |
| `/task/:id/report` | 评测报告 |
| `/task/:id/badcase/:bcid` | Bad Case 详情 |
| `/task/:id/export` | 审核导出 |

---

## API 文档

后端启动后访问 http://127.0.0.1:8000/docs 查看 Swagger。
