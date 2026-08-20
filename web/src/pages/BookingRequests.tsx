// v0.5 BookingRequests 列表页 (订舱申请版本历史)
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { v5Api, type BookingRequest } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const STATUS_LABELS: Record<string, { label: string; cls: string }> = {
  draft: { label: "草稿", cls: "bg-gray-100 text-gray-800" },
  sent: { label: "已发", cls: "bg-blue-100 text-blue-800" },
  acknowledged: { label: "对方已读", cls: "bg-purple-100 text-purple-800" },
  confirmed: { label: "已确认", cls: "bg-green-100 text-green-800" },
  rejected: { label: "已拒绝", cls: "bg-red-100 text-red-800" },
  cancelled: { label: "已取消", cls: "bg-gray-200 text-gray-500" },
};

export function BookingRequests() {
  const nav = useNavigate();
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [search, setSearch] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["booking-requests", statusFilter, search],
    queryFn: () =>
      v5Api.listBookingRequests({
        limit: 200,
        status: statusFilter === "all" ? undefined : statusFilter,
      }),
  });

  if (isLoading) return <div className="p-8 text-gray-500">加载中...</div>;
  if (error) return <div className="p-8 text-red-600">加载失败: {String(error)}</div>;

  const items: BookingRequest[] = (data ?? []).filter((br) => {
    if (!search) return true;
    const s = search.toLowerCase();
    return (
      br.booking_request_no.toLowerCase().includes(s) ||
      br.requested_pol.toLowerCase().includes(s) ||
      br.requested_pod.toLowerCase().includes(s) ||
      (br.carrier_preference ?? "").toLowerCase().includes(s)
    );
  });

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">订舱申请 ({items.length})</h1>
        <div className="flex gap-2">
          <Input
            placeholder="搜索编号/港口/船公司..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64"
          />
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              <SelectItem value="draft">草稿</SelectItem>
              <SelectItem value="sent">已发</SelectItem>
              <SelectItem value="acknowledged">对方已读</SelectItem>
              <SelectItem value="confirmed">已确认</SelectItem>
              <SelectItem value="rejected">已拒绝</SelectItem>
              <SelectItem value="cancelled">已取消</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-gray-50 text-gray-600">
                  <th className="text-left p-3">申请编号</th>
                  <th className="text-left p-3">版本</th>
                  <th className="text-left p-3">状态</th>
                  <th className="text-left p-3">路线</th>
                  <th className="text-left p-3">柜型×数</th>
                  <th className="text-left p-3">ETD</th>
                  <th className="text-left p-3">船公司</th>
                  <th className="text-left p-3">发送时间</th>
                  <th className="text-left p-3">响应时间</th>
                </tr>
              </thead>
              <tbody>
                {items.map((br) => {
                  const st = STATUS_LABELS[br.status] ?? { label: br.status, cls: "bg-gray-100" };
                  const respHrs =
                    br.sent_at && br.confirmed_at
                      ? ((new Date(br.confirmed_at).getTime() - new Date(br.sent_at).getTime()) /
                          3600000).toFixed(1) + "h"
                      : "—";
                  return (
                    <tr
                      key={br.id}
                      className="border-b hover:bg-blue-50 cursor-pointer"
                      onClick={() => nav(`/booking-requests/${br.id}`)}
                    >
                      <td className="p-3 font-mono text-xs">
                        {br.booking_request_no}
                        {br.request_version > 1 && (
                          <Badge className="ml-1 bg-orange-100 text-orange-700 text-[10px]">
                            v{br.request_version}
                          </Badge>
                        )}
                      </td>
                      <td className="p-3 text-xs">v{br.request_version}</td>
                      <td className="p-3">
                        <Badge className={st.cls}>{st.label}</Badge>
                      </td>
                      <td className="p-3 text-xs">{br.requested_pol} → {br.requested_pod}</td>
                      <td className="p-3 text-xs">
                        {br.requested_container_type} × {br.requested_container_count}
                      </td>
                      <td className="p-3 text-xs">{br.requested_etd}</td>
                      <td className="p-3 text-xs">{br.carrier_preference ?? "—"}</td>
                      <td className="p-3 text-xs">{fmtDate(br.sent_at)}</td>
                      <td className="p-3 text-xs">{respHrs}</td>
                    </tr>
                  );
                })}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={9} className="p-8 text-center text-gray-400">
                      暂无订舱申请
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
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
