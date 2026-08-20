# ADR-0003: Document, EmailThread, EmailMessage

- 状态: **ACCEPTED** (2026-08-20 由 Autumn 拍板)
- 日期: 2026-08-20
- 适用范围: v0.5 core workflow reset

## 1. 背景

v0.4 邮件和文件是分开的:

- `EmailLog`: 只记录发送历史 (to/cc/subject/body/status/retry)
- `SO` model: 把文件路径 + OCR 文本 + 解析字段混在一个 model 里
- 没有 inbound 邮件的概念 (IMAP 拉 SO 时, 邮件没存)

业务问题:
- 无法追踪一个 Shipment 的完整沟通历史 (入站 + 出站)
- 改船期时, 旧 SO 的"邮件往来"丢失
- 无法基于邮件主题 (job_no 嵌入) 自动匹配回复
- OCR 错误无法反馈到 OCR 模型持续训练

## 2. 决策

**邮件和文件彻底分开. EmailThread 聚合一组沟通, EmailMessage 单封邮件, Document 单一文件, DocumentExtraction 文件抽取结果.**

关系:

```
EmailThread 1 ─── N EmailMessage 1 ─── N EmailAttachment (outbound) / N Document (inbound 附件)
                    │
                    └─ references 上一封 (threading)

Document N ─── 0..1 DocumentExtraction (OCR 抽取结果)
            └── 0..1 BookingConfirmation (确认事实, 引用源文件)
```

## 3. EmailThread

聚合一组沟通, 可以关联到 Shipment / BookingRequest / 自由主题.

```
EmailThread:
  id                uuid
  organization_id   uuid (FK)
  subject           str                          # 主题 (去 [job_no] 前缀)
  subject_prefix    str nullable                 # 解析出的 [FB-20260820-0001]
  shipment_id       uuid nullable (FK)            # 关联业务单
  booking_request_id uuid nullable (FK)            # 关联订舱申请
  partner_id        uuid nullable (FK)            # 对方 (船公司/代理/客户)
  status            enum                          # active / closed / spam
  created_at, updated_at
```

## 4. EmailMessage

单封邮件, 区分 inbound / outbound.

```
EmailMessage:
  id                uuid
  organization_id   uuid (FK)
  thread_id         uuid (FK) EmailThread
  direction         enum                          # inbound / outbound

  # 邮件协议字段
  message_id        str unique                    # RFC 5322 Message-ID
  in_reply_to       str nullable
  references        text nullable                 # 多个 Message-ID 空格分隔
  from_addr         str
  to_addrs          json (list of str)
  cc_addrs          json (list of str)
  subject           str
  body_text         text nullable
  body_html         text nullable

  received_at       datetime
  sent_at           datetime nullable

  # 状态
  status            enum                          # 见 §4.1
  error             text nullable
  retry_count       int default 0

  # 来源
  source            enum                          # smtp_send / imap_poll / manual
  raw_eml_path      str nullable                  # 原始 .eml 文件路径 (IMAP)

  # 匹配
  matched_shipment_id  uuid nullable (FK)         # 自动匹配到的业务单
  matched_booking_request_id uuid nullable (FK)

  # 关联附件 (outbound 邮件, 附件是 EmailAttachment)
  # inbound 邮件, 附件是 Document

  created_at, updated_at
```

### 4.1 EmailMessage 状态

```
draft        # outbound 草稿
queued       # outbound 排队发送
sent         # outbound 已发送
failed       # outbound 失败
received     # inbound 收到
processing   # inbound 解析中 (OCR/分类/匹配)
processed    # inbound 处理完
ignored      # inbound 忽略 (如垃圾邮件)
```

## 5. EmailAttachment (出站邮件附件, 引用 Document)

出站邮件附件可以引用已有的 Document, 或者上传新文件. v0.5 简化为: 邮件附件直接是文件路径, 关联 Document (outbound 也用同一张表).

## 6. Document

文件. inbound 附件 / outbound 附件 / 手动上传 都是 Document.

```
Document:
  id                uuid
  organization_id   uuid (FK)
  shipment_id       uuid nullable (FK)            # 关联业务单 (可空, 临时)
  booking_request_id uuid nullable (FK)
  booking_confirmation_id uuid nullable (FK)     # 关联到的事实 (如果已被接受)

  # 文件信息
  filename          str
  file_path         str
  file_hash         str                           # SHA256, 去重
  mime_type         str
  file_size         int

  # 来源
  source            enum                          # imap_attachment / manual_upload / generated
  source_message_id uuid nullable (FK) EmailMessage  # inbound 邮件附件
  source_account_id uuid nullable (FK) EmailAccount   # 哪个邮箱收到的

  # 分类
  doc_type          enum                          # so / bl / invoice / si / vgm / packing_list / other
  carrier_hint      str nullable                  # 文件名/正文里识别出的船公司

  # OCR / 解析
  ocr_status        enum                          # pending / processing / done / failed
  ocr_text          text nullable
  ocr_engine        str nullable
  ocr_confidence    float nullable
  ocr_at            datetime nullable
  ocr_error         text nullable

  # 处理
  parse_status      enum                          # unmatched / matched_shipment / matched_booking / ignored
  parse_confidence  float nullable

  uploaded_by       uuid nullable
  uploaded_at       datetime

  created_at, updated_at
```

`file_hash` 唯一约束 (在 organization_id 范围内), 用于去重.

## 7. DocumentExtraction (OCR 抽取的字段结果)

OCR 抽取出的结构化字段, 与 Document 解耦. Document 可以有 0..1 个 Extraction. 一个 Extraction 一次抽取结果.

```
DocumentExtraction:
  id                uuid
  document_id       uuid (FK) Document
  extraction_method enum                          # regex / ocr / llm / manual

  # 抽取结果 (所有字段都是 nullable, 因为可能没抽到)
  fields            json                          # {field_name: {value, confidence, source_bbox}}

  # 与"已接受事实"对比
  diff              json nullable                 # {field: {extracted, expected, match, delta}}

  model_version     str nullable                  # ocr 模型版本 / llm 模型版本
  raw_response      text nullable                 # 模型原始输出 (审计)

  created_at
```

`fields` 例子:

```json
{
  "carrier": {"value": "MAERSK", "confidence": 0.98, "source_bbox": [[100,200],[300,210]]},
  "carrier_booking_no": {"value": "MAE-20260820-XYZ", "confidence": 0.92},
  "etd": {"value": "2026-09-01", "confidence": 0.85},
  "si_cutoff_at": {"value": "2026-08-25T17:00:00", "confidence": 0.78, "low_confidence_warning": true},
  ...
}
```

## 8. 邮件线程化流程

### 8.1 Outbound (发订舱申请)

```
操作员点"发送订舱申请"
  ↓
创建 BookingRequest (status=sent)
  ↓
创建 EmailThread (subject_prefix=job_no, subject="[FB-XXX] Booking Request | CNSHA-USLAX | 1×40HQ")
  ↓
创建 EmailMessage (direction=outbound, status=queued)
  ↓
调 email_service.send() (Jinja2 渲染)
  ↓
发送成功 → status=sent, 记录 sent_at + Message-ID
  ↓
入 BookingRequest.sent_at + email_message_id
```

### 8.2 Inbound (IMAP 拉 SO)

```
IMAP 拉邮件
  ↓
解析 .eml → EmailMessage (direction=inbound, status=received)
  ↓
看 In-Reply-To / References / subject_prefix 找 EmailThread
  ↓
看 job_no / customer_ref / 船公司 Booking Number 找 Shipment 候选
  ↓
自动匹配 (confidence > 0.8): 写 matched_shipment_id, status=processing
  ↓
自动匹配 (confidence 0.5~0.8): 写候选 Shipment (待人工确认), status=received
  ↓
下载附件 → Document (doc_type=so 或其他)
  ↓
OCR → DocumentExtraction
  ↓
创建 BookingConfirmation (status=unmatched 或 matched_pending)
  ↓
人工: 进入"SO 收件箱", 接受 / 拒绝 / 标记重复
```

## 9. v0.4 迁移

| v0.4 | v0.5 |
|---|---|
| `EmailLog` (outbound 发送日志) | `EmailMessage` direction=outbound, 状态映射 |
| (无) | `EmailMessage` direction=inbound (新功能) |
| (无) | `EmailThread` (新功能) |
| `SO` 文件路径/OCR 文本 | `Document.file_path` + `Document.ocr_text` + `DocumentExtraction` |
| `SO.booking_id` | `Document.shipment_id` + `BookingConfirmation.shipment_id` |

迁移脚本中:
- `EmailLog.to_emails` → `EmailMessage.to_addrs` (JSON)
- `EmailLog.body` → `EmailMessage.body_text`
- 每个 `EmailLog` 创建一个对应的 `EmailMessage` (direction=outbound) + `EmailThread`
- 每个 `SO` 创建一个 `Document` + (可选) `DocumentExtraction`

## 10. 验收 (v0.5 阶段 1)

- [ ] EmailThread / EmailMessage / Document / DocumentExtraction model + schema
- [ ] 邮件主题自动加 [job_no] 前缀
- [ ] 主题前缀解析 (split + 找 Shipment)
- [ ] IMAP 拉 SO 时走 inbound 流程
- [ ] 自动匹配 (job_no / customer_ref / 船公司 Booking Number)
- [ ] OCR 后自动创建 BookingConfirmation (status=matched_pending)
- [ ] v0.4 SO 上传兼容 (SO → Document)
- [ ] 邮件 thread UI (左侧 thread list + 右侧 messages)
- [ ] 附件下载 (Document.file_path 走 /files/)
- [ ] Document 列表 (按 Shipment)
- [ ] DocumentExtraction 字段展示 + 置信度
- [ ] 人工接受/拒绝 BookingConfirmation
- [ ] Audit log 记录所有写操作

## 11. 拍板结论 (2026-08-20, Autumn ACCEPTED)

1. **inbound 附件目录**: `uploads/attachments/inbound/{email_account_id}/{year}/{month}/{email_message_id}/{filename}`. outbound 附件: `uploads/attachments/outbound/{email_message_id}/{filename}`. 文件 hash 用 SHA256, 唯一约束 `(organization_id, file_hash)` 用于去重.
2. **DocumentExtraction 不自动重抽**: 第一次 OCR 后 fields 锁定, 如需重新抽取必须显式 POST `/api/v2/documents/{id}/re-extract` (创建新 DocumentExtraction 记录, 不覆盖). 旧 extraction 留档供审计.
3. **邮件 thread 拆分**: 同一 subject 的 inbound 邮件优先用 `In-Reply-To` / `References` 找 thread. 都没有则按 `(organization_id, subject_normalized, partner_id)` 启发式归到同一 thread, 置信度 < 0.6 的归到 "未匹配邮件" 留人工分.
4. **错配邮件**: 人工把 inbound 邮件标记为"未匹配/垃圾" → EmailMessage.status=`ignored`. 不删除原始 .eml 文件 (留作审计). 业务详情页"邮件"标签过滤 `status != ignored`.
5. **PDF/图片预览**: 静态文件经 nginx `/files/attachments/{path}` 暴露 (FastAPI 写时加 Content-Disposition: inline). 上传时检查 mime_type, 只允许 `application/pdf` / `image/jpeg` / `image/png` / `image/tiff`.
6. **OCR 三层策略**: 优先级 `可提取文本的 PDF (pdfplumber)` → `船公司模板 (regex)` → `PaddleOCR`. v0.5 不接 LLM 结构化抽取, LLM 留 v0.6 评估.
7. **匹配三信号**: 邮件 → Shipment 匹配按优先级 `Message-ID In-Reply-To 找 thread` → `subject_prefix job_no` → `(customer_ref + carrier_booking_no + carrier)` 三元组. 任一信号命中且置信度 ≥ 0.8 自动匹配; 0.5~0.8 给候选待人工确认; < 0.5 入"未匹配邮件".
