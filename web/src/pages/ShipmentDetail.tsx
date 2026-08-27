// v0.5 ShipmentDetail 业务详情 (8 业务阶段进度条 + 8 tab: 概览/节点/文件/柜/费用/日志/订舱/邮件)
import { useQuery } from "@tanstack/react-query";
import { useParams, useNavigate, Link } from "react-router-dom";
import { v5Api, type BookingRequest, type EmailThread, type OperationalException } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const PHASE_LABELS = [
  "", "建业务", "发订舱", "收/核 SO", "提柜装柜",
  "补料提单", "报关放行", "开船到港", "结案还柜",
];

const phaseColor = (idx: number, current: number, status: string) => {
  if (status === "overdue" && idx === current) return "bg-red-500 text-white";
  if (idx < current) return "bg-green-500 text-white"; // 已完成
  if (idx === current) return "bg-blue-500 text-white"; // 当前
  return "bg-gray-200 text-gray-500"; // 未开始
};

function PhaseBar({ phase, color }: { phase: number; color: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="grid grid-cols-8 gap-1">
          {PHASE_LABELS.slice(1).map((label, i) => {
            const idx = i + 1;
            const cls = phaseColor(idx, phase, color);
            return (
              <div
                key={idx}
                className={`text-center py-3 rounded text-sm font-medium ${cls}`}
              >
                {idx}. {label}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: string | null }) {
  if (!status || status === "not_started") return <span className="text-gray-400">—</span>;
  const map: Record<string, string> = {
    pending: "待申报",
    submitting: "申报中",
    released: "已放行",
    rejected: "退单",
    inspecting: "查验",
    not_received: "未收到",
    received: "已收到",
    handling: "处理中",
    completed: "已完成",
    not_happened: "未发生",
    suspected: "疑似",
    confirmed: "已确认",
    reallocated: "已改配",
    closed: "已关闭",
    not_requested: "未申请",
    requested: "已申请",
    approved: "已批准",
    paid: "已付",
    not_provided: "未提供",
    provided: "已提供",
    not_scheduled: "未预约",
    scheduled: "已预约",
    returned: "已还",
    overdue: "超期",
    abnormal: "异常",
    draft_received: "草稿已收",
    revising: "修改中",
  };
  return <Badge variant="secondary">{map[status] ?? status}</Badge>;
}

export function ShipmentDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const shipQ = useQuery({ queryKey: ["shipment", id], queryFn: () => v5Api.getShipment(id!), enabled: !!id });
  const phaseQ = useQuery({ queryKey: ["business-phase", id], queryFn: () => v5Api.getBusinessPhase(id!), enabled: !!id });
  const clQ = useQuery({ queryKey: ["doc-checklist", id], queryFn: () => v5Api.getDocumentChecklist(id!), enabled: !!id });
  const bcQ = useQuery({ queryKey: ["bcs", id], queryFn: () => v5Api.getBookingConfirmations(id!), enabled: !!id });
  const contQ = useQuery({ queryKey: ["containers", id], queryFn: () => v5Api.getContainers(id!), enabled: !!id });
  const msQ = useQuery({ queryKey: ["milestones", id], queryFn: () => v5Api.getMilestones(id!), enabled: !!id });
  const taskQ = useQuery({ queryKey: ["tasks", id], queryFn: () => v5Api.getTasks(id!), enabled: !!id });
  const auditQ = useQuery({ queryKey: ["audit", id], queryFn: () => v5Api.getAuditLogs(id!), enabled: !!id });
  // 阶段 3 第二批: 订舱申请 + 邮件 + 异常
  const brQ = useQuery<BookingRequest[]>({
    queryKey: ["shipment-booking-requests", id],
    queryFn: () => v5Api.listBookingRequests({ shipment_id: id!, limit: 50 }),
    enabled: !!id,
  });
  const etQ = useQuery<EmailThread[]>({
    queryKey: ["shipment-email-threads", id],
    queryFn: () => v5Api.listEmailThreads({ shipment_id: id!, limit: 50 }),
    enabled: !!id,
  });
  const exQ = useQuery<OperationalException[]>({
    queryKey: ["shipment-exceptions", id],
    queryFn: () => v5Api.listExceptions({ shipment_id: id!, days: 90, limit: 50 }),
    enabled: !!id,
  });

  if (shipQ.isLoading) return <div className="p-8">加载中...</div>;
  if (shipQ.error) return <div className="p-8 text-red-600">{String(shipQ.error)}</div>;
  const s = shipQ.data!;
  const phase = phaseQ.data;

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <Button variant="ghost" size="sm" onClick={() => nav("/shipments")}>← 返回</Button>
          <h1 className="text-2xl font-semibold mt-2 inline-block ml-2">
            {s.job_no} <span className="text-gray-500 text-base ml-2">{s.pol} → {s.pod}</span>
          </h1>
          <div className="text-sm text-gray-500 mt-1">
            {s.current_carrier ?? "—"} · {s.container_count} 柜 · {s.commodity} · 阶段 {s.stage}
          </div>
        </div>
        {phase && (
          <Badge className={
            phase.color === "overdue" ? "bg-red-500" :
            phase.color === "approaching_deadline" ? "bg-yellow-500" : "bg-blue-500"
          }>
            业务阶段 {phase.phase} - {phase.phase_label}
          </Badge>
        )}
      </div>

      {/* 8 业务阶段进度条 */}
      {phase && <PhaseBar phase={phase.phase} color={phase.color} />}

      {/* Tabs */}
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">概览</TabsTrigger>
          <TabsTrigger value="milestones">节点 ({msQ.data?.length ?? 0})</TabsTrigger>
          <TabsTrigger value="files">文件 ({clQ.data?.total_completed ?? 0}/{clQ.data?.total_required ?? 0})</TabsTrigger>
          <TabsTrigger value="container">柜 ({contQ.data?.length ?? 0})</TabsTrigger>
          <TabsTrigger value="booking">订舱 ({brQ.data?.length ?? 0})</TabsTrigger>
          <TabsTrigger value="emails">邮件 ({etQ.data?.length ?? 0})</TabsTrigger>
          <TabsTrigger value="exceptions">异常 ({exQ.data?.length ?? 0})</TabsTrigger>
          <TabsTrigger value="log">日志 ({auditQ.data?.length ?? 0})</TabsTrigger>
        </TabsList>

        {/* 概览 Tab */}
        <TabsContent value="overview">
          <div className="grid grid-cols-2 gap-4">
            <Card>
              <CardHeader><CardTitle>当前阶段字段</CardTitle></CardHeader>
              <CardContent className="text-sm space-y-2">
                <Row label="SO 编号" value={s.so_no ?? "—"} />
                <Row label="船公司 Booking No." value="— 待确认" />
                <Row label="当前 ETD" value={s.etd ?? "—"} />
                <Row label="当前 ETA" value={s.eta ?? "—"} />
                <Row label="SO 收到时间" value={fmtDate(s.so_received_at)} />
                <Row label="封柜时间" value={fmtDate(s.sealed_at)} />
                <Row label="CY Cut-off" value={fmtDate(s.cy_cutoff_at)} />
                <Row label="还空柜" value={fmtDate(s.empty_return_due_at)} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>操作备注</CardTitle></CardHeader>
              <CardContent className="text-sm space-y-2">
                <Row label="订舱备注" value={s.booking_remark ?? "—"} />
                <Row label="报关状态" value={<StatusBadge status={s.customs_status} />} />
                <Row label="查验状态" value={<StatusBadge status={s.inspection_status} />} />
                <Row label="甩柜状态" value={<StatusBadge status={s.rolled_status} />} />
                <Row label="请款状态" value={<StatusBadge status={s.payment_request_status} />} />
                <Row label="水单状态" value={<StatusBadge status={s.payment_proof_status} />} />
                <Row label="还空柜状态" value={<StatusBadge status={s.empty_return_status} />} />
                <Row label="提单处理" value={<StatusBadge status={s.bl_process_status} />} />
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* 节点 Tab */}
        <TabsContent value="milestones">
          <Card>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-600">
                  <tr>
                    <th className="p-3 text-left">代码</th>
                    <th className="p-3 text-left">发生时间</th>
                    <th className="p-3 text-left">船名/航次</th>
                    <th className="p-3 text-left">柜号</th>
                    <th className="p-3 text-left">地点</th>
                    <th className="p-3 text-left">来源</th>
                    <th className="p-3 text-left">备注</th>
                  </tr>
                </thead>
                <tbody>
                  {(msQ.data ?? []).map((m) => (
                    <tr key={m.id} className="border-t">
                      <td className="p-3 font-mono text-xs">{m.code}</td>
                      <td className="p-3">{fmtDate(m.occurred_at)}</td>
                      <td className="p-3">{[m.vessel_name, m.voyage_no].filter(Boolean).join(" ") || "—"}</td>
                      <td className="p-3">{m.container_no ?? "—"}</td>
                      <td className="p-3">{m.location ?? "—"}</td>
                      <td className="p-3 text-xs">{m.source}</td>
                      <td className="p-3 text-xs">{m.remark ?? "—"}</td>
                    </tr>
                  ))}
                  {(msQ.data ?? []).length === 0 && (
                    <tr><td colSpan={7} className="p-8 text-center text-gray-400">暂无节点</td></tr>
                  )}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* 文件 Tab */}
        <TabsContent value="files">
          <Card>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-600">
                  <tr>
                    <th className="p-3 text-left">文件</th>
                    <th className="p-3 text-left">要求</th>
                    <th className="p-3 text-left">状态</th>
                    <th className="p-3 text-left">进度</th>
                  </tr>
                </thead>
                <tbody>
                  {(clQ.data?.items ?? []).map((it) => (
                    <tr key={it.code} className="border-t">
                      <td className="p-3">
                        {it.label} <span className="text-xs text-gray-500">({it.code})</span>
                      </td>
                      <td className="p-3">{it.required ? "必填" : "可选"}</td>
                      <td className="p-3">
                        <Badge className={
                          it.status === "completed" ? "bg-green-100 text-green-800" :
                          it.status === "missing" ? "bg-red-100 text-red-800" :
                          it.status === "partial" ? "bg-yellow-100 text-yellow-800" :
                          "bg-gray-100 text-gray-500"
                        }>
                          {it.status}
                        </Badge>
                      </td>
                      <td className="p-3">{it.count}/{it.expected}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* 柜 Tab */}
        <TabsContent value="container">
          <Card>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-600">
                  <tr>
                    <th className="p-3 text-left">柜型</th>
                    <th className="p-3 text-left">柜号</th>
                    <th className="p-3 text-left">封条号</th>
                    <th className="p-3 text-left">提柜时间</th>
                    <th className="p-3 text-left">装船时间</th>
                    <th className="p-3 text-left">还柜时间</th>
                    <th className="p-3 text-left">状态</th>
                  </tr>
                </thead>
                <tbody>
                  {(contQ.data ?? []).map((c) => (
                    <tr key={c.id} className="border-t">
                      <td className="p-3">{c.container_type}</td>
                      <td className="p-3 font-mono">{c.container_no ?? "—"}</td>
                      <td className="p-3 font-mono">{c.seal_no ?? "—"}</td>
                      <td className="p-3">{fmtDate(c.pickup_time)}</td>
                      <td className="p-3">{fmtDate(c.loaded_time)}</td>
                      <td className="p-3">{fmtDate(c.return_time)}</td>
                      <td className="p-3"><Badge variant="outline">{c.status}</Badge></td>
                    </tr>
                  ))}
                  {(contQ.data ?? []).length === 0 && (
                    <tr><td colSpan={7} className="p-8 text-center text-gray-400">暂无柜</td></tr>
                  )}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* 订舱申请 Tab */}
        <TabsContent value="booking">
          <Card>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-600">
                  <tr>
                    <th className="p-3 text-left">编号</th>
                    <th className="p-3 text-left">版本</th>
                    <th className="p-3 text-left">状态</th>
                    <th className="p-3 text-left">请求内容</th>
                    <th className="p-3 text-left">柜型×数</th>
                    <th className="p-3 text-left">发送时间</th>
                    <th className="p-3 text-left">响应时长</th>
                  </tr>
                </thead>
                <tbody>
                  {(brQ.data ?? []).map((br) => (
                    <tr
                      key={br.id}
                      className="border-t hover:bg-blue-50 cursor-pointer"
                      onClick={() => nav(`/booking-requests/${br.id}`)}
                    >
                      <td className="p-3 font-mono text-xs">{br.booking_request_no}</td>
                      <td className="p-3 text-xs">v{br.request_version}</td>
                      <td className="p-3">
                        <Badge className={
                          br.status === "confirmed" ? "bg-green-100 text-green-800" :
                          br.status === "rejected" ? "bg-red-100 text-red-800" :
                          br.status === "sent" ? "bg-blue-100 text-blue-800" :
                          br.status === "acknowledged" ? "bg-purple-100 text-purple-800" :
                          "bg-gray-100 text-gray-800"
                        }>
                          {br.status}
                        </Badge>
                      </td>
                      <td className="p-3 text-xs">
                        {br.requested_pol}→{br.requested_pod} · ETD {br.requested_etd}
                      </td>
                      <td className="p-3 text-xs">
                        {br.requested_container_type}×{br.requested_container_count}
                      </td>
                      <td className="p-3 text-xs">{fmtDate(br.sent_at)}</td>
                      <td className="p-3 text-xs">
                        {br.sent_at && br.confirmed_at
                          ? `${((new Date(br.confirmed_at).getTime() - new Date(br.sent_at).getTime()) / 3600000).toFixed(1)}h`
                          : "—"}
                      </td>
                    </tr>
                  ))}
                  {(brQ.data ?? []).length === 0 && (
                    <tr><td colSpan={7} className="p-8 text-center text-gray-400">暂无订舱申请</td></tr>
                  )}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* 邮件 Tab */}
        <TabsContent value="emails">
          <div className="space-y-2">
            {(etQ.data ?? []).map((t) => (
              <Card
                key={t.id}
                className="cursor-pointer hover:bg-blue-50"
                onClick={() => nav(`/email-threads/${t.id}`)}
              >
                <CardContent className="p-3">
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="font-medium text-sm">{t.subject}</div>
                      <div className="text-xs text-gray-500 mt-1">
                        {t.subject_prefix && <span className="font-mono mr-2">{t.subject_prefix}</span>}
                        创建 {fmtDate(t.created_at)} · 最近活动 {fmtDate(t.updated_at)}
                      </div>
                    </div>
                    <Badge
                      className={
                        t.status === "active"
                          ? "bg-green-100 text-green-800"
                          : t.status === "closed"
                          ? "bg-gray-200 text-gray-500"
                          : "bg-red-100 text-red-800"
                      }
                    >
                      {t.status}
                    </Badge>
                  </div>
                </CardContent>
              </Card>
            ))}
            {(etQ.data ?? []).length === 0 && (
              <Card>
                <CardContent className="p-8 text-center text-gray-400">暂无邮件线程</CardContent>
              </Card>
            )}
          </div>
        </TabsContent>

        {/* 异常 Tab */}
        <TabsContent value="exceptions">
          <Card>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-600">
                  <tr>
                    <th className="p-3 text-left">代码</th>
                    <th className="p-3 text-left">严重度</th>
                    <th className="p-3 text-left">状态</th>
                    <th className="p-3 text-left">检测时间</th>
                    <th className="p-3 text-left">处理说明</th>
                  </tr>
                </thead>
                <tbody>
                  {(exQ.data ?? []).map((e) => (
                    <tr key={e.id} className="border-t">
                      <td className="p-3 font-mono text-xs">
                        <Link
                          to={`/exceptions/${e.id}`}
                          className="text-sky-600 hover:underline"
                        >
                          {e.code}
                        </Link>
                      </td>
                      <td className="p-3">
                        <Badge className={
                          e.severity === "critical" ? "bg-red-100 text-red-800" :
                          e.severity === "warning" ? "bg-yellow-100 text-yellow-800" :
                          "bg-blue-100 text-blue-800"
                        }>
                          {e.severity}
                        </Badge>
                      </td>
                      <td className="p-3">
                        <Badge className={
                          e.status === "open" ? "bg-orange-100 text-orange-800" :
                          e.status === "resolved" ? "bg-green-100 text-green-800" :
                          "bg-gray-200 text-gray-500"
                        }>
                          {e.status}
                        </Badge>
                      </td>
                      <td className="p-3 text-xs">{fmtDate(e.detected_at)}</td>
                      <td className="p-3 text-xs">{e.resolution ?? "—"}</td>
                    </tr>
                  ))}
                  {(exQ.data ?? []).length === 0 && (
                    <tr><td colSpan={5} className="p-8 text-center text-gray-400">无异常</td></tr>
                  )}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* 日志 Tab */}
        <TabsContent value="log">
          <Card>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-600">
                  <tr>
                    <th className="p-3 text-left">时间</th>
                    <th className="p-3 text-left">操作</th>
                    <th className="p-3 text-left">操作人</th>
                    <th className="p-3 text-left">原因</th>
                  </tr>
                </thead>
                <tbody>
                  {(auditQ.data ?? []).slice(0, 50).map((a) => (
                    <tr key={a.id} className="border-t">
                      <td className="p-3 text-xs">{fmtDate(a.created_at)}</td>
                      <td className="p-3 text-xs">{a.action}</td>
                      <td className="p-3 text-xs">{a.actor_user_name ?? a.actor_job_name ?? "—"}</td>
                      <td className="p-3 text-xs">{a.reason ?? "—"}</td>
                    </tr>
                  ))}
                  {(auditQ.data ?? []).length === 0 && (
                    <tr><td colSpan={4} className="p-8 text-center text-gray-400">暂无日志</td></tr>
                  )}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
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

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return s;
  }
}
