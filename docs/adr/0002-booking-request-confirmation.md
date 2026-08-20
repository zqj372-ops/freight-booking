# ADR-0002: BookingRequest 与 BookingConfirmation

- 状态: DRAFT (待审)
- 日期: 2026-08-20
- 适用范围: v0.5 core workflow reset

## 1. 背景

v0.4 把"订舱申请"和"订舱确认"混在一起:

- 操作员手动 `create_booking()` = 业务上 = 发订舱申请 (但没有 BookingRequest 实体记录"申请")
- 操作员 `confirm_so()` = 业务上 = 接受 SO (但又顺手建了 Booking, 重复了)
- v0.4 Booking 同时表达 "我发出了请求" + "对方确认了" + "我在内部" 三种语义, 互相打架

## 2. 决策

**拆成两个独立表: BookingRequest (我发出) + BookingConfirmation (对方确认). 关系是 Shipment 1 ── N BookingRequest 1 ── 0..1 BookingConfirmation.**

### 2.1 BookingRequest (订舱申请, 我发出)

每次对外发订舱都创建一条记录. 改 ETD / 改港 / 换船公司, 都要创建新版本 (递增 booking_request_no).

```
BookingRequest:
  id                    uuid
  shipment_id           uuid (FK) Shipment
  partner_id            uuid (FK) Partner        # 供应商 (一级代理/船公司直客)

  booking_request_no    str                       # BR-001/BR-002 系统生成
  request_version       int                       # 1, 2, 3 ...
  supersedes_id         uuid nullable (FK)         # 旧版指向新版 (业务时间序)

  # 申请时的快照 (cargo_snapshot): 当时锁定的客户/货物/路线/柜型
  cargo_snapshot        json                      # 见 §2.3
  requested_etd         date
  requested_pol         str
  requested_pod         str
  requested_container_type str
  requested_container_count int

  # 沟通
  email_thread_id       uuid nullable (FK)         # 关联邮件线程
  email_message_id      uuid nullable (FK)         # 这次发的邮件 Message
  email_account_id      uuid nullable (FK)         # 用哪个邮箱发

  # 状态
  status                enum                       # 见 §2.4
  sent_at               datetime nullable
  acknowledged_at       datetime nullable           # 供应商确认收到
  confirmed_at          datetime nullable           # 供应商确认订舱
  rejected_at           datetime nullable
  rejection_reason      text nullable
  cancelled_at          datetime nullable
  cancellation_reason   text nullable

  # SLA
  expected_response_by  datetime nullable           # 操作员填的 SLA
  response_sla_hours    int nullable                # 默认 24h

  # 备注
  remark                text nullable

  created_at, updated_at, created_by
```

#### 2.1.1 BookingRequest 状态机

```
draft ──发邮件──> sent ──对方回邮说收到──> acknowledged
                       │                    │
                       │                    ├──对方回 SO/Booking──> confirmed
                       │                    └──对方拒──> rejected
                       │
                       ├──超时未回──> (开 exception: booking_response_overdue)
                       │
                       └──我方取消──> cancelled (终态)
```

`confirmed` 不一定立刻变 Shipment.stage, 还要人工 review + accept BookingConfirmation (见 §2.2).

### 2.2 BookingConfirmation (订舱确认, 对方发来)

每次收到船公司/代理回复的 SO/Booking 文件, 解析 + 人工核对后, 创建一条记录. 一个 Shipment 多个版本 (改船期, 改港, 换船公司).

```
BookingConfirmation:
  id                    uuid
  shipment_id           uuid (FK) Shipment
  booking_request_id    uuid nullable (FK)         # 可空: 收到的 SO 有时无法立刻匹配到具体某次申请

  # 解析结果 (来自 OCR/人工, 字段来源标注在 extraction 中)
  carrier               str nullable               # 船公司
  carrier_booking_no    str nullable               # 船公司 Booking Number
  so_no                 str nullable
  bl_no                 str nullable
  vessel_name           str nullable
  voyage_no             str nullable
  pol                   str nullable               # 解析得到
  pod                   str nullable
  etd                   date nullable
  eta                   date nullable

  # 截关 (单独存, 不混在 etd/eta 里)
  cy_open_at            datetime nullable
  si_cutoff_at          datetime nullable
  vgm_cutoff_at         datetime nullable
  cy_cutoff_at          datetime nullable

  # 柜
  container_type        str nullable
  container_count       int nullable

  # 文档关联
  document_id           uuid (FK) Document          # 来源 PDF/图片
  extraction_id         uuid (FK) DocumentExtraction  # OCR 抽取结果

  # 版本
  version               int                         # 1, 2, 3 ...
  is_current            bool                        # 当前有效版本
  supersedes_id         uuid nullable (FK)          # 旧版指向新版

  # 状态
  status                enum                        # 见 §2.4
  review_status         enum                        # 见 §2.5

  # 接受人
  accepted_at           datetime nullable
  accepted_by           uuid nullable

  # 备注
  remark                text nullable

  created_at, updated_at
```

#### 2.2.1 BookingConfirmation 状态

```
unmatched       # 系统刚拿到, 还没匹配到 Shipment
matched_pending  # 已自动匹配候选, 等人工确认
accepted        # 人工接受, 字段写入 Shipment (或形成下一版 supersedes)
superseded      # 被新版本替代
rejected        # 人工拒绝
duplicate       # 与已有版本重复
```

#### 2.2.2 review_status (审核状态, 独立于 status)

```
needs_review    # OCR 抽取后有低置信度字段
reviewed        # 全部字段已确认
```

### 2.3 cargo_snapshot 字段

BookingRequest 发出时的客户/货物/柜型快照. BookingRequest 是 Shipment 的"申请版"副本, 防止 Shipment 字段改了之后历史对账找不回原值.

```
cargo_snapshot = {
  "commodity": "...",
  "hs_code": "...",
  "pieces": ...,
  "weight_kg": ...,
  "volume_cbm": ...,
  "pol": "...",
  "pod": "...",
  "target_etd": "...",
  "container_type": "...",
  "container_count": ...,
  "is_dangerous": false,
  "is_oversize": false,
  "incoterm": "...",
  "customer_ref": "..."
}
```

### 2.4 字段来源

OCR 抽取的字段和 BookingRequest.cargo_snapshot 对比, 差异处标红, 人工接受时确认.

差异数据存 `BookingConfirmation.context` 字段:

```
context = {
  "diff": {
    "pol": {"requested": "CNSHA", "confirmed": "CNSHA", "match": true},
    "etd": {"requested": "2026-09-01", "confirmed": "2026-09-02", "match": false,
            "delta_days": 1},
    "container_count": {"requested": 1, "confirmed": 2, "match": false}
  }
}
```

## 3. 一个 Shipment 多个版本怎么处理

场景: 客户改 ETD, 操作员要:
1. 取消原 BookingRequest (status=cancelled)
2. 创建新 BookingRequest (cargo_snapshot 用新 ETD)
3. 发新邮件 (新 email_message)
4. 收到新 SO → 创建新 BookingConfirmation (supersedes_id 指向旧)
5. 人工接受 → 新字段写入 Shipment, 旧 BookingConfirmation.is_current=false

`is_current` 决定哪个版本的字段是当前 Shipment 的"事实来源".

## 4. 与 v0.4 兼容

- v0.4 `Booking.booking_no` → BookingRequest.legacy_booking_no
- v0.4 `SO` 文件记录 → BookingConfirmation.document 关联, BookingRequest 不需要从 SO 派生
- v0.4 `confirm_so()` 路径删除 (这是 v0.4 的 bug)

## 5. 验收 (v0.5 阶段 1)

- [ ] BookingRequest / BookingConfirmation model + schema
- [ ] POST /api/v2/shipments/{id}/booking-requests 创建申请
- [ ] GET /api/v2/shipments/{id}/booking-requests 列表
- [ ] PATCH /api/v2/booking-requests/{id} 修改
- [ ] POST /api/v2/booking-requests/{id}/send 发送 (调 email service + 创建 email_message)
- [ ] POST /api/v2/booking-requests/{id}/cancel 取消
- [ ] POST /api/v2/booking-confirmations 创建确认
- [ ] PATCH /api/v2/booking-confirmations/{id}/accept 接受
- [ ] PATCH /api/v2/booking-confirmations/{id}/reject 拒绝
- [ ] is_current 自动切换 (接受新版时, 旧版自动 superseded)
- [ ] cargo_snapshot diff 计算 API
- [ ] 邮件主题自动加 job_no 嵌入
- [ ] 邮件 thread 关联 (Message-ID / In-Reply-To)
- [ ] v0.4 SO 上传兼容 (SO → Document → BookingConfirmation)
