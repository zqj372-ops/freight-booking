// v0.5 BookingRequest 详情页
import { useQuery } from "@tanstack/react-query";
import { useParams, useNavigate, Link } from "react-router-dom";
import { v5Api, type BookingRequest } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const STATUS_LABELS: Record<string, { label: string; cls: string }> = {
  draft: { label: "草稿", cls: "bg-gray-100 text-gray-800" },
  sent: { label: "已发", cls: "bg-blue-100 text-blue-800" },
  acknowledged: { label: "对方已读", cls: "bg-purple-100 text-purple-800" },
  confirmed: { label: "已确认", cls: "bg-green-100 text-green-800" },
  rejected: { label: "已拒绝", cls: "bg-red-100 text-red-800" },
  cancelled: { label: "已取消", cls: "bg-gray-200 text-gray-500" },
};

export function BookingRequestDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const { data: br, isLoading, error } = useQuery<BookingRequest>({
    queryKey: ["booking-request", id],
    queryFn: () => v5Api.getBookingRequest(id!),
    enabled: !!id,
  });

  if (isLoading) return <div className="p-8">加载中...</div>;
  if (error) return <div className="p-8 text-red-600">{String(error)}</div>;
  if (!br) return <div className="p-8 text-gray-500">未找到</div>;

  const st = STATUS_LABELS[br.status] ?? { label: br.status, cls: "bg-gray-100" };
  const respHrs =
    br.sent_at && br.confirmed_at
      ? ((new Date(br.confirmed_at).getTime() - new Date(br.sent_at).getTime()) /
          3600000).toFixed(2) + " 小时"
      : null;

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <Button variant="ghost" size="sm" onClick={() => nav("/booking-requests")}>
            ← 返回订舱申请
          </Button>
          <h1 className="text-2xl font-semibold mt-2 inline-block ml-2">
            {br.booking_request_no}
            {br.request_version > 1 && (
              <Badge className="ml-2 bg-orange-100 text-orange-700">v{br.request_version}</Badge>
            )}
          </h1>
          <div className="text-sm text-gray-500 mt-1">
            业务单:{" "}
            <Link to={`/shipments/${br.shipment_id}`} className="text-blue-600 hover:underline">
              {br.shipment_id.slice(0, 8)}…
            </Link>
          </div>
        </div>
        <Badge className={`${st.cls} text-base px-3 py-1`}>{st.label}</Badge>
      </div>

      {/* 基本信息 + 状态时间线 */}
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader><CardTitle>请求字段</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-2">
            <Row label="申请编号" value={br.booking_request_no} />
            <Row label="版本" value={`v${br.request_version}`} />
            {br.supersedes_id && (
              <Row label="前身版本" value={
                <Link
                  to={`/booking-requests/${br.supersedes_id}`}
                  className="text-blue-600 hover:underline font-mono text-xs"
                >
                  {br.supersedes_id.slice(0, 8)}…
                </Link>
              } />
            )}
            <Row label="请求 ETD" value={br.requested_etd} />
            <Row label="路线" value={`${br.requested_pol} → ${br.requested_pod}`} />
            <Row label="柜型×数" value={`${br.requested_container_type} × ${br.requested_container_count}`} />
            <Row label="船公司偏好" value={br.carrier_preference ?? "—"} />
            <Row label="响应 SLA" value={br.response_sla_hours ? `${br.response_sla_hours} 小时` : "—"} />
            <Row label="期望回复时间" value={fmtDate(br.expected_response_by)} />
            <Row label="备注" value={br.remark ?? "—"} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>状态时间线</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-3">
            <TimelineRow label="创建" time={br.created_at} />
            <TimelineRow label="发送" time={br.sent_at} />
            <TimelineRow label="对方已读" time={br.acknowledged_at} />
            <TimelineRow label="确认" time={br.confirmed_at} />
            <TimelineRow
              label="拒绝"
              time={br.rejected_at}
              remark={br.rejection_reason}
              color="red"
            />
            <TimelineRow
              label="取消"
              time={br.cancelled_at}
              remark={br.cancellation_reason}
              color="gray"
            />
            {respHrs && (
              <div className="pt-3 border-t">
                <div className="flex justify-between">
                  <span className="text-gray-500">响应时长</span>
                  <span className="font-semibold text-green-700">{respHrs}</span>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* 关联邮件 */}
      {(br.email_thread_id || br.email_message_id) && (
        <Card>
          <CardHeader><CardTitle>关联邮件</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-2">
            {br.email_thread_id && (
              <Row
                label="邮件线程"
                value={
                  <Link
                    to={`/email-threads/${br.email_thread_id}`}
                    className="text-blue-600 hover:underline font-mono text-xs"
                  >
                    {br.email_thread_id}
                  </Link>
                }
              />
            )}
            {br.email_message_id && (
              <Row
                label="邮件消息"
                value={
                  <span className="font-mono text-xs">{br.email_message_id.slice(0, 8)}…</span>
                }
              />
            )}
          </CardContent>
        </Card>
      )}

      {/* 货物快照 */}
      {br.cargo_snapshot && Object.keys(br.cargo_snapshot).length > 0 && (
        <Card>
          <CardHeader><CardTitle>货物快照</CardTitle></CardHeader>
          <CardContent className="text-sm">
            <pre className="bg-gray-50 p-3 rounded text-xs overflow-x-auto">
              {JSON.stringify(br.cargo_snapshot, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between border-b pb-1">
      <span className="text-gray-500">{label}</span>
      <span>{value}</span>
    </div>
  );
}

function TimelineRow({
  label,
  time,
  remark,
  color,
}: {
  label: string;
  time: string | null;
  remark?: string | null;
  color?: "red" | "gray";
}) {
  return (
    <div className="flex items-start gap-2">
      <span
        className={`inline-block w-2 h-2 rounded-full mt-1.5 ${
          time
            ? color === "red"
              ? "bg-red-500"
              : color === "gray"
              ? "bg-gray-400"
              : "bg-blue-500"
            : "bg-gray-200"
        }`}
      />
      <div className="flex-1">
        <div className="flex justify-between">
          <span className={time ? "text-gray-900" : "text-gray-400"}>{label}</span>
          <span className="text-xs text-gray-500">{fmtDate(time)}</span>
        </div>
        {remark && <div className="text-xs text-gray-500 mt-0.5">{remark}</div>}
      </div>
    </div>
  );
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return s;
  }
}
