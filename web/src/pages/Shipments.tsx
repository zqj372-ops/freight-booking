// v0.5 ShipmentList 主列表 (12 字段 + 颜色规则)
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { v5Api, type ShipmentListItem } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const phaseColorClass = (color: string) => {
  switch (color) {
    case "completed":
      return "bg-green-100 text-green-800 border-green-300";
    case "in_progress":
      return "bg-blue-100 text-blue-800 border-blue-300";
    case "waiting_external":
      return "bg-purple-100 text-purple-800 border-purple-300";
    case "approaching_deadline":
      return "bg-yellow-100 text-yellow-800 border-yellow-300";
    case "overdue":
      return "bg-red-100 text-red-800 border-red-300";
    case "not_started":
    default:
      return "bg-gray-100 text-gray-800 border-gray-300";
  }
};

const exceptionColorClass = (label: string) => {
  if (label === "紧急") return "bg-red-100 text-red-800";
  if (label === "重要") return "bg-orange-100 text-orange-800";
  if (label === "一般") return "bg-yellow-100 text-yellow-800";
  return "bg-gray-100 text-gray-500";
};

const priorityIcon = (p: string) => {
  if (p === "urgent") return "🔴";
  if (p === "important") return "🟡";
  if (p === "waiting_external") return "🟣";
  return "🔵";
};

function Countdown({ hours }: { hours: number | null }) {
  if (hours === null) return <span className="text-gray-400">—</span>;
  if (hours < 0) {
    return <span className="text-red-600 font-semibold">逾期 {Math.abs(hours).toFixed(1)}h</span>;
  }
  if (hours < 24) {
    return <span className="text-orange-600">{hours.toFixed(1)}h 后</span>;
  }
  const days = Math.floor(hours / 24);
  return <span>{days} 天后</span>;
}

export function Shipments() {
  const nav = useNavigate();
  const { data, isLoading, error } = useQuery({
    queryKey: ["shipments"],
    queryFn: () => v5Api.listShipments({ limit: 100 }),
  });

  if (isLoading) return <div className="p-8 text-gray-500">加载中...</div>;
  if (error) return <div className="p-8 text-red-600">加载失败: {String(error)}</div>;

  const items: ShipmentListItem[] = data ?? [];

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">业务单 ({items.length})</h1>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-gray-50 text-gray-600">
                  <th className="text-left p-3">业务编号</th>
                  <th className="text-left p-3">路线/柜型</th>
                  <th className="text-left p-3">船公司/代理</th>
                  <th className="text-left p-3">船名航次</th>
                  <th className="text-left p-3">ETD</th>
                  <th className="text-left p-3">ETA</th>
                  <th className="text-left p-3">阶段</th>
                  <th className="text-left p-3">下一步</th>
                  <th className="text-left p-3">倒计时</th>
                  <th className="text-left p-3">跟进人</th>
                  <th className="text-left p-3">异常</th>
                  <th className="text-left p-3">进度</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr
                    key={it.id}
                    className="border-b hover:bg-blue-50 cursor-pointer"
                    onClick={() => nav(`/shipments/${it.id}`)}
                  >
                    <td className="p-3 font-mono text-xs">{it.job_no}</td>
                    <td className="p-3">{it.route_summary}</td>
                    <td className="p-3 text-xs">{it.carrier_partner}</td>
                    <td className="p-3 text-xs">{it.vessel_voyage}</td>
                    <td className="p-3 text-xs">{it.current_etd ?? "—"}</td>
                    <td className="p-3 text-xs">{it.current_eta ?? "—"}</td>
                    <td className="p-3">
                      <Badge className={phaseColorClass(it.business_phase_color)}>
                        {it.business_phase_label} ({it.business_phase})
                      </Badge>
                    </td>
                    <td className="p-3 text-xs">
                      <span className="mr-1">{priorityIcon(it.next_action_priority)}</span>
                      {it.next_action}
                    </td>
                    <td className="p-3 text-xs">
                      <Countdown hours={it.countdown_hours} />
                    </td>
                    <td className="p-3 text-xs">{it.operator_user_name ?? "—"}</td>
                    <td className="p-3">
                      <Badge className={exceptionColorClass(it.exception_label)}>
                        {it.exception_label}
                      </Badge>
                    </td>
                    <td className="p-3 text-xs">
                      <div className="w-20 bg-gray-200 rounded h-2">
                        <div
                          className="bg-blue-500 h-2 rounded"
                          style={{ width: `${(it.progress * 100).toFixed(0)}%` }}
                        />
                      </div>
                      <div className="text-gray-500 mt-0.5">
                        {(it.progress * 100).toFixed(0)}%
                      </div>
                    </td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={12} className="p-8 text-center text-gray-400">
                      暂无业务单
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
