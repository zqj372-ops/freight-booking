# v0.4 → v0.5 数据迁移映射 (Migration Map)

> **本文件是 ADR-0001~0005 拍板后, v0.5 阶段 2 数据迁移脚本的字段对照表.**
> 数据迁移原则: **不能为了让数据看起来完整而编造业务事实**.

## 0. 迁移策略总览

不是把旧表 `bookings` 改名为 `shipments`, 而是:

```
v0.4 表 (只读保留)
  ↓
迁移脚本 (一次性)
  ↓
v0.5 新表 (主用)
  ↓
LegacyEntityMap (新→旧索引)
```

迁移后:
- v0.4 表保留, 标记为 "legacy" 状态, 不写
- v0.4 API `/api/v1/*` 降级为只读兼容层
- v0.5 API `/api/v2/*` 为主用
- 工作台/详情页都从 v0.5 表读

## 1. 对象级映射

| v0.4 表 | v0.5 表 | 处理原则 |
|---|---|---|
| (无) | `organizations` | seed 一行 `slug='default-company'`, 所有迁移记录都用它的 UUID |
| `agents` | `partners` | `Agent.name → Partner.name`, `Agent.code → Partner.short_code`, `Agent.booking_email → Partner.primary_email`, `Agent.cc_emails → Partner.cc_emails`, `Agent.service_routes → Partner.preferred_routes`. `partner_type='agent_l1'` (无法区分 L1/L2, 默认 L1) |
| `bookings` | `shipments` | 见 §2 Booking → Shipment |
| (无) | `booking_requests` | 仅当 Booking 状态 SUBMITTED/CONFIRMED 时, 创建一条 BR-001 (status=confirmed, sent_at=booking.created_at) |
| `sos` | `documents` + `booking_confirmations` | 见 §3 SO → Document + BookingConfirmation |
| `email_logs` | `email_messages` (outbound) + `email_threads` | 见 §4 EmailLog → EmailMessage |
| `tracking_events` | `milestones` | 见 §5 TrackingEvent → Milestone |
| `bills` | `bills` (保留) | `booking_id` 改 `shipment_id`, 加 `matched_shipment_id` (替代 matched_booking_id) |
| (无) | `tasks` | 不迁移, 全新对象 |
| (无) | `operational_exceptions` | 不迁移, 全新对象 |
| (无) | `audit_logs` | 不回填, 全新对象 (从 v0.5 上线日清零) |
| (无) | `legacy_entity_maps` | 每次迁移都写一条 |
| `email_ingestions` | `email_ingestions` (保留) | 不动, 暂存为 IMAP 拉取历史 |
| `processed_emails` | `processed_emails` (保留) | 不动, v0.5 IMAP 去重仍用 |
| `email_templates` | `email_templates` (保留) | 不动 |

## 2. Booking → Shipment 详细映射

### 2.1 字段映射

| v0.4 Booking | v0.5 Shipment | 备注 |
|---|---|---|
| `id` (uuid) | `id` (uuid) | 直接搬, 同值 |
| (无) | `organization_id` (uuid) | 写默认组织的 UUID |
| (无) | `job_no` (str) | 新生成 `FB-{migration_date}-XXXX`, 全局唯一 |
| `booking_no` (如 `MAE-20260820-A8F3`) | `legacy_job_no` (str) | 整段搬过来, 加 UNIQUE(organization_id, legacy_job_no) 索引 |
| (无) | `customer_ref` (str) | 来自 Booking.customer_ref, 同名搬 |
| (无) | `carrier_booking_no` (str) | **不**从 booking_no 拆! 留空, 等 v0.5 收到 SO 确认后才填. 除非 SO.booking_number 不为空且与 booking_no 不同, 才填 |
| `customer_name` | (无) | 拆出来: 创建一个 `Partner(partner_type='customer', name=customer_name)`, 写 `customer_partner_id` |
| `customer_ref` | `customer_ref` | 同名 |
| `carrier` | `current_carrier` | 同值搬, 字段改名 |
| `agent_id` (FK→agents) | `current_partner_id` (FK→partners) | 关联新 Partner, partner_type=agent_l1 |
| `pol` | `pol` | 同值 |
| `pod` | `pod` | 同值 |
| (无) | `final_destination` (str) | 留空, v0.5 录入 |
| `etd` | `target_etd` (date) | 只取 date 部分, 留 time=00:00 |
| (无) | `etd` (实际确认 ETD) | 来自 SO.etd (被接受的 BookingConfirmation), 不直接搬 Booking.etd |
| (无) | `eta` (实际确认 ETA) | 来自 SO.eta |
| `cut_off` | (无) | 拆出来进 `BookingConfirmation.cy_cutoff_at` (被接受的那个) |
| `container_type` | `container_count=1`, `container_type` 记录到 Container (后续) | v0.5 一柜一单, 字段保留作冗余 |
| `container_count` | `container_count` | 同值搬 (v0.5 业务上 =1, 数据可能 >1, 数据保留原值) |
| `commodity` | `commodity` | 同值 |
| (无) | `hs_code` | 留空 |
| (无) | `pieces` | 留空 (v0.4 Booking 不存) |
| `weight_kg` | `weight_kg` | 同值 |
| `volume_cbm` | `volume_cbm` | 同值 |
| (无) | `is_dangerous` | 默认 false |
| (无) | `is_oversize` | 默认 false |
| `status` (enum) | `stage` (enum) + Milestone | 见 §2.2 状态映射 |
| `remark` | `remark` | 同值 |
| `created_at` | `created_at` | 同值 |
| `updated_at` | `updated_at` | 同值 |

### 2.2 Booking.status → Shipment.stage + 初始 Milestone

| v0.4 Booking.status | v0.5 Shipment.stage | 同步创建 Milestone |
|---|---|---|
| `DRAFT` | `draft` | 无 |
| `SUBMITTED` | `booking_in_progress` | `booking_request_sent` (occurred_at=created_at) |
| `CONFIRMED` (有 SO) | `awaiting_confirmation` 或 `booked` | `booking_confirmation_received` + `booking_confirmation_accepted` (如果 SO.status=CONFIRMED). 见 §2.3 |
| `CONFIRMED` (无 SO) | `draft` | 无, migration_warning="status=confirmed but no SO" |
| `REJECTED` | `cancelled` (强制取消, reason=v0.4 rejected) | `booking_rejected` |
| `CANCELLED` | `cancelled` (reason=v0.4 cancelled) | 无 |
| `COMPLETED` | `completed` | `delivered` + `empty_returned` (从 TrackingEvent 取最后两个) |

### 2.3 CONFIRMED 但 SO.status 不同的处理

- Booking 状态 CONFIRMED + SO.status=CONFIRMED → Shipment.stage=booked, 创建 Milestone `booking_confirmation_accepted`
- Booking 状态 CONFIRMED + SO.status=PENDING/OCR_DONE → Shipment.stage=awaiting_confirmation, 只创建 Milestone `booking_confirmation_received`, `accepted` 不创建 (等 v0.5 人工 accept)
- Booking 状态 CONFIRMED + 没有 SO 记录 → Shipment.stage=draft, migration_warning="confirmed but no so", status=needs_review

### 2.4 BookingRequest 生成规则

只有 Booking.status 属于以下值才生成 BookingRequest:
- SUBMITTED, CONFIRMED, REJECTED, COMPLETED

规则:
- 一个 Booking 生成一个 BookingRequest, `request_version=1`, `booking_request_no=BR-001`
- `status` 直接用 Booking.status 映射:
  - SUBMITTED → `sent` (sent_at=booking.created_at)
  - CONFIRMED → `confirmed` (sent_at=booking.created_at, acknowledged_at/confirmed_at 从 TrackingEvent 推)
  - REJECTED → `rejected` (rejection_reason 从 remark 提取)
  - COMPLETED → `confirmed` (当作历史已接受)
- DRAFT/CANCELLED → 不生成 BookingRequest (没有"申请"语义)

## 3. SO → Document + BookingConfirmation 详细映射

### 3.1 Document 创建

每个 v0.4 SO 记录创建一条 v0.5 Document:

| v0.4 SO | v0.5 Document | 备注 |
|---|---|---|
| `id` | (无) | v0.5 Document.id 是新 UUID |
| (无) | `organization_id` | 默认组织 UUID |
| (无) | `shipment_id` | 来自 SO.booking_id 映射到的新 Shipment.id, 如果 SO 没关联 Booking 则为 NULL |
| (无) | `booking_request_id` | 来自新 Shipment 的 BR-001 (如有) |
| `source` ("upload" / "email" / "api") | `source` (enum) | "upload" → `manual_upload`, "email" → `imap_attachment`, "api" → `manual_upload` |
| `source_email` | (无) | 拆分进 EmailMessage.from_addr (无 inbound 邮件上下文, 留空) |
| `source_subject` | (无) | 同上 |
| `file_path` | `file_path` | 同值 |
| `file_name` | `filename` | 改名 |
| `file_mime` | `mime_type` | 改名 |
| `file_size` | `file_size` | 同值 |
| (无) | `file_hash` (sha256) | 迁移时计算并写入 |
| `status` | `ocr_status` (enum) | "PENDING" → `pending`, "OCR_DONE" → `done`, "OCR_FAILED" → `failed`, "CONFIRMED"/"REJECTED" → `done` |
| `ocr_text` | `ocr_text` | 同值 |
| `ocr_engine` | `ocr_engine` | 同值 |
| `ocr_confidence` | `ocr_confidence` | 同值 |
| `ocr_error` | `ocr_error` | 同值 |
| `ocr_at` | `ocr_at` | 同值 |
| (无) | `doc_type` | 默认 `so` |
| (无) | `carrier_hint` | 来自 SO.carrier |
| (无) | `parse_status` | "CONFIRMED" → `matched_booking`, "REJECTED" → `ignored`, 其他 → `unmatched` |
| (无) | `parse_confidence` | 来自 OCR 整体置信度 (ocr_confidence) |
| (无) | `uploaded_by` | NULL (v0.4 没记录操作员) |
| (无) | `uploaded_at` | 来自 created_at |

### 3.2 BookingConfirmation 创建

每个 v0.4 SO 记录同时创建一条 v0.5 BookingConfirmation:

| v0.4 SO | v0.5 BookingConfirmation | 备注 |
|---|---|---|
| `id` | (无) | v0.5 BookingConfirmation.id 是新 UUID |
| (无) | `organization_id` | 默认组织 UUID |
| (无) | `shipment_id` | 来自 SO.booking_id 映射, 可空 |
| (无) | `booking_request_id` | 来自新 Shipment 的 BR-001 (如有) |
| (无) | `document_id` | 关联刚创建的 Document |
| (无) | `extraction_id` | 见 §3.3 DocumentExtraction |
| `carrier` | `carrier` | 同值 |
| `booking_number` | `carrier_booking_no` | 同值 (但**不**作为 Shipment.legacy_job_no, 那个来自 Booking.booking_no) |
| `so_number` | `so_no` | 改名 |
| `bl_number` | `bl_no` | 改名 |
| `vessel_name` | `vessel_name` | 同值 |
| `voyage_no` | `voyage_no` | 同值 |
| `pol` | `pol` | 同值 |
| `pod` | `pod` | 同值 |
| `etd` | `etd` | 同值 |
| `eta` | `eta` | 同值 |
| `cut_off` | `cy_cutoff_at` | 改名 |
| (无) | `cy_open_at` / `si_cutoff_at` / `vgm_cutoff_at` | 留空 (v0.4 SO 没存) |
| `container_type` | `container_type` | 同值 |
| `container_count` | `container_count` | 同值 |
| (无) | `version` | 默认 1 |
| (无) | `is_current` | SO.status=CONFIRMED → true, 其他 → false |
| (无) | `supersedes_id` | NULL (v0.4 没有版本概念) |
| `status` | `status` (enum) | "PENDING" → `unmatched`, "OCR_DONE" → `matched_pending`, "OCR_FAILED" → `unmatched` (migration_warning="ocr failed"), "CONFIRMED" → `accepted`, "REJECTED" → `rejected` |
| (无) | `review_status` | SO.status=CONFIRMED → `reviewed`, 其他 → `needs_review` |
| (无) | `accepted_at` | SO.status=CONFIRMED → 用 SO.updated_at |
| (无) | `accepted_by` | NULL |
| `extra_fields` (JSON) | `extraction_id` (FK) | 抽到 DocumentExtraction.fields, 见 §3.3 |
| `created_at` | `created_at` | 同值 |
| `updated_at` | `updated_at` | 同值 |

### 3.3 DocumentExtraction 创建

如果 v0.4 SO 有 `extra_fields` (JSON), 抽到 DocumentExtraction:

```python
{
  "fields": {
    field_name: {
      "value": extra_fields[field_name],
      "confidence": so.ocr_confidence,  # 整体置信度, 字段级没有
      "source": "v0.4_migration"
    }
    for field_name in extra_fields
  },
  "extraction_method": "regex",  # v0.4 用的是 regex/规则
  "model_version": so.ocr_engine,
  "raw_response": so.ocr_text[:5000] if so.ocr_text else None,
  "diff": None  # 迁移时不计算 diff
}
```

## 4. EmailLog → EmailMessage (outbound) 详细映射

每个 v0.4 EmailLog 创建一条 v0.5 EmailMessage + 一条 v0.5 EmailThread:

### 4.1 EmailThread 创建

- 一个 EmailLog 一条 EmailThread (一对一, v0.4 没有 thread 概念)
- `subject` 来自 EmailLog.subject
- `subject_prefix` 正则提取 `[XXX]` 前缀 (如果没匹配到, NULL)
- `shipment_id` 来自 EmailLog.booking_id 映射
- `partner_id` 来自 EmailLog.so_id → Document.shipment_id → Shipment.current_partner_id, 或 NULL
- `status='active'`

### 4.2 EmailMessage 创建

| v0.4 EmailLog | v0.5 EmailMessage | 备注 |
|---|---|---|
| `id` | (无) | 新 UUID |
| (无) | `organization_id` | 默认组织 |
| (无) | `thread_id` | 关联刚创建的 EmailThread |
| (无) | `direction` | `outbound` (v0.4 只有出站) |
| (无) | `message_id` | NULL (v0.4 没存 Message-ID), 后续 inbound 邮件会用 |
| (无) | `in_reply_to` | NULL |
| (无) | `references` | NULL |
| (无) | `from_addr` | 从 app config 读 default sender, 或 NULL |
| `to_emails` | `to_addrs` | 改名, 数据格式一致 (list[str]) |
| `cc_emails` | `cc_addrs` | 改名 |
| `subject` | `subject` | 同值 |
| `body` | `body_text` | 改名 |
| (无) | `body_html` | NULL |
| (无) | `received_at` | NULL (outbound 没"收到"概念) |
| `sent_at` | `sent_at` | 同值 |
| `status` (EmailStatus) | `status` (新 enum) | "PENDING" → `queued`, "SENT" → `sent`, "FAILED" → `failed`, "RETRYING" → `queued` |
| `error` | `error` | 同值 |
| `retry_count` | `retry_count` | 同值 |
| (无) | `source` | `smtp_send` |
| (无) | `raw_eml_path` | NULL (v0.4 没存 .eml) |
| (无) | `matched_shipment_id` | 来自 booking_id 映射 |
| (无) | `matched_booking_request_id` | 来自新 Shipment 的 BR-001 (如有) |
| `booking_id` | (无) | 进 matched_shipment_id |
| `so_id` | (无) | 进 matched 上下文, 但 v0.5 EmailMessage 不直接关联 SO, 关联 thread + Shipment |
| `context` (JSON) | (无) | 弃用, 进 audit log |
| `created_at` | `created_at` | 同值 |
| `updated_at` | `updated_at` | 同值 |

## 5. TrackingEvent → Milestone 详细映射

| v0.4 TrackingEvent.status | v0.5 Milestone.code |
|---|---|
| `BOOKED` | `booking_confirmation_accepted` (取最近一次 SO 接受时间) |
| `EMPTY_PICKED_UP` | `container_picked_up` |
| `LOADED` | `container_loaded` |
| `DEPARTED` | `departed` |
| `IN_TRANSIT` | `in_transit` |
| `ARRIVED` | `arrived_at_pod` |
| `DELIVERED` | `delivered` |
| `COMPLETED` | 不创建新 Milestone, 用最后那个 `delivered` |
| `EXCEPTION` | 不创建 Milestone, 留作 v0.5 OperationalException 用 (可选) |

其他字段映射:
| v0.4 | v0.5 |
|---|---|
| `id` | 不保留, 新 UUID |
| `booking_id` | `shipment_id` (FK) |
| `status` | `code` (enum, 见上表) |
| `occurred_at` | `occurred_at` |
| `recorded_at` (用 created_at) | `recorded_at` |
| `source` | `source` (MANUAL → manual, EMAIL → email, API → api, AUTO → auto) |
| `location` | `location` |
| `vessel_name` | `vessel_name` |
| `voyage_no` | `voyage_no` |
| `container_no` | `container_no` |
| `remark` | `remark` |

## 6. Agent → Partner 详细映射

| v0.4 Agent | v0.5 Partner | 备注 |
|---|---|---|
| `id` | (无) | 新 UUID |
| (无) | `organization_id` | 默认组织 |
| `name` | `name` | 同值 |
| `code` | `short_code` | 改名, 保留 UNIQUE(organization_id, short_code) |
| `contact_person` | `contact_person` | 同值 |
| `contact_phone` | `contact_phone` | 同值 |
| `contact_email` | (无) | 留空, 用 booking_email |
| `booking_email` | `primary_email` | 改名 |
| `cc_emails` | `cc_emails` | 同值 |
| `service_routes` | `preferred_routes` | 改名 |
| `notes` | `remark` | 改名 |
| `is_active` | `is_active` | 同值 |
| (无) | `partner_type` | `agent_l1` (v0.4 无法区分 L1/L2, 全默认 L1) |
| (无) | `preferred_carriers` | NULL |
| (无) | `response_sla_hours` | NULL |
| (无) | `default_template_id` | NULL |
| `created_at` | `created_at` | 同值 |
| `updated_at` | `updated_at` | 同值 |

迁移后: `Booking.agent_id` 已经无法直接 FK 到新 Partner, 走 LegacyEntityMap 关联. `Bill.matched_booking_id` 也类似.

## 7. Bill 微调 (保留 v0.5 主用, 不破坏)

`bills` 表**不重建**, 改字段:

| v0.4 Bill | v0.5 Bill |
|---|---|
| `booking_id` (FK→bookings) | 改名为 `shipment_id`, 加 FK→shipments, nullable |
| `matched_booking_id` (FK→bookings) | 改名为 `matched_shipment_id`, 加 FK→shipments, nullable |
| 其他字段 | 全部保留 |

迁移脚本: 直接用 ALTER TABLE (SQLite 不支持 rename column, 用 create new + copy + drop old 三步).

## 8. LegacyEntityMap 写入

每次成功迁移一条旧记录, 写一条 LegacyEntityMap. 关键映射:

| legacy_table | legacy_id | legacy_booking_no | new_entity_type | new_entity_id | migration_status |
|---|---|---|---|---|---|
| `bookings` | `<booking.id>` | `<booking.booking_no>` | `shipment` | `<new shipment.id>` | `migrated` / `needs_review` |
| `bookings` | `<booking.id>` | 同上 | `booking_request` | `<new BR.id>` (如有) | `migrated` |
| `sos` | `<so.id>` | `<booking.booking_no>` (从关联 Booking 拿) | `document` | `<new document.id>` | `migrated` |
| `sos` | `<so.id>` | 同上 | `booking_confirmation` | `<new BC.id>` | `migrated` |
| `agents` | `<agent.id>` | NULL | `partner` | `<new partner.id>` | `migrated` |
| `email_logs` | `<email.id>` | NULL | `email_message` | `<new EM.id>` | `migrated` |
| `email_logs` | `<email.id>` | NULL | `email_thread` | `<new ET.id>` | `migrated` |
| `tracking_events` | `<te.id>` | NULL | `milestone` | `<new MS.id>` | `migrated` |

唯一约束: `UNIQUE(organization_id, legacy_table, legacy_id)`.

migration_status:
- `migrated`: 正常, 全部字段都搬过去
- `needs_review`: 有字段缺失或异常, 留 migration_warning 说明原因 (例: "booking status=CONFIRMED but no SO")
- `failed`: 迁移时抛异常, 留 error trace

## 9. 迁移执行流程

```
1. 备份 data/freight.db → data/freight.v0.4.bak.{timestamp}.db
2. 启动 v0.5 alembic upgrade head (创建新表: organizations / partners / shipments / booking_requests / booking_confirmations / containers / documents / document_extractions / email_threads / email_messages / milestones / tasks / operational_exceptions / audit_logs / legacy_entity_maps)
3. 运行迁移脚本 python scripts/migrate_v04_to_v05.py
   - seed organization
   - 迁移 agents → partners
   - 迁移 bookings → shipments + booking_requests
   - 迁移 sos → documents + document_extractions + booking_confirmations
   - 迁移 email_logs → email_threads + email_messages
   - 迁移 tracking_events → milestones
   - 迁移 bills (改字段名 + FK)
   - 每次迁移写 legacy_entity_map
4. 输出迁移报告:
   - data/migration_report_{timestamp}.json
   - 包含: 每张表的迁移数量, needs_review 列表 (含 warning), failed 列表
5. 验证:
   - 抽样 N 条新表记录, 对比 v0.4 字段值, 必须 100% 一致
   - 所有 needs_review 在工作台有提醒
   - 所有 failed 立即报警, 不进入下一步
6. /api/v1/* 切换到 read-only (FastAPI 路由层加只读装饰器, 写操作返回 410 Gone)
7. 通知用户, 让用户在 UI 验证主链路
```

## 10. 不迁移 / 不回填

- `audit_logs`: v0.5 上线日清零, 不回填 v0.4 历史
- `tasks`: 全新, 不迁移
- `operational_exceptions`: 全新, 不迁移
- `containers`: v0.5 Shipment 默认生成 1 个占位 Container (container_no="TBD"), 真正提柜时操作员录入
- `email_ingestions` / `processed_emails`: 保留, 暂不动 (后续 IMAP 兼容用)

## 11. 回滚方案

如果 v0.5 上线后发现迁移有严重问题:

```
1. 停 uvicorn
2. cp data/freight.v0.4.bak.{timestamp}.db data/freight.db
3. alembic downgrade -1 (撤销 v0.5 schema)
4. 启动 uvicorn (回退到 v0.4)
```

回滚后 v0.5 阶段 1 写的 model 代码不动, 但运行时不用 /api/v2. LegacyEntityMap 数据保留供下次重试.

## 12. 验收 (v0.5 阶段 2)

- [ ] 迁移脚本幂等 (重复跑不重复写, 除非 allow_rewrite=true)
- [ ] 备份文件存在, 大小 > 0
- [ ] alembic upgrade 成功
- [ ] 迁移报告 JSON 生成, needs_review / failed 计数准确
- [ ] 抽样验证: 至少 5 条 Booking, 全部字段对得上
- [ ] /api/v1/* 写操作返回 410, 读操作正常
- [ ] /api/v2/shipments/{id} 能查回旧 booking_no (通过 legacy_job_no)
- [ ] 业务详情页能显示 "v0.4 来源" tab
- [ ] 旧数据 (用 v0.4 demo 跑过的 1 个 Booking + 1 个 SO) 在 v0.5 UI 上完整可见
