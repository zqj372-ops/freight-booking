# 二掌柜订舱系统 (Freight Booking System)

货代订舱自动化系统 — SO 识别 / 邮件订舱 / 账单 OCR / 运单跟踪 / 订舱代理管理。

**当前状态**：v0.3 — SO + OCR + 邮件订舱 + 账单 OCR + 运单跟踪 Kanban + IMAP 自动拉取 + React 前端 全部可跑通 + Docker 一键起。

## ✨ 功能矩阵

| 模块 | v0.1 | v0.2 | v0.3 | 状态 |
|---|---|---|---|---|
| 📥 **SO 收件箱** (PaddleOCR) | ✅ | ✅ | ✅ | 已稳定 |
| ✏️ SO 字段修正 | ✅ | ✅ | ✅ | 已稳定 |
| 🎯 SO → Booking 一键生成 | ✅ | ✅ | ✅ | 已稳定 |
| 📧 **邮件订舱** (SMTP + Jinja2) | ✅ | ✅ | ✅ | 已稳定 |
| 👥 订舱代理管理 | ✅ | ✅ | ✅ | 已稳定 |
| 💰 **账单 OCR** (PaddleOCR + 规则) | - | ✅ | ✅ | 已稳定 |
| 💰 应收/应付对账 | - | ✅ | ✅ | 已稳定 |
| 🗺️ **运单跟踪 Kanban** | - | ✅ | ✅ | 已稳定 |
| 🗺️ 跟踪状态机 (9 节点) | - | ✅ | ✅ | 已稳定 |
| 🔁 自动状态节点 (创建即 BOOKED) | - | ✅ | ✅ | 已稳定 |
| 📬 **IMAP 自动拉 SO** (mock 优先) | - | - | ✅ | 已稳定 |
| 🖥️ **React + shadcn/ui 前端** (9 页) | - | - | ✅ | 已稳定 |
| 🎯 **Kanban 拖拽** (dnd-kit) | - | - | ✅ | 已稳定 |
| 📜 邮件发送历史 | ✅ | ✅ | ✅ | 已稳定 |
| 🐳 **Docker Compose 一键起** (api + web) | ✅ | ✅ | ✅ | 已稳定 |

## 🛠 技术栈

- **后端**: Python 3.12 + FastAPI + SQLAlchemy 2.0 (async) + Pydantic v2 + Alembic
- **OCR**: PaddleOCR 3.x (中文 SOTA, Apache 2.0)
- **邮件**: aiosmtplib + Jinja2 模板 + APScheduler 定时
- **IMAP**: imaplib (标准库) + .eml mock 模式
- **DB**: SQLite (开发) / PostgreSQL (生产, Docker Compose 已注释)
- **前端**: React 18 + TypeScript 5 + Vite 5 + shadcn/ui + Tailwind + @tanstack + @dnd-kit
- **部署**: Docker Compose (api + web 双容器, nginx 反代)

## 🚀 快速开始

### 方式 A：本地开发 (前后端分开跑)

```bash
# 1. 克隆
git clone https://github.com/zqj372-ops/freight-booking.git
cd freight-booking

# 2. 复制环境变量
cp .env.example .env
# 编辑 .env, 至少填 SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD

# 3. 后端
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[ocr,dev]"
uvicorn app.main:app --reload     # API: http://localhost:8000

# 4. 前端 (另开终端)
cd web
npm install
npm run dev                       # Web: http://localhost:5173
```

访问:
- API 文档: <http://localhost:8000/docs>
- 前端: <http://localhost:5173>
- 健康检查: <http://localhost:8000/health>

### 方式 B：Docker Compose 一键起 (推荐生产/演示)

```bash
# 1. 复制并编辑环境变量
cp .env.example .env
vi .env  # 至少 SMTP_* 必填

# 2. 启动 (构建 api + web 镜像 + 起容器)
docker compose up -d --build

# 查看日志
docker compose logs -f api
docker compose logs -f web

# 停
docker compose down

# 重建 (改代码后)
docker compose up -d --build
```

**端口**:
- Web (React UI): <http://localhost:8080> ← **对外唯一入口**
- API: 容器内 8000（不直接对外，由 nginx 反代 `/api` + `/health`）

**架构**:
```
浏览器 → :8080 (nginx) → /         → 静态 React 资源
                            /api/*   → 反代 → freight-api:8000
                            /health  → 反代 → freight-api:8000/health
```

容器内 `web` 用 service name `api` 访问后端 (Docker network 内部 DNS)，无需配置外部 URL。

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
