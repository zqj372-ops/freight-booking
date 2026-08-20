# ADR-0005: AuditLog + LegacyEntityMap

- 状态: **ACCEPTED** (2026-08-20 由 Autumn 拍板)
- 日期: 2026-08-20
- 适用范围: v0.5 core workflow reset

## 1. 背景

v0.4 没有任何审计/追溯机制:

- 字段被谁改的不知道
- 改之前是什么值不知道
- v0.4 → v0.5 迁移后, 旧 Booking / SO / Bill 在哪里, 不知道
- 合规要求 (财务/操作责任) 无法满足

## 2. 决策

**两张表: AuditLog (操作审计) + LegacyEntityMap (旧→新实体映射).**

## 3. AuditLog

任何 Shipment / BookingRequest / BookingConfirmation / Document / Task / Exception 上的写操作都自动留痕.

```
AuditLog:
  id                uuid
  organization_id   uuid (FK)
  entity_type       str                          # "shipment" / "booking_request" / ...
  entity_id         uuid
  action            enum                         # create / update / delete / accept / reject / send / cancel

  # 变更详情
  field_changes     json nullable                # {field: {"old": ..., "new": ...}}
  context           json nullable                # request_id / ip / user_agent / reason

  actor_type        enum                         # user / system / scheduled_job
  actor_user_id     uuid nullable (FK)
  actor_job_name    str nullable                 # e.g. "imap_poll"

  created_at        datetime
```

### 3.1 哪些操作要留痕

| 实体 | 操作 |
|---|---|
| Shipment | create / update / stage_change / cancel |
| BookingRequest | create / send / acknowledge / confirm / reject / cancel |
| BookingConfirmation | create / accept / reject / supersede |
| Document | upload / ocr_done / match / delete |
| Task | create / complete / cancel |
| OperationalException | detect / resolve / auto_close |
| Milestone | record (任何节点都留) |
| EmailMessage | receive / send / match |

### 3.2 实现

中间件 + 装饰器. 例如:

```python
@audit_log(entity_type="shipment", action="update")
async def patch_shipment(id: str, ...):
    ...
```

中间件自动捕获:
- actor (从 JWT 取 user)
- before / after diff
- request_id

敏感操作 (accept / reject / cancel) 还加 `reason` 必填字段.

## 4. LegacyEntityMap

v0.4 → v0.5 迁移后, 旧数据要能找到新位置. 一个表搞定:

```
LegacyEntityMap:
  id                  uuid
  organization_id     uuid (FK)
  legacy_table        str                       # "bookings" / "sos" / "bills" / ...
  legacy_id           str                       # 旧 uuid
  legacy_booking_no   str nullable              # 旧 booking_no (方便查)

  new_entity_type     str                       # "shipment" / "booking_confirmation" / ...
  new_entity_id       uuid

  migration_status    enum                      # migrated / needs_review / failed
  migration_warning   text nullable             # "missing so_number" 等
  migrated_at         datetime
  migrated_by         str                       # "v0.4_to_v0.5_migration"
```

唯一约束: `(organization_id, legacy_table, legacy_id)`.

### 4.1 使用场景

- 用户: "v0.4 我有个 SO xxx 现在在哪里?" → 查 LegacyEntityMap, 给新 BookingConfirmation 链接
- 财务: "v0.4 那批账单 v0.5 后怎么对?" → 查 LegacyEntityMap 找到新 Bill
- 排查: 旧数据不一致时, migration_status=needs_review, 留 migration_warning 人工处理

### 4.2 迁移不完整时的处理原则

> **不能让数据看起来完整而编造业务事实.**

例:
- 旧 Booking.status=confirmed, 但没有 SO → 迁移成 Shipment(stage=draft, 没有 BookingConfirmation), migration_status=needs_review
- 旧 SO.carrier=MAERSK, 但 OCR 字段不全 → 迁移成 Document(ocr_status=pending) + BookingConfirmation(status=unmatched), migration_status=migrated, migration_warning="low OCR confidence"

## 5. 验收 (v0.5 阶段 2-3)

- [ ] AuditLog model + schema
- [ ] 中间件自动捕获 actor + diff
- [ ] GET /api/v2/audit-logs?entity_type=&entity_id= 查审计
- [ ] GET /api/v2/shipments/{id}/history 时间线视图
- [ ] LegacyEntityMap model
- [ ] 迁移脚本: Booking → Shipment + LegacyEntityMap
- [ ] 迁移脚本: SO → Document + BookingConfirmation
- [ ] 迁移脚本: Agent → Partner
- [ ] 迁移脚本: Bill.booking_id → Bill.shipment_id
- [ ] 迁移脚本: TrackingEvent → Milestone
- [ ] 迁移报告: 数量 + needs_review 列表
- [ ] v0.4 /api/v1 暂时只读 (兼容性)

## 6. 拍板结论 (2026-08-20, Autumn ACCEPTED)

1. **actor 取值**: JWT 暂不实现. v0.5 用 FastAPI Depends 从 request header 取 `X-User-Id` (UUID) + `X-User-Name`. 没传则用 system default: `actor_type=system, actor_user_id=NULL, actor_job_name='api_call'`. 前端在 `apiClient` 拦截器里塞 header. 等 v0.6 接真 JWT 时换实现, AuditLog schema 不变.
2. **sensitive 操作 reason 强制**: `accept` / `reject` / `cancel` / `delete` 4 个 action 必须在 request body 带 `reason: str` (min 5 字符). 缺字段返回 422. 前端表单做 required 验证.
3. **v0.4 历史数据不回填 audit**: AuditLog 从 v0.5 上线日清零. v0.4 字段修改历史丢失 (实际生产中本来也没记). 需要追溯时通过 LegacyEntityMap + 老数据库 snapshot 查.
4. **LegacyEntityMap 暴露给用户**: API `GET /api/v2/legacy-maps?legacy_booking_no=XXX` 提供查询. 业务详情页加 "v0.4 来源" tab 显示当前 Shipment 对应的旧 Booking/SO 记录 (只读快照). 不会显示给客户, 只给内部操作员.
5. **migration_status=needs_review 不阻塞**: 迁移后有 needs_review 记录时, 系统照常运行, 不强求人工处理. 但工作台有专属 "迁移待复核" 卡片提醒, 直到全部 resolved.
6. **AuditLog 不做全文检索**: v0.5 简单 `entity_type + entity_id + created_at` 索引 + 分页. 全文搜索留 v0.6 (考虑 SQLite FTS5 或迁 Postgres).
