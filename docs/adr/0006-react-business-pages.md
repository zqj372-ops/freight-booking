# ADR-0006: React 业务页面 + 阶段 1.5 后端增强

- 状态: **ACCEPTED** (2026-08-20, Autumn 拍板)
- 作者: Mavis 起草, Autumn 设计原稿 (主列表原型 + 业务详情原型 + Excel 字段表)
- 适用范围: v0.5 阶段 1.5 (后端增强) + 阶段 3 (React 业务页面)
- 设计依据: `docs/domain/design-2026-08-20.xlsx` (3 sheet: 字段分组 / 建议新增字段 / 节点SLA + 2 个原型 PNG)

## 1. 背景

v0.5 阶段 1 (新 model + /api/v2) 完成 (commit 2762820). 后端有 24 张表 + 42 个 /api/v2 endpoint + 49/49 测试通过.

但 Autumn 在工作台主列表场景下, 发现 68 列字段全部"塞"到一个表里反而干扰操作员. 操作员不需要看全部字段, 只需要知道:

- 这是谁的业务
- 现在做到哪一步
- 下一步做什么
- 什么时候必须完成
- 有没有异常
- 谁负责处理

因此重新设计为 8 业务阶段 + 12 字段主列表 + 8 阶段进度条 + 右侧固定待办栏.

阶段 1.5 是为这些 React 页面提供后端能力, 阶段 3 是基于这些能力写 React.

## 2. 业务阶段 8 段 (替代 v0.4 单一 status enum)

```
1 建业务 → 2 发订舱 → 3 收/核 SO → 4 提柜装柜 →
5 补料提单 → 6 报关放行 → 7 开船到港 → 8 结案还柜
```

v0.5 阶段 1 用的 `ShipmentStage` 是粗粒度 9 个值 (draft / booking_in_progress / awaiting_confirmation / booked / container_operation / documentation / departed / completed / cancelled), 偏后端实现.

新设计要的是**业务阶段 8 段 + 颜色规则**:

| 阶段 | 中文 | 颜色 (UI) | 触发条件 (Milestone) |
|---|---|---|---|
| 1 建业务 | draft | 蓝 | Shipment created |
| 2 发订舱 | booking_in_progress | 蓝 | booking_request_sent |
| 3 收/核 SO | awaiting_confirmation / booked | 黄 (待 SO) | confirmation_received + (human accept) |
| 4 提柜装柜 | container_operation | 蓝 | container_picked_up |
| 5 补料提单 | documentation | 蓝 | si_submitted / bl_draft_received |
| 6 报关放行 | documentation | 蓝 (紫=等放行) | customs_released |
| 7 开船到港 | departed | 蓝 | departed → in_transit → arrived_at_pod |
| 8 结案还柜 | completed | 绿 | empty_returned |

`Shipment.current_phase` 字段 (新增): 取值为 1-8 业务阶段编号, 由 `derive_stage(milestones)` 推导 (不写回, 查询时算).

颜色规则 (UI 渲染):
- 绿色 = 已完成
- 蓝色 = 正常进行
- 紫色 = 等待外部 (SO/拖车/客户/船公司)
- 黄色 = 即将到期 (within 4h of cutoff)
- 红色 = 逾期/异常
- 灰色 = 未开始/不适用

## 3. 主列表 12 字段 (替代 68 列)

主列表只展示"业务身份 + 当前阶段 + 下一步 + 截止时间 + 异常":

| # | 字段 | 来源 | 备注 |
|---|---|---|---|
| 1 | 业务编号 (job_no) | Shipment.job_no | 系统生成, FB-YYYYMMDD-XXXX |
| 2 | 路线 / 柜型 (pol → pod / container_type × count) | Shipment | "CNSZX → CAVAN / 1×40HQ" |
| 3 | 船公司 / 代理 (current_carrier / current_partner) | Shipment | 合作方 |
| 4 | 船名航次 (vessel_name / voyage_no) | BookingConfirmation (is_current=true) | 拆分双字段, UI 合并 |
| 5 | 当前 ETD (effective_etd) | BookingConfirmation.is_current.etd | 多版本管理, 取当前版 |
| 6 | 当前 ETA (effective_eta) | BookingConfirmation.is_current.eta | 同上 |
| 7 | 当前阶段 (current_phase 1-8) | derived_stage(milestones) | 软联动 |
| 8 | 下一步动作 (next_action) | derive_next_action(shipment) | 系统推导, 不是手填 |
| 9 | 截止/倒计时 (next_due_at + countdown) | derive_countdown(shipment) | 红/黄/绿 |
| 10 | 跟进人 (operator_user_name) | Shipment.operator_user_name | |
| 11 | 异常 (exception_level) | 最高 severity 异常 | 一般/重要/紧急/— |
| 12 | 进度 (progress_pct) | derive_progress(shipment) | 0~1 浮点 |

顶部 4 卡片 (工作台):

| 卡片 | 含义 | 排序 | 默认值 |
|---|---|---|---|
| 逾期任务 | Task.due_at < now AND status=pending | 倒计时从小到大 | 数量 |
| 今日到期 | Task.due_at ∈ [now, today_end] | 倒计时从小到大 | 数量 |
| 待 SO | Shipment.booking_in_progress / awaiting_confirmation + 超 SLA | 等待时长 | 数量 |
| 7 日内到港 | Shipment.etd within 7 days AND stage=departed/in_transit | ETA 从小到大 | 数量 |

可扩展卡片: SO 待审核, 报关未放行, 3 日内截港, 待补料, 待电放, 待还空柜, 查验业务, 甩柜业务.

## 4. 业务详情页 (8 阶段进度条 + 右侧待办)

### 4.1 顶部固定区

```
FB-20260820-0001 | 深圳 → 温哥华 | 1×40HQ
COSCO · COSCO SHIPPING / 082E | 当前阶段: SO 待确认 | 跟进人: 小周 | 最近截止: 核对 SO (剩余 1 小时)
```

### 4.2 8 阶段进度条 (颜色)

横向 8 段, 每段宽度均分. 当前阶段高亮, 已完成变绿, 等待外部变紫, 即将到期变黄, 逾期变红.

### 4.3 当前阶段字段 (Summary 区, 12 字段精简版)

| 字段 | 来源 |
|---|---|
| SO 编号 | BookingConfirmation.is_current.so_no |
| 船公司 Booking No. | BookingConfirmation.is_current.carrier_booking_no |
| 船名航次 | BookingConfirmation.is_current.vessel_name / voyage_no |
| 当前 ETD | BookingConfirmation.is_current.etd |
| 当前 ETA | BookingConfirmation.is_current.eta |
| 拖车行 | Partner (partner_type=trucking) |
| SO 发车行 | Task (code=record_container_no, status=pending) 的 due_at |
| 异常等级 | OperationalException (max severity) |
| 文件 | Document list (按 doc_type) |
| 操作备注 | Shipment.remark |
| 快捷操作 | [接受 SO] [要求修改] [发送拖车行] (按 current_phase 动态显隐) |

### 4.4 后续关键节点 (按时间线展示)

| 字段 | 来源 |
|---|---|
| 计划做柜 | Shipment.target_etd / Container (planned) |
| 实际提柜 | Container.pickup_time |
| 柜号/封条 | Container.container_no / seal_no |
| 补料发送 | Task (code=submit_si) status |
| 提单核对 | Task (code=confirm_booking) status |
| 报关资料 | Task (code=handle_exception, custom) status |
| 出口放行 | OperationalException (customs status) |
| ATD/ATA | Milestone (departed/arrived_at_pod) |
| 文件齐套 | Document (按 doc_type 计算齐套度) |

### 4.5 右侧固定待办栏

滚动跟随, 永远显示:

| 优先级 | 任务 | 截止 | 状态 | 负责人 |
|---|---|---|---|---|
| 紧急 | 核对 SO 差异 | 今天 13:30 | 剩余 1 小时 | 小周 |
| 重要 | 将 SO 发拖车行 | 今天 13:30 | 未开始 | 小周 |
| 重要 | 确认客户接受新 ETD | 今天 15:00 | 等待外部 | 销售 |
| 一般 | 确认提柜安排 | 明天 10:00 | 未开始 | 拖车 |
| 风险 | ETD 延后 2 天 | — | 需确认 | 小周 |
| 风险 | SI Cut-off 距离 31 小时 | — | 正常 | 单证 |

来源: Task (priority=urgent/important/normal/risk) + OperationalException (open).

### 4.6 多 tab (详情内部)

| Tab | 内容 |
|---|---|
| 概览 | 顶部固定区 + 8 阶段进度条 + 后续关键节点 + 快捷操作 |
| 操作节点 | Milestone 时间线 (按 occurred_at 排序) |
| 文件与邮件 | Document + EmailMessage (按时间倒序) |
| 柜信息 | Container 列表 (v0.5 1 个, v0.6 N 个) |
| 费用 | Bill + Charges (v0.5 用 v0.4 模型) |
| 操作日志 | AuditLog (按 entity_type=shipment AND entity_id=sid) |

## 5. Y/N 字段全部改 enum 状态 (从 Excel "字段分组" sheet 提炼)

| 原 Y/N 字段 | 新 enum (5 状态) | 记录字段 |
|---|---|---|
| 出口报关放行 (Y/N) | 报关状态: 待申报/申报中/已放行/退单/查验 | status + released_at + released_by + file_ref + remark |
| 官方查验通知 (Y/N) | 查验: 未收到/已收到/处理中/已完成 | status + received_at + handler + notice_file |
| 甩柜 (Y/N) | 甩柜: 未发生/疑似甩柜/已确认/已改配/已关闭 | status + rolled_at + new_allocation_shipment_id + resolution |
| 已请预付款 (Y) | 请款: 未请/已请/已批/已付 | status + requested_at + approved_at + paid_at + amount |
| 已提供水单 (Y) | 水单: 未提供/已提供/已确认 | status + provided_at + file_path |
| 还空柜 (Y/N) | 还空柜: 未安排/已预约/已归还/超期/异常 | status + scheduled_at + returned_at + location + receipt_file + overdue_days |
| 打单情况 (Y/N) | 提单处理: 未开始/草稿已到/修改中/已确认/异常 | status + draft_received_at + last_modified_at + confirmed_at |

每次状态变化自动:
1. 写 audit log
2. 触发下一节点任务 (例如 还空柜 状态变 "已归还" → 关闭柜任务)
3. 关联 OperationalException (超期 → 自动开异常)

## 6. 关键时间必须由"触发事件"自动生成任务

原 Excel 68 列里很多字段是"开始时间" + "完成时间"分离. 设计上必须改成:

| 触发事件 | 生成任务 | SLA | 自动字段 |
|---|---|---|---|
| 业务单资料齐全 | 发送订舱申请 | 按操作员计划时间 | booking_request_sent_at |
| SO 收到/接受 | 将 SO 发拖车行 | 2h | so_sent_to_trucker_at |
| 计划做柜日期确定 | 确认提柜安排 | 做柜日前 1 工作日 | pickup_confirmed_at |
| 补料资料齐全 | 发送 SI/补料 | 2h | si_sent_at |
| 收到提单草稿/修改件 | 核对提单草稿 | 30min | bl_review_feedback_at (每轮) |
| 封柜完成 | 发送出口报关资料 | 2h | customs_docs_sent_at |
| 完成申报 | 确认出口放行 | CY Cut-off 前 | customs_released_at |
| 收到官方查验通知 | 处理官方查验 | 立即 (高优先级) | inspection_handled_at |
| 当前 ETD 到达 | 查询是否开船 | ETD+1 天 | departure_checked_at |
| ATD 已确认 | 取得开船提单 | ATD+2 天 | onboard_bl_received_at |
| ATD 已确认 | 取得 EMF | ATD+2 天 | emf_received_at |
| 当前 ETA 临近 | 查询到港情况 | ETA-3 天 | arrival_checked_at |
| 当前 ETA 已确认 | 发起请款/预付款 | ETA-7 天 | payment_requested_at |
| 当前 ETA 已确认 | 取得电放提单 | ETA-3 工作日 | telex_bl_received_at |
| 承运人发出 AN | 取得 Arrival Notice | 建议 ETA 前 | arrival_notice_received_at |
| 到港/拆柜计划确定 | 准备 Load Plan | 拆柜前 | load_plan_ready_at |
| 预付款获批/付款完成 | 提供水单 | 付款后立即 | payment_proof_provided_at |
| 卸货/拆柜完成 | 归还空柜 | 还柜截止前 | empty_returned_at |

完成 → 字段自动回填时间戳 → 关闭 Task (status=done) → 触发下一节点任务.

## 7. ETD/ETA 多版本管理

| 字段 | 含义 | 来源 |
|---|---|---|
| 初始要求 ETD | 客户下单时要求 | Shipment.target_etd (不变) |
| 当前 ETD | 最新 BookingConfirmation.is_current.etd | derived |
| 实际开船 ATD | Milestone.departed.occurred_at | Milestone |
| 当前 ETA | 最新 BookingConfirmation.is_current.eta | derived |
| 实际到港 ATA | Milestone.arrived_at_pod.occurred_at | Milestone |
| ETA VAN | 温哥华节点 ETA (中转业务) | 单独字段, 暂用 eta |
| ETA 最终目的地 | 二程下船后的 ETA | 单独字段, v0.6 |

改船期不覆盖原值, 而是创建新 BookingConfirmation (is_current=true), 旧版自动 is_current=false.

## 8. 18 个新增字段 (来自 Excel "建议新增字段" sheet)

| 字段 | 阶段 | 来源 | 用途 |
|---|---|---|---|
| job_no | 基础 | 系统 | FB-YYYYMMDD-XXXX 主键 |
| customer_name | 基础 | 手工/CRM | 客户 ≠ 发货人, 单独保留 |
| customer_ref | 基础 | 手工/API | 客户委托号, 搜索键 |
| carrier_booking_no | SO | SO/OCR | 船公司 Booking Number |
| booking_request_sent_at | 基础 | 自动 | 计算待回复时长 |
| so_received_at | SO | 邮件/上传 | 触发 2h 发拖车行任务 |
| si_info_ready_at | 补料 | 手工/系统 | 触发 2h 发送 SI 任务 |
| bl_draft_received_at | 提单 | 邮件 | 触发 30min 核对任务 |
| sealed_at | 装柜 | 手工/设备 | 触发 2h 报关任务 |
| cy_open_at | 船期 | SO/OCR | 提柜/进港安排 |
| si_cutoff_at | 补料 | SO/OCR | 主列表风险预警 |
| vgm_cutoff_at | 补料 | SO/OCR | 主列表风险预警 |
| cy_cutoff_at | 报关 | SO/OCR | 报关放行硬截止 |
| next_action | 全 | 推导 | 主列表下一步 |
| next_due_at | 全 | 推导 | 倒计时/超时 |
| exception_level | 全 | 系统/手工 | 一般/重要/紧急 |
| email_thread_id | 全 | 系统 | 邮件绑业务 |
| document_status | 全 | 推导 | SO/BL/EMF/电放/AN/Load Plan 齐套度 |
| empty_return_due_at | 结案 | 船公司/API | 滞箱超期风险 |
| last_updated_at | 全 | 系统 | 主列表排序 |

v0.5 阶段 1.2 已加的: customer_partner_id, customer_ref, pol, pod, etd, eta, current_partner_id, current_carrier, target_etd (合 "初始要求 ETD"), carrier_booking_no, so_no, bl_no, job_no.

需要 1.5 新增: customer_name, booking_request_sent_at, so_received_at, si_info_ready_at, bl_draft_received_at, sealed_at, cy_open_at, si_cutoff_at, vgm_cutoff_at, cy_cutoff_at, next_action, next_due_at, exception_level, email_thread_id, document_status, empty_return_due_at, last_updated_at.

部分已在 v0.5 1.2/1.3 阶段加: customer_partner_id (1.2), email_thread_id (1.3).

## 9. 备注拆分 (5 类)

原 68 列有 2 处备注. v0.5 拆为 5 类, 互不混入:

| 字段 | 用途 |
|---|---|
| booking_remark | 订舱/操作备注 (主列表可见) |
| bl_remark | 提单修改/特殊备注 |
| customs_remark | 报关/查验备注 |
| pod_remark | 目的港/清关备注 |
| finance_remark | 财务备注 |

另加 OperationalException.resolution 字段存"异常处理记录", 不混备注.

## 10. 字段清理 (废弃)

| 原字段 | 处理 |
|---|---|
| 空白 BF 列 | 删除 |
| 船名航次 (合并字段) | 拆分船名 + 航次双字段, UI 合并 |
| RMB/USD 列 | 改成"费用明细汇总" (Bill model) |
| 状态 (operator editable) | 改成"当前业务阶段" 系统推导 |
| 电放提单文件 + 电放状态 | 拆开 (Document + Task 联动) |
| 请款 + 预付款 | 改成"请款流程" 任务链 |
| 卡/UPS 末端派送 | 暂归"目的港文件"阶段, 后续按实际调整 |

## 11. 阶段 1.5 后端增强范围 (Autumn 拍板, 6 项一起干)

1. **8 业务阶段 enum + Shipment.current_phase 推导**
   - 加 `Shipment.current_phase: int` (1-8) 字段 (内存派生, 可不入库)
   - 改 `derive_stage` 支持返回 1-8 业务阶段编号 + 颜色

2. **Shipment 加 18 个触发字段 (部分) + alembic rev5**
   - 新加 11 个: customer_name, booking_request_sent_at, so_received_at, si_info_ready_at, bl_draft_received_at, sealed_at, cy_open_at, si_cutoff_at, vgm_cutoff_at, cy_cutoff_at, empty_return_due_at, last_updated_at, document_status, exception_level, next_action, next_due_at (16 个新字段, 含已有 customer_ref/pol/pod/etd/eta/carrier_booking_no 复用)
   - alembic rev5: ALTER TABLE shipments ADD COLUMN ...

3. **next_action + countdown + dashboard endpoint**
   - `GET /api/v2/shipments/{id}/next-action` 返回 {action, due_at, count_down, severity}
   - `GET /api/v2/shipments/{id}/countdown` 返回 {overdue_tasks, today_due_tasks, nearest_cutoff}
   - `GET /api/v2/dashboard` 返回 4 卡片 (逾期/今日到期/待 SO/7 日内到港)

4. **触发字段 + 17 SLA 任务 auto-trigger service**
   - `app/services/triggers.py` 注册 17 个 trigger
   - 事件 hook: booking_request sent / SO received / SI info ready / BL draft received / sealed / customs released / ATD / ETA / 等
   - 触发时: 算 SLA due_at, 自动建 Task (auto_close_on = 对应 milestone)

5. **文件齐套度 + 文档状态机**
   - `GET /api/v2/shipments/{id}/document-checklist` 返回每种 doc_type 的 {required, current, missing, latest_version, overdue}
   - 检查项: SO / BL / EMF / 电放 / AN / Load Plan / 报关资料 / SI / VGM
   - 缺失时自动开 OperationalException (severity=warning)

6. **Y/N → enum 状态机**
   - Shipment 加 6 个新 enum 字段: customs_status, inspection_status, rolled_status, payment_request_status, payment_proof_status, empty_return_status
   - 加 5 个 remark 字段 (备注拆分)
   - 8 阶段 17 SLA 任务的状态机定义

每个 sub-task 独立 commit + push + ls-remote 验证, 不合并.

## 12. 阶段 3 React 实施顺序 (3 批)

| 批 | 范围 | 前置依赖 |
|---|---|---|
| 第一批 | Shipments 主列表 + ShipmentDetail (概览/操作节点/文件与邮件/柜信息/费用/操作日志 6 tab) + Partners | 1.5 全部 |
| 第二批 | BookingConfirmationInbox + EmailThreads + OperationsDashboard (4 卡片) | 第一批 |
| 第三批 | Tasks + Containers + Bills (财务) | 第二批 |

React 一级菜单 (按用户设计):
1. 工作台 (OperationsDashboard, 4 卡片 + 5 卡片扩展)
2. 业务单 (Shipments 主列表)
3. 任务中心 (Tasks, 跨业务)
4. SO/文件收件箱 (BookingConfirmationInbox)
5. 异常中心 (OperationalExceptions)
6. 合作方 (Partners)
7. 费用与账单 (Bills)
8. 系统设置

## 13. 不在 v0.5 范围 (明确剔除)

- 客户门户/小程序
- 多邮箱路由 (v0.5 单邮箱)
- LLM 结构化抽取 OCR (v0.5 pdfplumber + regex)
- 复杂规则引擎 (v0.5 if-else)
- 全文搜索 AuditLog (v0.5 简单索引)
- 真实 JWT 鉴权 (v0.5 X-User-Id header)
- 一票多柜 (v0.5 强制 1 柜)
- 报价/价格管理 (独立 Pricing 上下文)
- 多组织切换 (v0.5 单租户, organization_id 预留)

## 14. 验收 (v0.5 阶段 1.5 + 3 完成)

- [ ] Shipment 加 11+ 新字段, alembic rev5 通过
- [ ] GET /shipments/{id}/next-action 返回正确 action + due_at
- [ ] GET /shipments/{id}/countdown 返回倒计时
- [ ] GET /dashboard 返回 4 卡片计数
- [ ] GET /shipments/{id}/document-checklist 返回 9 类文件齐套度
- [ ] 17 SLA trigger 中至少 8 个事件能自动建 Task
- [ ] 6 个 Y/N 改 enum 字段
- [ ] 5 类备注拆分
- [ ] React 主列表 12 字段渲染
- [ ] React 详情页 8 阶段进度条 + 右侧待办栏渲染
- [ ] 端到端 demo 跑通: 建单 → 发订舱 → 收 SO (自动 task) → 接受 (自动 task) → 提柜 → 装船 → 提交 SI → 开船 → 还空柜

## 15. 拍板结论 (2026-08-20, Autumn ACCEPTED)

1. **8 业务阶段**: 用 1-8 编号, 颜色规则 5 色 (绿蓝紫黄红灰), 与 ShipmentStage 9 值共存 (ShipmentStage 是后端实现, current_phase 是业务语义).
2. **主列表 12 字段**: 严格按设计, 不加列. 顶部 4 卡片可扩展.
3. **8 阶段进度条**: UI 8 段均分, 颜色映射 5 规则.
4. **右侧待办栏**: 滚动跟随, 优先级 (紧急/重要/一般/风险) + 状态 (剩余/未开始/等待/进行中/需确认) + 负责人.
5. **Y/N → enum**: 6 个状态机, 5 类备注拆分, 字段不混.
6. **触发字段**: 18 个新增字段, 17 个 SLA trigger 事件.
7. **ETD/ETA 多版本**: 不覆盖, 改船期建新 BC, is_current 切换.
8. **文件进文件中心**: Document 多版本管理, 每版本带状态/截止/上传人.
9. **1.5 范围**: 6 项一起干 (8 阶段 / 触发字段 / next-action+countdown+dashboard / 17 SLA trigger / 文件齐套 / Y/N→enum).
10. **React 顺序**: 1.5 → 3 第一批 (Shipments + ShipmentDetail + Partners) → 第二批 → 第三批.
