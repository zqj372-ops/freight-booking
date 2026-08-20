# v0.5 拍板执行指令 (Execution Decisions)

> 2026-08-20 Autumn 给出的 12 项最终拍板决议, 落地清单.
> 这是 v0.5 阶段 0 → 阶段 4 全过程的执行准绳, 后续争议以本文为准.

## 0. 背景

v0.4 把 SO 当主对象, `confirm_so() → 创建 Booking` 的路径把业务流程反了. 
2026-08-20 业务复盘, 决定整体重构, 重新以 Shipment 作为聚合根. 
本文锁定 12 项关键决策, 防止后续 implementation 阶段反复争议.

## 1. 12 项决策

### D1. 冻结 v0.4 基线
- 冻结 `feature/v0.4-closed-loop` 分支
- 打 tag `legacy-v0.4-pre-core-reset`
- 不在 v0.4 上重写, 不在 v0.4 上 patch

### D2. 新建 `refactor/v0.5-core-workflow` 分支
- 基于 v0.4 快照 (commit 71c9cff) 起步
- 不从 v0.1 重新搭, 保留 v0.4 已有的 React / IMAP / Docker / OCR / 邮件模板基础设施
- v0.5.0 是产品版本号, "Core Workflow Reset" 是内部工作包名

### D3. 停止 `SO → 新建 Booking` 流程
- v0.4 `confirm_so()` 创建 Booking 的路径在 v0.5 物理删除
- SO 不再是业务流程起点, 只是船公司回复的附件
- SO 改为匹配已有 Shipment, 不再生成新业务单

### D4. 新增 `/api/v2`, 保留 `/api/v1` 作只读
- `/api/v1/*` 切换为只读兼容层 (写操作 410 Gone)
- `/api/v2/*` 是新主用
- 不要为新流程开发 Streamlit 页面 (用 React)
- 不要在 v0.4 API 路径下塞新逻辑

### D5. Shipment 是聚合根
- 一个业务单 = 一个 Shipment
- 流程: 建 Shipment → 发 BookingRequest → 收 BookingConfirmation → 接受 → 录入 Container/Milestone/Task
- 子对象全部挂在 Shipment 下 (见 ADR-0001 §1 总览图)

### D6. 补齐缺失对象
v0.5 核心对象 (v0.4 没有的):
- `Document` (文件, 替代 v0.4 SO 的文件部分)
- `EmailThread` (邮件线程)
- `EmailMessage` (单封邮件, 区分 inbound/outbound)
- `DocumentExtraction` (OCR 抽取结果, 与 Document 解耦)
- `OperationalException` (异常, 与 Milestone/Task 平行)
- `AuditLog` (操作审计)
- `LegacyEntityMap` (旧→新实体映射)

### D7. React 保留, 重写业务页面
- React 工程基础 (Vite / TS / Tailwind / shadcn/ui / TanStack Query / API Client / Docker) 全部保留
- 业务页面分批重写:
  - 第一批: `Shipments` / `ShipmentDetail` / `Partners`
  - 第二批: `BookingConfirmationInbox` / `EmailThreads` / `OperationsDashboard`
  - 第三批: `Tasks` / `Containers` / `Bills`
- React UI 开发**等 API 契约稳定后**跟进, 不让旧页面绑架新数据模型

### D8. Streamlit 不再用于新流程
- `frontend/app.py` Streamlit v0.1 demo 保留作历史参考
- 不再为 v0.5 业务流开发 Streamlit 页面
- README 注明: Streamlit 是早期 MVP UI, 当前主 UI 是 React

### D9. 产品第一阶段只服务内部操作团队
- 主要用户: 订舱操作员, 操作主管
- 后续用户: 销售, 财务, 管理层
- 当前**不**做: 客户订舱商城, 多家货代共用 SaaS, 客户门户, 租户计费, 套餐管理
- 不称"做 SaaS", 称"内部操作系统"
- 角色: 你承担"内部产品负责人 + 领域负责人"

### D10. 加 Organization + organization_id, 不实现多租户 SaaS
- 新增 `organizations` 表, seed `slug='default-company'`
- 以下核心表加 `organization_id`:
  users, shipments, partners, email_accounts, email_templates, documents, email_threads, tasks, operational_exceptions
- 编号唯一约束: `UNIQUE(organization_id, job_no)`, 不是 `UNIQUE(job_no)`
- 当前不实现: 租户切换, SaaS 注册, 多租户登录, 租户账单, Row-Level Security
- 称为: "tenant-ready single-tenant, 架构可多租户, 产品仍单租户"

### D11. 业务编号体系
- 9 字段拆开, 各有含义:
  - `job_no` (FB-20260820-0001, 系统内部业务编号)
  - `legacy_job_no` (旧 v0.4 Booking.booking_no, 迁移保留)
  - `customer_ref` (客户委托编号)
  - `booking_request_no` (BR-001/BR-002, 系统内部订舱申请版本号)
  - `carrier_booking_no` (船公司/代理返回的 Booking Number)
  - `so_no` (SO 文件编号)
  - `bl_no` (提单号)
  - `container_no` (柜号)
  - `seal_no` (封条号)
- 编号规则配置到 Organization (`job_no_prefix` / `job_no_date_fmt` / `job_no_seq_digits` / `job_no_reset_policy`)
- v0.5 用默认, 不做可视化规则编辑器

### D12. 不引入报价/价格模块
- v0.5 不做: 询价管理, 供应商报价, 船期价格, 客户报价, 利润测算, 调价, 价格审批
- BookingRequest 最多预留 `rate_reference` / `rate_valid_until` / `commercial_snapshot` 字段
- 报价管理是另一个 bounded context (Pricing / Procurement), v0.6+ 评估

## 2. 关键设计原则

### P1. 业务事实来源
- OCR 结果, 邮件内容, 人工操作都**只能提供证据**
- 真正被接受并进入 Shipment 的数据, 才是当前有效的业务事实
- v0.4 的 `parse_so_text() → 直接 setattr(so, ...)` 隐式写入是 v0.4 的 bug, v0.5 不再存在

### P2. 业务编号概念清晰
- `job_no` ≠ 船公司 Booking Number
- `booking_request_no` (BR-001) ≠ `carrier_booking_no`
- 旧 v0.4 `Booking.booking_no` 整体搬入 `Shipment.legacy_job_no`, 不拆解

### P3. 多版本管理
- BookingRequest 多版本 (request_version 1→2→3, supersedes_id 链)
- BookingConfirmation 多版本 (version 1→2→3, supersedes_id 链, is_current 标记)
- 改 ETD/改港/换船公司都创建新版本, 不修改旧的

### P4. 状态分层
- Shipment.stage (粗粒度, 9 个值, 由 Milestone 推导, 不直接改)
- Milestone (业务节点, 不可变, 修正靠 corrected_at)
- Task (待办, 可变, auto_close_on 字段)
- OperationalException (异常, 0..N, 状态 open/resolved/auto_closed)

### P5. 迁移不留假数据
- 不能为了让数据看起来完整而编造业务事实
- 例: v0.4 Booking.status=confirmed 但没 SO → Shipment.stage=draft, migration_status=needs_review
- 例: v0.4 `booking_no=MAE-20260820-A8F3` 不直接当 carrier_booking_no, 只当 legacy_job_no

### P6. OCR 字段必须可追溯
- DocumentExtraction.fields 含 `value` + `confidence` + `source_bbox`
- 关键字段低置信度时 `low_confidence_warning=true`
- diff 字段必填 (申请值 vs 确认值), 人工 review 后才能 accept

### P7. 审计 + 追溯
- AuditLog 记录所有写操作 (Shipment / BookingRequest / BookingConfirmation / Document / Task / Exception / Milestone / EmailMessage)
- actor 取自 `X-User-Id` request header (v0.5 JWT 暂未实现)
- sensitive 操作 (accept/reject/cancel/delete) 必填 reason
- LegacyEntityMap 提供新→旧索引, 业务详情页有 "v0.4 来源" tab

## 3. 阶段路线 (5 阶段)

### 阶段 0: 领域冻结 (本次)
- 5 份 ADR + core-workflow.md + migration-map.md + execution-decisions.md ← **当前**
- 产出: docs/adr/000{1..5}-*.md (ACCEPTED), docs/domain/{core-workflow,migration-map,execution-decisions}.md
- 状态: ✅ 全部落地, commit + push

### 阶段 1: 新模型 + /api/v2
- 12 个 SQLAlchemy model (Organization / Partner / Shipment / BookingRequest / BookingConfirmation / Container / Document / DocumentExtraction / EmailThread / EmailMessage / Milestone / Task / OperationalException / AuditLog / LegacyEntityMap)
- 15+ Pydantic schema
- /api/v2 路由 (shipments / booking-requests / booking-confirmations / documents / milestones / tasks / exceptions / audit-logs / email-threads / email-messages / partners / legacy-maps / dashboard)
- alembic migration 重建 schema
- 单元测试 + 端到端测试 (mock OCR + 模拟邮件)
- 不删 /api/v1

### 阶段 2: 数据迁移
- 备份 v0.4 db
- 迁移脚本 (Booking → Shipment, SO → Document + BookingConfirmation, Agent → Partner, EmailLog → EmailMessage, TrackingEvent → Milestone, Bill FK 改名)
- 迁移报告
- 抽样验证
- /api/v1 切只读
- 旧数据 demo 验收

### 阶段 3: React 业务页面
- 第一批: Shipments 列表 + ShipmentDetail (概览/时间线/SO/邮件/柜/费用) + Partners
- 第二批: BookingConfirmationInbox + EmailThreads + OperationsDashboard
- 第三批: Tasks + Containers + Bills
- 不复用 v0.4 React 业务页代码, 基础组件 (shadcn/ui / TanStack Query / Layout) 保留

### 阶段 4: 端到端验收
按 core-workflow.md §6 的 19 步跑一遍, 真实或脱敏业务数据.

## 4. 不在 v0.5 范围 (明确剔除)

- 完整费用管理 / 报价 / 利润 (→ v0.6)
- 客户门户 / 小程序 (→ v0.7)
- 拖柜 / 报关 / 仓库子模块 (→ v0.6+)
- SaaS 多租户 (永远不做本系统)
- 一票多柜 (→ v0.6)
- LLM 结构化抽取 OCR (v0.5 评估, v0.6 引入)
- 复杂规则引擎 (v0.5 用 if-else, v0.6 评估 Drools / JSONLogic)
- 全文检索 AuditLog (v0.5 简单索引, v0.6 评估 SQLite FTS5 / Postgres)
- 真实 JWT 鉴权 (v0.5 用 X-User-Id header, v0.6 评估)
- 多邮箱路由 (v0.5 单邮箱够用, v0.6 引入)
- 业务规则可视化编辑器 (v0.5 不暴露, v0.6 评估)

## 5. 验证清单 (任何实现偏离本文时回查)

- [ ] Shipment 是唯一主对象, 没有第二条业务主链
- [ ] 业务编号 9 字段都拆开, 没有混用
- [ ] SO 不再创建新业务单, 只匹配
- [ ] 一个 Shipment 可以有多个 BookingConfirmation 版本
- [ ] OCR 字段不直接污染 Shipment, 必经人工 accept
- [ ] 状态 4 层 (stage / Milestone / Task / Exception) 互不替代
- [ ] organization_id 在所有核心表上, 但 UI 不暴露切换
- [ ] audit_log 自动留痕, sensitive 操作 reason 必填
- [ ] legacy_entity_map 每条迁移都写
- [ ] 迁移不留假数据 (status=needs_review 不阻塞但显眼)
- [ ] React 基础组件复用, 业务页分批重写
- [ ] 不为 v0.5 业务流开发 Streamlit 页面
- [ ] /api/v1 写操作 410, 读操作正常
- [ ] 不引入报价/价格模块
