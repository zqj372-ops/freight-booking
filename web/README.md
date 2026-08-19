# Freight Booking Web (React + shadcn/ui)

二掌柜订舱系统前端 — 替换 v0.1/v0.2 的 Streamlit 单文件。

## 技术栈

- **React 18** + **TypeScript 5** + **Vite 5**
- **shadcn/ui** (基于 Radix UI) — UI 组件
- **Tailwind CSS 3** — 样式
- **@tanstack/react-query 5** — 服务端状态
- **@tanstack/react-table 8** — 表格
- **@dnd-kit/core** + **sortable** + **utilities** — Kanban 拖拽
- **react-router-dom 6** — 路由
- **axios** — HTTP
- **lucide-react** — 图标
- **zod** — 校验 (预留)

## 9 个页面

| 路径 | 页面 | 关键能力 |
|---|---|---|
| `/` | 工作台 Dashboard | 4 个 KPI 卡片 + 最近 SO/账单 + IMAP 历史 |
| `/so` | SO 收件箱 | 上传 / 列表 / 修正字段 / 重 OCR / 确认 |
| `/bookings` | 订舱管理 | 新建 / 列表 / 发邮件 |
| `/tracking` | 运单跟踪 **Kanban** | **9 列拖拽** (dnd-kit) + 时间线 + 添加节点 |
| `/bills` | 账单中心 | 上传 / 列表 / 修正字段 / 重新 OCR / 确认入账 |
| `/agents` | 订舱代理 | CRUD |
| `/templates` | 邮件模板 | 只读列表 + 主题/正文 |
| `/logs` | 发送历史 | 列表 + 状态/重试/错误 |
| `/settings` | 系统设置 | API 状态 + IMAP 手动拉 + 拉取历史 |

## 本地开发

```bash
cd web
npm install
npm run dev
# 访问 http://localhost:5173
# API 走 vite proxy → http://localhost:8000
```

生产构建:
```bash
npm run build
# 产物 web/dist, Docker 用 nginx 服务
```

## 目录结构

```
web/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
├── components.json      # shadcn/ui config
├── index.html
├── .env.example         # VITE_API_BASE
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── index.css
│   ├── lib/
│   │   ├── api.ts       # axios + API client
│   │   └── utils.ts     # cn + formatDate + formatMoney
│   ├── components/
│   │   ├── layout.tsx   # sidebar + outlet
│   │   └── ui/          # shadcn primitives
│   └── pages/
│       ├── Dashboard.tsx
│       ├── SOInbox.tsx
│       ├── Bookings.tsx
│       ├── Tracking.tsx     # Kanban 拖拽
│       ├── Bills.tsx
│       ├── Agents.tsx
│       ├── EmailTemplates.tsx
│       ├── EmailLogs.tsx
│       └── Settings.tsx
```

## 与后端的关系

- 开发时通过 vite proxy 把 `/api` 代理到 `http://localhost:8000`（可在 `vite.config.ts` 改）
- 生产环境通过 nginx 反代: `/api` → fastapi 服务
- 类型定义在 `lib/api.ts` 手动维护, 与后端 `app/schemas/*.py` 保持一致

## 待扩展

- React Hook Form 替换当前的 useState 表单
- React Query 优化缓存策略
- Toast 提示 (用 sonner 替换默认)
- 暗色模式 (CSS variables 已就位, 需在 Layout 加 toggle)
- 实时通知 (WebSocket 监听 SO OCR 完成 / 邮件到达)
