# ADR-0001: Shipment 是核心聚合根

- 状态: DRAFT (待审)
- 作者: Mavis (Mavis 起草, Autumn 拍板)
- 日期: 2026-08-20
- 适用范围: v0.5 core workflow reset

## 1. 背景

v0.4 把 SO 当主对象, 但业务现实是:

- 货代操作员每天的核心动作是 "跟进一个业务单" (从客户下单 → 开船 → 完成账单)
- 客户下单时系统没有 SO (SO 是船公司后续回复的)
- 船公司可能发多个 SO 版本 (改船期/改港/换船公司/甩柜重订)
- "booking_no" 在系统里有歧义: 系统内部编号 vs 船公司 Booking Number 混着

## 2. 决策

**以 Shipment (业务单) 作为整个系统的聚合根, 所有订舱流程的子对象都挂在 Shipment 下。**

### 2.1 业务编号体系 (拆开混用)

| 字段 | 含义 | 来源 |
|---|---|---|
| `job_no` | 系统内部唯一业务编号, 如 `FB-20260820-0001` | 系统生成 |
| `legacy_job_no` | 旧 v0.4 Booking.booking_no, 迁移保留 | v0.4 迁移 |
| `customer_ref` | 客户委托编号 | 客户/操作员录入 |
| `booking_request_no` | 系统内部订舱申请版本号, 如 `BR-001/BR-002` | 系统生成 |
| `carrier_booking_no` | 船公司/代理返回的 Booking Number | SO 提取/船公司邮件 |
| `so_no` | SO 文件上显示的号码 | SO 提取 |
| `bl_no` | 提单号 | BL 文件提取 |
| `container_no` | 柜号 | 现场录入/船公司邮件 |
| `seal_no` | 封条号 | 现场录入 |

### 2.2 Shipment 字段定义 (v0.5)

```
Shipment (聚合根):
  id              uuid
  organization_id uuid (FK)        # 多租户预留
  job_no          str unique        # FB-YYYYMMDD-XXXX
  legacy_job_no   str nullable
  customer_ref    str nullable

  # 业务阶段 (粗粒度)
  stage           enum             # 见 §2.4

  # 客户
  customer_partner_id  uuid (FK)   # Partner.type=customer
  customer_ref         str

  # 路线
  pol              str
  pod              str
  final_destination str nullable    # 最终目的地
  target_etd       date

  # 货物
  commodity        str
  hs_code          str nullable
  pieces           int
  weight_kg        float
  volume_cbm       float
  is_dangerous     bool default false
  is_oversize      bool default false

  # 柜信息 (柜是子对象, 但 v0.5 一个 Shipment 默认 1 个柜, 预留 N 个)
  container_count  int default 1

  # 订舱
  current_partner_id  uuid (FK)     # 当前在用供应商
  current_carrier      str

  # 责任
  operator_user_id  uuid (FK)
  sales_user_id     uuid nullable

  # 备注
  remark            text nullable

  # 时间
  created_at, updated_at
```

### 2.3 字段归属原则

- **业务事实字段** (pol/pod/target_etd 等): 进入 Shipment 时人工录入, 之后只能由人工或"接受 SO"操作修改
- **OCR/解析结果字段**: 进入 BookingConfirmation 下的 DocumentExtraction, 不直接污染 Shipment
- **自动推导字段** (如 current_status): 永远不存, 每次查询时由 Milestone 推导

### 2.4 Shipment 阶段 (粗粒度 enum)

```
draft                      # 草稿
booking_in_progress        # 已发订舱, 等回复
awaiting_confirmation      # 收到 SO, 人工未确认
booked                     # SO 已确认
container_operation        # 提柜/装柜阶段
documentation              # 补料/截关阶段
departed                   # 已开船
completed                  # 全部完成
cancelled                  # 取消
```

**注意**: 阶段 ≠ 状态机. 具体节点由 Milestone 表达 (见 ADR-0004).

### 2.5 Shipment 取消 vs 删除

- **取消 (cancelled)**: 软删, 保留所有数据, 但不能再添加新 BookingRequest
- **删除**: 不允许 (业务单必须留痕, 财务/审计需要)

## 3. 为什么这样设计

### 3.1 SO 不再是主对象

SO 是船公司回复的附件, 不是业务流程的起点. v0.4 的 `confirm_so() → 创建 Booking` 路径在 v0.5 删除.

新流程:

```
操作员建 Shipment (无 SO)
  ↓
发 BookingRequest
  ↓
收到邮件 + 附件 (Document)
  ↓
OCR/解析 → BookingConfirmation (候选, 未接受)
  ↓
人工: 匹配到 Shipment → 接受 → 字段写入 Shipment
```

### 3.2 一个 Shipment 多个 SO 版本

v0.4 SO.booking_id 是 FK, 表达 "SO 属于哪个 Booking". 但业务上:

- 改船期: 收第二个 SO
- 改港: 收第二个 SO
- 甩柜: 重新订舱, 收第二个 SO
- 换船公司: 第三个 SO

v0.5 改成:

```
Shipment 1 ─── N BookingConfirmation (一个 Shipment 多个 SO 版本)
                └─ is_current bool (哪个是当前有效)
                └─ supersedes_id (旧版指向新版)
```

### 3.3 不再"自动从 SO 字段回填 Shipment"

OCR 解析结果先进入 BookingConfirmation.extraction (DocumentExtraction), 字段来源标注清楚, 人工点击"接受"后才写入 Shipment. v0.4 的 `parse_so_text() → 直接 setattr(so, ...)` 这种隐式写入是 v0.4 的 bug, v0.5 不再存在.

## 4. 受影响范围

- 删除 v0.4 `Booking`, `SO` 模型 (替换为 `Shipment`, `BookingConfirmation`)
- `Bill.booking_id` → `Bill.shipment_id` (迁移)
- `TrackingEvent.booking_id` → `Milestone.shipment_id` (迁移)
- `Agent` → `Partner` (扩展 type 字段)
- 老的 `/api/v1/bookings` `/api/v1/so` 暂时只读兼容层
- 新的 `/api/v2/shipments` 是主用

## 5. 验收标准 (v0.5 阶段 1)

- [ ] Shipment model 创建, migration 通过
- [ ] Pydantic schema 完整, OpenAPI 文档生成 OK
- [ ] POST /api/v2/shipments 创建业务单
- [ ] GET /api/v2/shipments 列表 (含 stage 过滤)
- [ ] GET /api/v2/shipments/{id} 详情
- [ ] PATCH /api/v2/shipments/{id} 修改
- [ ] job_no 自动生成 (组织内唯一)
- [ ] organization_id 多租户预留 (但不实现切换)
- [ ] 阶段枚举值完整
- [ ] 字段含义有 docstring 注释

## 6. 不在本 ADR 范围

- BookingRequest / BookingConfirmation 详细设计 → ADR-0002
- Document / EmailThread 设计 → ADR-0003
- Milestone / Task / Exception → ADR-0004
- AuditLog / LegacyEntityMap → ADR-0005
- 数据迁移具体脚本 → docs/domain/migration-map.md
- React 业务页面 → 阶段 3 (等 API 稳定)

## 7. 待用户确认的问题

1. **job_no 编号规则**: `FB-YYYYMMDD-XXXX` (4位流水, 每天重置) OK 吗? 还是 `FB-YYYYMM-XXXXX` (5位流水每月重置) 或 UUID?
2. **organization_id 默认值**: 用 `default-company` 字面量? 还是用 UUID? 默认组织要不要可视化显示在 UI?
3. **container_count 默认 1**: v0.5 强制 1 个柜一个 Shipment, 数据库预留 N 柜 (子表). 是 v0.5 范围? 还是 v0.5 允许 N 柜 Shipment?
4. **stage 转换规则**: 哪些 stage 是系统自动推, 哪些必须人工改? 是不是彻底禁止自动推 stage, 全部由 Milestone 触发?
5. **删除策略**: 取消 (cancelled) 后还能再激活吗? 还是 cancelled 是终态?
6. **轮询/分支判断**: 同一业务单同一供应商, 改了 ETD, 是新增一个 BookingRequest (版本号递增) 还是修改旧的? 我倾向新增 (审计好做)
