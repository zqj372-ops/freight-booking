# API 文档速查

详细 schema 见 `http://localhost:8000/docs` (Swagger UI)。

## SO 收件箱

### 上传 SO
```http
POST /api/v1/so/upload
Content-Type: multipart/form-data

file=@so.pdf
source=upload
source_email=ops@maersk.com
```

响应:
```json
{
  "id": "uuid",
  "status": "pending",
  "file_name": "so.pdf",
  ...
}
```
OCR 在后台异步执行, 数秒后 `status` 会变成 `ocr_done`。

### 列表
```http
GET /api/v1/so/?page=1&page_size=20&status=ocr_done
```

### 详情
```http
GET /api/v1/so/{id}
```

返回包含 `ocr_text`（完整原文）、`ocr_confidence`、`extra_fields` 等。

### 修正字段
```http
PATCH /api/v1/so/{id}
Content-Type: application/json

{
  "carrier": "MAERSK",
  "pol": "CNSHA",
  "pod": "USLAX",
  "container_type": "40HQ",
  "container_count": 2
}
```

### 确认 → Booking
```http
POST /api/v1/so/{id}/confirm
```

需要 `carrier / pol / pod` 必填字段都填好。

## 订舱

### 发送邮件
```http
POST /api/v1/bookings/{id}/send?template_code=booking_request
```

收件人来自 `booking.agent.booking_email`, 抄送来自 `booking.agent.cc_emails`。

## 邮件

### 预览模板
```http
POST /api/v1/emails/templates/{id}/preview
Content-Type: application/json

{
  "booking_no": "MAE-20260819-ABCD",
  "carrier": "MAERSK",
  "pol": "CNSHA",
  "pod": "USLAX"
}
```

## 状态码约定

- `200` 正常
- `201` 创建成功
- `204` 删除成功
- `400` 参数错误 / 状态机不允许
- `404` 资源不存在
- `413` 文件过大
- `500` 服务端错误
