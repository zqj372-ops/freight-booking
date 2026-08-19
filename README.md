# 二掌柜订舱系统 (Freight Booking System)

货代订舱自动化系统 — SO 识别 / 邮件订舱 / 账单 OCR / 运单跟踪 / 订舱代理管理。

**当前状态**：v0.2 — SO + OCR + 邮件订舱 + 账单 OCR + 运单跟踪 Kanban + 代理管理 全部可跑通。

## ✨ 功能矩阵

| 模块 | v0.1 | v0.2 | 状态 |
|---|---|---|---|
| 📥 **SO 收件箱** (PaddleOCR) | ✅ | ✅ | 已稳定 |
| ✏️ SO 字段修正 | ✅ | ✅ | 已稳定 |
| 🎯 SO → Booking 一键生成 | ✅ | ✅ | 已稳定 |
| 📧 **邮件订舱** (SMTP + Jinja2) | ✅ | ✅ | 已稳定 |
| 👥 订舱代理管理 | ✅ | ✅ | 已稳定 |
| 💰 **账单 OCR** (PaddleOCR + 规则) | - | ✅ | 已稳定 |
| 💰 应收/应付对账 | - | ✅ | 已稳定 |
| 🗺️ **运单跟踪 Kanban** | - | ✅ | 已稳定 |
| 🗺️ 跟踪状态机 (9 节点) | - | ✅ | 已稳定 |
| 🔁 自动状态节点 (创建即 BOOKED) | - | ✅ | 已稳定 |
| 📜 邮件发送历史 | ✅ | ✅ | 已稳定 |
| 🐳 Docker Compose | ✅ | ✅ | 已稳定 |

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

### SO / 订舱
| Method | Path | 说明 |
|---|---|---|
| POST | `/api/v1/so/upload` | 上传 SO, 后台跑 OCR |
| GET | `/api/v1/so/` | SO 列表（分页 + 过滤）|
| GET | `/api/v1/so/{id}` | SO 详情（含 OCR 原文）|
| PATCH | `/api/v1/so/{id}` | 修正字段 |
| POST | `/api/v1/so/{id}/reocr` | 重新 OCR |
| POST | `/api/v1/so/{id}/confirm` | 确认 → 生成 Booking |
| GET | `/api/v1/bookings/` | 订舱列表 |
| POST | `/api/v1/bookings/` | 新建订舱 (自动建 BOOKED 跟踪节点) |
| POST | `/api/v1/bookings/{id}/send` | 发订舱邮件 |

### 代理 / 邮件
| Method | Path | 说明 |
|---|---|---|
| GET | `/api/v1/agents/` | 代理列表 |
| POST | `/api/v1/agents/` | 新增代理 |
| GET | `/api/v1/emails/templates` | 邮件模板 |
| POST | `/api/v1/emails/send` | 手动发邮件 |
| GET | `/api/v1/emails/logs` | 发送历史 |

### 账单 (v0.2 新增)
| Method | Path | 说明 |
|---|---|---|
| POST | `/api/v1/bills/upload` | 上传账单 (PDF/图片), 后台 OCR |
| POST | `/api/v1/bills/` | 手动创建账单 |
| GET | `/api/v1/bills/` | 账单列表 |
| GET | `/api/v1/bills/{id}` | 账单详情 (含 OCR 原文 + 行项) |
| PATCH | `/api/v1/bills/{id}` | 修正字段 |
| POST | `/api/v1/bills/{id}/reocr` | 重新 OCR |
| POST | `/api/v1/bills/{id}/confirm` | 财务确认入账 |

### 运单跟踪 (v0.2 新增)
| Method | Path | 说明 |
|---|---|---|
| GET | `/api/v1/tracking/kanban` | Kanban 看板数据 (9 列分组) |
| GET | `/api/v1/tracking/bookings/{id}/status` | 当前状态 |
| GET | `/api/v1/tracking/bookings/{id}/events` | 全部跟踪节点 |
| POST | `/api/v1/tracking/bookings/{id}/events` | 手动添加节点 (校验状态机) |

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

- [x] SO 收件箱 + PaddleOCR (v0.1)
- [x] 邮件订舱 (SMTP + 模板) (v0.1)
- [x] 订舱代理管理 (v0.1)
- [x] **账单 OCR** — PaddleOCR + 规则 (v0.2)
- [x] **运单跟踪 Kanban** — 9 状态节点状态机 (v0.2)
- [x] 自动 BOOKED 节点 (创建 booking 即记录) (v0.2)
- [ ] **账单 LLM 增强** — Gemini/GPT 提取结构化字段
- [ ] **IMAP 自动拉邮件** — 定时拉订舱邮件
- [ ] **应收应付对账** — 账单 vs Booking 自动匹配
- [ ] **船公司跟踪 API 接入** — 自动同步跟踪状态
- [ ] **多用户 / 权限** — 主管/操作员/财务
- [ ] **React + shadcn/ui 前端** — 替换 Streamlit
- [ ] **微信小程序** — 移动端查看 / 审批

## 🧪 测试

```bash
pytest tests/ -v
```

## 📝 License

MIT © zqj372-ops
