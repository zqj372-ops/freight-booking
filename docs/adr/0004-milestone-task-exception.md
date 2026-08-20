# ADR-0004: 状态分层 (Milestone + Task + OperationalException)

- 状态: DRAFT (待审)
- 日期: 2026-08-20
- 适用范围: v0.5 core workflow reset

## 1. 背景

v0.4 把所有进度塞进一个 `Booking.status` enum:

```python
class BookingStatus(str, enum.Enum):
    DRAFT, SUBMITTED, CONFIRMED, REJECTED, CANCELLED, COMPLETED
```

这个设计无法表达:

- "已订舱, 但 SI Cut-off 剩 8 小时" (同时存在阶段 + 异常)
- "收到 SO 但有字段差异" (阶段 + 待办任务)
- "装柜完成, 等待开船" (阶段 + 多 milestone)

## 2. 决策

**用三个独立表分别表达: Shipment.stage (粗粒度阶段) / Milestone (业务节点) / Task (待办) / OperationalException (异常).**

四个概念互不替代, 同时存在.

### 2.1 Shipment.stage (粗粒度, 1 个字段)

见 ADR-0001 §2.4. 这里只列一下:

```
draft → booking_in_progress → awaiting_confirmation → booked →
container_operation → documentation → departed → completed

任何阶段都可以 cancelled (终态)
```

### 2.2 Milestone (业务节点, 多个)

不可变日志, 一旦记录只能 `corrected_at` 不能改字段.

```
Milestone:
  id              uuid
  shipment_id     uuid (FK) Shipment
  code            enum    # 见 §2.2.1
  occurred_at     datetime # 业务发生时间
  recorded_at     datetime # 系统记录时间
  source          enum    # auto / manual / email / api
  source_ref      str nullable  # 邮件 Message-ID / API 调用 ID 等
  location        str nullable
  vessel_name     str nullable
  voyage_no       str nullable
  container_no    str nullable
  remark          text nullable
  corrected_at    datetime nullable  # 修正时间
  corrected_by    uuid nullable
```

#### 2.2.1 Milestone code 枚举

```
booking_request_sent           # 订舱申请发出
booking_request_acknowledged   # 供应商收到 (回邮件)
booking_confirmation_received  # 收到 SO / Booking Confirmation
booking_confirmation_accepted   # 人工接受 SO
booking_rejected               # 船公司拒接
empty_release_available         # 提箱开放
container_picked_up             # 提柜
container_gated_in              # 进港
container_loaded                # 装船
si_submitted                    # 提交 SI
vgm_submitted                   # 提交 VGM
customs_cleared                 # 报关
si_cutoff_passed                # SI 截关过
vgm_cutoff_passed               # VGM 截关过
cy_cutoff_passed                # CY 截关过
gate_in                         # 进闸口
departed                        # 开船
arrived_at_pol                  # 到达装货港
in_transit                      # 在途
arrived_at_pod                  # 到达卸货港
customs_cleared_at_pod          # 目的港清关
container_discharged            # 卸船
delivered                       # 派送
empty_returned                  # 还箱
```

### 2.3 Task (待办, 多个)

操作员/系统主动创建, 有明确 owner 和 due_time.

```
Task:
  id              uuid
  shipment_id     uuid (FK) Shipment
  code            enum    # 见 §2.3.1
  title           str     # 操作员可改
  description     text nullable
  due_at          datetime nullable
  assignee_user_id uuid nullable
  status          enum    # pending / in_progress / done / cancelled
  created_at, updated_at
  completed_at    datetime nullable
  completed_by    uuid nullable
  auto_close_on   enum nullable  # 哪个 milestone 自动关闭这个 task
```

#### 2.3.1 Task code 枚举 (v0.5 范围)

```
confirm_so              # 接受 SO 之前必须先确认匹配
confirm_booking        # 确认 Booking Confirmation 字段
contact_supplier        # 联系供应商
arrange_pickup          # 安排提柜
record_container_no    # 录入柜号
record_seal_no          # 录入封条号
submit_si                # 提交 SI
submit_vgm               # 提交 VGM
confirm_cargo_ready     # 确认货物就绪
confirm_loaded           # 确认装船
handle_exception         # 处理异常
```

### 2.4 OperationalException (异常, 0..N)

可被人工标记 resolved, 也可被自动 close (例如 schedule_changed 收到新 SO 后自动 close).

```
OperationalException:
  id              uuid
  shipment_id     uuid (FK) Shipment
  code            enum    # 见 §2.4.1
  severity        enum    # info / warning / critical
  status          enum    # open / resolved / auto_closed
  detected_at     datetime
  detected_by     enum    # system / manual
  resolved_at     datetime nullable
  resolved_by     uuid nullable
  resolution      text nullable
  related_milestone_id uuid nullable (FK) Milestone
  related_task_id       uuid nullable (FK) Task
  context         json    # 异常上下文 (e.g. {"old_etd": "...", "new_etd": "..."})
```

#### 2.4.1 Exception code 枚举

```
booking_response_overdue      # 订舱申请超过 SLA 未回复
booking_rejected              # 船公司拒接
so_mismatch                   # SO 字段与申请不符
schedule_changed              # 船期变更
port_changed                  # 港口变更
carrier_changed               # 船公司变更
container_rolled               # 甩柜
cutoff_approaching             # 截关临近
cutoff_passed                  # 截关已过未完成
si_overdue                    # SI 超时未提交
vgm_overdue                   # VGM 超时未提交
missing_container_no          # 缺柜号
missing_seal_no                # 缺封条号
email_send_failed              # 邮件发送失败
email_parse_failed             # 邮件解析失败
```

## 3. 状态联动规则

### 3.1 Milestone → Stage 自动推导 (软联动)

不直接写回 stage, 每次查询时由"最新的相关 milestone 集合"推导当前 stage. 这避免了状态机和 milestone 打架.

例如:
- 看到 `booking_confirmation_accepted` 但没 `container_picked_up` → 推导 `stage=booked`
- 看到 `container_picked_up` 但没 `delivered` → 推导 `stage=container_operation`
- 看到 `delivered` 但没 `empty_returned` → 推导 `stage=documentation`

这样 stage 只是 UI 提示, 真实进度看 milestone 序列.

但 UI 也会给一个按钮"手动调整 stage" 给特殊场景 (例如客户取消).

### 3.2 Milestone → Task 自动关闭

Task 有一个 `auto_close_on` 字段, 当对应 milestone 录入时自动 close.

例如:
- Task `record_container_no` 的 `auto_close_on=container_picked_up`
- 操作员录入 "提柜" milestone 时, 这个 task 自动 completed

### 3.3 Exception 自动生成 (基于规则)

| 触发条件 | 自动开 exception |
|---|---|
| BookingRequest sent 超过 24h 没收到 confirmation | `booking_response_overdue` |
| BookingConfirmation 字段与 BookingRequest 字段不一致 | `so_mismatch` |
| SI Cut-off - now < 4h 但 si_submitted milestone 不存在 | `si_overdue` |
| schedule_changed milestone 后, 检测到 ETD 变化 | `schedule_changed` (auto closed 收新 SO 后) |

## 4. v0.4 迁移

| v0.4 对象 | v0.5 对象 |
|---|---|
| `TrackingEvent.status` (enum) | `Milestone.code` (更细的 enum) |
| `TrackingEvent` | `Milestone` |
| (无对应) | `Task` (新功能) |
| (无对应) | `OperationalException` (新功能) |
| `Booking.status` (DRAFT/SUBMITTED/...) | 派生字段, 不直接存储 |

v0.4 `TrackingEvent` 数据全量迁移到 `Milestone`, 字段映射:

- `status="booked"` → `code=booking_confirmation_accepted` (近似)
- `status="in_transit"` → `code=in_transit`
- 等等, 不一一列举, 在 migration 脚本里逐个映射

## 5. 验收 (v0.5 阶段 1)

- [ ] Milestone / Task / OperationalException 三个 model + schema
- [ ] POST /api/v2/shipments/{id}/milestones 录入节点
- [ ] GET /api/v2/shipments/{id}/milestones 时间线
- [ ] POST /api/v2/shipments/{id}/tasks 创建待办
- [ ] GET /api/v2/shipments/{id}/tasks 待办列表
- [ ] PATCH /api/v2/tasks/{id} 标记完成
- [ ] POST /api/v2/shipments/{id}/exceptions 开异常
- [ ] GET /api/v2/shipments/{id}/exceptions 异常列表
- [ ] 派生 stage API (GET /api/v2/shipments/{id}/derived-stage)
- [ ] 自动规则: BookingRequest sent 超 24h 自动开 overdue exception
- [ ] 审计: 任何 milestone 修改留 audit log
