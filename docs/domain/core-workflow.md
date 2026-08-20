# Core Workflow 总览 (v0.5)

> 业务单 Shipment 贯穿全流程, 任何子对象 (订舱/确认/文件/邮件/节点) 都挂在 Shipment 下.
>
> **领域冻结 (阶段 0) 已完成**. 进入阶段 1 (新 model + /api/v2) 等待用户拍板.

## 1. 业务主对象

```
Shipment (聚合根, 业务单)
├── BookingRequest (N)            # 订舱申请
│   └── EmailMessage (1, outbound) # 申请邮件
├── BookingConfirmation (N)        # 船公司确认
│   ├── Document (1)               # 来源 PDF/图片
│   │   └── DocumentExtraction (1) # OCR 抽取结果
│   └── EmailMessage (1, inbound)  # 收到的 SO 邮件
├── Container (N, 预留 v0.6)
├── Milestone (N, 业务节点)        # SO接受/提柜/装船/开船
├── Task (N, 待办)                # 提交SI/录入柜号
├── OperationalException (N)       # 超时/字段不一致
├── Document (N, 其他文件)         # 提单/补料/发票
├── Bill (N)                       # 财务 (v0.5 暂时保留 v0.4 模型)
└── AuditLog (N, 自动)             # 任何写操作
```

## 2. 状态流转 (粗粒度)

```
                   建业务单
                      │
                      ▼
                  ┌─draft─┐
                  │      │ 发订舱
                  │      ▼
                  │ booking_in_progress ────收到 SO──> awaiting_confirmation
                  │      │                              │
                  │      │ 超时(异常)                  │ 人工接受
                  │      │                              ▼
                  │      │                        ┌─booked─┐
                  │      │                        │       │ 提柜
                  │      │                        │       ▼
                  │      │                        │ container_operation
                  │      │                        │       │ 装船
                  │      │                        │       ▼
                  │      │                        │ documentation
                  │      │                        │       │ 提交 SI/VGM
                  │      │                        │       ▼
                  │      │                        │ departed (开船)
                  │      │                        │       │
                  │      │                        │       ▼
                  │      │                        │ completed
                  │      │
                  │      │ (任何阶段)
                  │      └──────────────────────> cancelled (终态)
                  └──────────────────────────────────┘
```

实际 stage 由最新相关 Milestone 推导 (见 ADR-0004 §3.1), 不是硬写.

## 3. 一个 Shipment 多个 SO 版本

```
时间线:
  T0: Shipment 创建, stage=draft
  T1: BookingRequest BR-001 发给代理 A
  T2: 收到代理 A 的 SO-001, BookingConfirmation BC-001 (status=matched_pending)
  T3: 人工接受 BC-001, is_current=true, Shipment.ETD 写入 BC-001.ETD, stage=booked
  T4: 客户改 ETD, 创建 BR-002 (cargo_snapshot 锁新 ETD), 发邮件
  T5: 收到代理 A 的 SO-002, BC-002 (supersedes_id=BC-001, is_current=true)
  T6: 人工接受 BC-002, BC-001.is_current=false (自动), Shipment.ETD 覆盖
```

## 4. 邮件线程

```
EmailThread (subject="[FB-20260820-0001] Booking Request | CNSHA-USLAX | 1×40HQ")
├── EmailMessage 1 (outbound, sent)     # BR-001 申请
├── EmailMessage 2 (inbound, received)  # 代理 A 收到确认
├── EmailMessage 3 (inbound, received)  # 代理 A 发 SO-001
└── EmailMessage 4 (outbound, sent)     # 我们回执/追问
```

主题前缀 `[FB-20260820-0001]` 是机器可解析的, 用来自动匹配回复.

## 5. 异常联动

```
BookingRequest sent 超过 24h
  ↓
自动开 OperationalException (code=booking_response_overdue, severity=warning)
  ↓
工作台显示"待回复超时"
  ↓
操作员点击 → 打电话给代理
  ↓
收到回复邮件 → exception.auto_close (resolved_at, resolution="已电话沟通")
```

## 6. v0.5 端到端验收 (主链路)

1. ✅ 操作员创建一个 Shipment (填客户/路线/柜型/ETD)
2. ✅ Shipment 出现在工作台
3. ✅ 操作员选供应商, 点"生成订舱邮件" → 预览 Jinja2 渲染
4. ✅ 点"发送" → 创建 BookingRequest BR-001, 创建 outbound EmailMessage, 邮件真发出去
5. ✅ 操作员等几秒, 手动"模拟收到 SO" (因为 v0.5 dev 阶段没真 IMAP): 上传 PDF
6. ✅ 系统 OCR PDF → Document(ocr_text) + DocumentExtraction(fields)
7. ✅ 系统根据文件名/主题自动匹配到 Shipment, 创建 BookingConfirmation BC-001 (status=matched_pending)
8. ✅ 操作员进业务详情, 看到 BC-001 + diff 列表 (OCR 字段 vs BookingRequest 申请值)
9. ✅ 操作员点"接受" → BC-001.status=accepted, is_current=true, 字段写入 Shipment
10. ✅ 接受时自动生成 Task: "记录柜号" / "提交 SI" / "提交 VGM" (按 ETA 算 due_at)
11. ✅ 系统自动生成 Milestone: booking_confirmation_accepted
12. ✅ stage 由 Milestone 推导: booked
13. ✅ 操作员在业务详情, 录入 Container(柜号/封条号/提柜时间)
14. ✅ 录入时自动生成 Milestone: container_picked_up, 自动关闭 Task "记录柜号"
15. ✅ 录入装柜时间 → Milestone: container_loaded
16. ✅ 操作员点"提交 SI" → Task 完成, Milestone: si_submitted
17. ✅ 操作员点"开船" → Milestone: departed, stage 推导 → departed
18. ✅ 工作台显示剩余 Task (提交 VGM / 派送 / 还箱)
19. ✅ 操作员录入 BL 文件 → Document, 自动创建 future Bill 关联

**这条主链路顺了, v0.5 算成功.**

## 7. v0.5 不做什么

- 完整费用管理 (报价/利润/调价) → v0.6
- 客户门户/小程序 → v0.7
- 拖柜/报关/仓库子模块 → v0.6+
- 完整 React 业务详情页 → v0.5 阶段 3 (API 稳定后)
- SaaS 多租户 → 永远不做 (本系统只服务你公司)
- 集装箱多柜 (一票多柜) → v0.6

## 8. ADR 索引

- [ADR-0001: Shipment 聚合根 + Organization/Partner](0001-shipment-aggregate.md) (ACCEPTED)
- [ADR-0002: BookingRequest + BookingConfirmation](0002-booking-request-confirmation.md) (ACCEPTED)
- [ADR-0003: Document + EmailThread + EmailMessage + DocumentExtraction](0003-document-email-thread.md) (ACCEPTED)
- [ADR-0004: Milestone + Task + OperationalException](0004-milestone-task-exception.md) (ACCEPTED)
- [ADR-0005: AuditLog + LegacyEntityMap](0005-audit-legacy.md) (ACCEPTED)
- [migration-map.md](migration-map.md) (阶段 2 数据迁移映射, 已写)
- [execution-decisions.md](execution-decisions.md) (12 项拍板决议备查, 已写)

## 9. 当前状态 (2026-08-20)

**阶段 0: 领域冻结 — ✅ 已完成**

- [x] 仓库冻结 `feature/v0.4-closed-loop`, tag `legacy-v0.4-pre-core-reset`
- [x] 新建 `refactor/v0.5-core-workflow` 分支 (commit 278e32d)
- [x] 5 份 ADR 草案 (DRAFT)
- [x] 5 份 ADR 由 Autumn 拍板 → 状态 ACCEPTED, 末尾加拍板结论
- [x] ADR-0001 补 Organization + Partner 上下文表
- [x] 写 `docs/domain/migration-map.md` (v0.4 → v0.5 字段映射, 12 个章节)
- [x] 写 `docs/domain/execution-decisions.md` (12 项拍板决议备查 + 5 阶段路线 + 验证清单)
- [x] ADR 末尾的 13 个待确认问题 → 全部回答并写入拍板结论

**下一步 (阶段 1): 新模型 + /api/v2 — ⏳ 等用户拍板**

- [ ] 12 个 SQLAlchemy model (Organization / Partner / Shipment / BookingRequest / BookingConfirmation / Container / Document / DocumentExtraction / EmailThread / EmailMessage / Milestone / Task / OperationalException / AuditLog / LegacyEntityMap)
- [ ] 15+ Pydantic schema
- [ ] /api/v2 路由 (shipments / booking-requests / booking-confirmations / documents / milestones / tasks / exceptions / audit-logs / email-threads / email-messages / partners / legacy-maps / dashboard)
- [ ] alembic migration 重建 schema
- [ ] 单元测试 + 端到端测试 (mock OCR + 模拟邮件)
- [ ] /api/v1 不删, 暂时保留

**后续阶段**

- [ ] 阶段 2: 数据迁移 (Booking/SO/Agent/EmailLog/TrackingEvent/Bill FK → 新表 + LegacyEntityMap)
- [ ] 阶段 3: React 业务页面重写 (Shipments 列表 + ShipmentDetail 多 tab + Partners + BookingConfirmationInbox + EmailThreads + OperationsDashboard + Tasks + Containers + Bills)
- [ ] 阶段 4: 端到端验收 (本文件 §6 的 19 步主链路)

## 10. 阶段 1 拆分方案 (待用户拍板)

阶段 1 是个大工程, 建议拆 4 个 sub-task 顺序推进, 每 sub-task 独立 commit + push:

### Sub-task 1.1: 领域基座
- `app/models/_base.py` (软删除基类 / 组织上下文 / 时间戳 mixin 升级)
- `app/models/organization.py` (Organization)
- `app/models/partner.py` (Partner, 替代 Agent)
- `app/models/audit.py` (AuditLog + actor 取值 from X-User-Id header)
- alembic revision 1: 创建 organizations / partners / audit_logs 表
- 测试: organization seed / partner CRUD / audit log 自动留痕

### Sub-task 1.2: 业务聚合
- `app/models/shipment.py` (Shipment)
- `app/models/booking_request.py` (BookingRequest)
- `app/models/booking_confirmation.py` (BookingConfirmation)
- `app/models/container.py` (Container)
- alembic revision 2: shipments / booking_requests / booking_confirmations / containers
- /api/v2/shipments (POST/GET/PATCH/list)
- /api/v2/booking-requests (CRUD + send + cancel)
- /api/v2/booking-confirmations (create + accept + reject)
- /api/v2/shipments/{id}/containers
- 测试: Shipment 完整生命周期 (建单 → 发申请 → 收确认 → 接受)

### Sub-task 1.3: 文件 + 邮件
- `app/models/document.py` (Document + DocumentExtraction)
- `app/models/email.py` (EmailThread + EmailMessage)
- alembic revision 3: documents / document_extractions / email_threads / email_messages
- /api/v2/documents (upload + ocr + match + accept)
- /api/v2/email-threads (list + 详情 + 收件箱)
- /api/v2/email-messages (outbound send + inbound 处理)
- 邮件主题自动加 [job_no] 前缀
- 邮件 → Shipment 自动匹配 (3 信号, 见 ADR-0003 §11.7)
- 测试: 上传 SO PDF → OCR → 匹配 → 创建 BookingConfirmation

### Sub-task 1.4: 状态分层 + 异常
- `app/models/milestone.py` (Milestone)
- `app/models/task.py` (Task + auto_close_on)
- `app/models/operational_exception.py` (OperationalException)
- alembic revision 4: milestones / tasks / operational_exceptions
- /api/v2/shipments/{id}/milestones
- /api/v2/shipments/{id}/tasks
- /api/v2/shipments/{id}/exceptions
- 派生 stage API (由 Milestone 集合推导)
- 异常自动规则 (if-else, 4 种 auto_close)
- 端到端 demo: 9 步主链路 (本文件 §6)

**预估**: 每个 sub-task 1~2 轮对话完成, 4 个 sub-task 累计 5~8 轮.
