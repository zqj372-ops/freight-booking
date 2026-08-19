# 二掌柜订舱系统 (Freight Booking System)

货代订舱自动化系统 — SO 识别 / 邮件订舱 / 账单 OCR / 订舱代理管理。

**当前状态**：MVP 阶段（SO + OCR + 邮件订舱 + 代理管理）已可跑通；账单 OCR、运单跟踪、自动拉取邮件 等在下一轮叠加。

## ✨ MVP 功能

- 📥 **SO 收件箱** — 上传 PDF / 图片，自动 PaddleOCR 识别，自动抽取船公司 / 航线 / 柜型 / ETD 等字段
- ✏️ **字段修正** — 识别不准确的字段人工修订
- 🎯 **一键生成 Booking** — SO 确认后自动转订舱单
- 📧 **邮件订舱** — SMTP 发送 / 模板 (Jinja2) / 重试 / 抄送 / 附件 / 发送历史
- 👥 **订舱代理管理** — 代理档案、收件邮箱、CC、擅长航线
- 📜 **邮件历史** — 全部发送记录 / 失败重试 / 错误日志
- 🐳 **Docker 一键部署** — API + UI 双容器

## 🛠 技术栈

- **后端**: Python 3.12 + FastAPI + SQLAlchemy 2.0 (async) + Pydantic v2 + Alembic
- **OCR**: PaddleOCR 3.x (中文 SOTA, Apache 2.0)
- **邮件**: aiosmtplib + Jinja2 模板
- **DB**: SQLite (开发) / PostgreSQL (生产, Docker Compose 已注释)
- **前端**: Streamlit 1.x (单文件, 快速验证 UI)
- **部署**: Docker / Docker Compose

## 🚀 快速开始

### 方式 A：本地开发

```bash
# 1. 克隆
git clone https://github.com/zqj372-ops/freight-booking.git
cd freight-booking

# 2. 复制环境变量
cp .env.example .env
# 编辑 .env, 至少填 SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD

# 3. 装依赖 (推荐用 venv)
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
# 可选: pip install -e ".[ocr,ui,dev]"

# 4. 跑后端 (端口 8000)
uvicorn app.main:app --reload

# 5. 另开终端, 跑前端 (端口 8501)
streamlit run frontend/app.py
```

访问:
- API 文档: <http://localhost:8000/docs>
- 前端: <http://localhost:8501>
- 健康检查: <http://localhost:8000/health>

### 方式 B：Docker

```bash
# 1. 复制并编辑环境变量
cp .env.example .env
vi .env

# 2. 启动
docker compose up -d --build

# 查看日志
docker compose logs -f api
```

- API: <http://localhost:8000/docs>
- UI: <http://localhost:8501>

## 📂 项目结构

```
freight-booking/
├── app/
│   ├── api/v1/         # REST 路由 (SO / Booking / Agent / Email)
│   ├── core/           # 日志、安全
│   ├── models/         # SQLAlchemy ORM
│   ├── schemas/        # Pydantic
│   ├── services/       # OCR / 邮件 / 解析
│   ├── utils/          # bootstrap / 工具
│   ├── data/           # 船公司模板 JSON
│   ├── config.py
│   ├── database.py
│   └── main.py
├── frontend/app.py     # Streamlit UI
├── migrations/         # Alembic
├── uploads/            # SO / 账单 / 附件
├── data/               # SQLite
├── logs/
├── tests/
├── docs/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

## 🔌 主要 API 端点

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/v1/so/upload` | 上传 SO, 后台跑 OCR |
| GET | `/api/v1/so/` | SO 列表（分页 + 过滤）|
| GET | `/api/v1/so/{id}` | SO 详情（含 OCR 原文）|
| PATCH | `/api/v1/so/{id}` | 修正字段 |
| POST | `/api/v1/so/{id}/reocr` | 重新 OCR |
| POST | `/api/v1/so/{id}/confirm` | 确认 → 生成 Booking |
| GET | `/api/v1/bookings/` | 订舱列表 |
| POST | `/api/v1/bookings/` | 新建订舱 |
| POST | `/api/v1/bookings/{id}/send` | 发订舱邮件 |
| GET | `/api/v1/agents/` | 代理列表 |
| POST | `/api/v1/agents/` | 新增代理 |
| GET | `/api/v1/emails/templates` | 邮件模板 |
| POST | `/api/v1/emails/templates/{id}/preview` | 预览渲染 |
| POST | `/api/v1/emails/send` | 手动发邮件 |
| GET | `/api/v1/emails/logs` | 发送历史 |

完整列表见 <http://localhost:8000/docs>。

## ⚙️ 配置项

` .env` 关键配置：

```bash
DATABASE_URL=sqlite+aiosqlite:///./data/freight.db
SMTP_HOST=smtp.exmail.qq.com
SMTP_PORT=465
SMTP_USERNAME=ops@yourdomain.com
SMTP_PASSWORD=xxx
SMTP_USE_SSL=true
SMTP_FROM_EMAIL=ops@yourdomain.com
SMTP_FROM_NAME=二掌柜订舱

PADDLEOCR_LANG=ch
PADDLEOCR_USE_GPU=false
```

## 🧠 路线图

- [x] SO 收件箱 + PaddleOCR
- [x] 邮件订舱 (SMTP + 模板)
- [x] 订舱代理管理
- [ ] **账单 OCR** — PaddleOCR + LLM (Gemini/GPT) 提取结构化字段
- [ ] **运单跟踪看板** — 状态机 + 拖拽切换
- [ ] **自动拉取订舱邮件** — IMAP 定时拉, 解析后入库
- [ ] **应收应付对账** — 账单 vs Booking 自动匹配
- [ ] **多用户 / 权限** — 主管/操作员/财务
- [ ] **React + shadcn/ui 前端** — 替换 Streamlit
- [ ] **微信小程序** — 移动端查看 / 审批

## 🧪 测试

```bash
pytest tests/ -v
```

## 📝 License

MIT © zqj372-ops
