// v0.6.3 头程看板
// 路径: /transit
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { v6TransitApi, type TransitOverview } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const STATUS_CLS: Record<string, string> = {
  scheduled: "bg-gray-100 text-gray-700",
  departed_in_transit: "bg-blue-100 text-blue-700",
  arrived: "bg-emerald-100 text-emerald-700",
  delayed: "bg-red-100 text-red-700",
  delivered: "bg-green-200 text-green-800",
};

const STATUS_LABEL: Record<string, string> = {
  scheduled: "已排期",
  departed_in_transit: "在途",
  arrived: "已到港",
  delayed: "延误",
  delivered: "已派送",
};

function OverviewTable({ rows }: { rows: TransitOverview[] }) {
  if (rows.length === 0) {
    return <div className="p-8 text-center text-slate-400 text-sm">无数据</div>;
  }
  return (
    <table className="w-full text-sm">
      <thead className="bg-slate-50 text-slate-600">
        <tr>
          <th className="p-3 text-left">Job No</th>
          <th className="p-3 text-left">航线</th>
          <th className="p-3 text-left">状态</th>
          <th className="p-3 text-left">ETA</th>
          <th className="p-3 text-left">距 ETA</th>
          <th className="p-3 text-left">最近变更</th>
          <th className="p-3 text-left">异常</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((o) => (
          <tr key={o.shipment_id} className="border-t hover:bg-slate-50">
            <td className="p-3">
              <Link
                to={`/shipments/${o.shipment_id}`}
                className="text-sky-600 hover:underline font-mono text-xs"
              >
                {o.job_no}
              </Link>
            </td>
            <td className="p-3 text-xs">
              {o.pol} → {o.pod}
              {o.current_carrier && (
                <span className="text-slate-400 ml-1">· {o.current_carrier}</span>
              )}
            </td>
            <td className="p-3">
              <Badge className={STATUS_CLS[o.status] || "bg-gray-100"}>
                {STATUS_LABEL[o.status] || o.status}
              </Badge>
            </td>
            <td className="p-3 text-xs">{o.eta || "—"}</td>
            <td className="p-3 text-xs">
              {o.days_to_eta == null ? "—" :
                o.days_to_eta < 0 ? (
                  <span className="text-red-600 font-medium">
                    已过 {Math.abs(o.days_to_eta)} 天
                  </span>
                ) : o.days_to_eta === 0 ? (
                  <span className="text-orange-600 font-medium">今天</span>
                ) : (
                  `${o.days_to_eta} 天`
                )
              }
            </td>
            <td className="p-3 text-xs">
              {o.latest_eta_update ? (
                <div>
                  <div>
                    {o.latest_eta_update.old_eta || "(初)"} → {o.latest_eta_update.new_eta}
                  </div>
                  <div className="text-[10px] text-slate-400">
                    {o.latest_eta_update.delta_days >= 0 ? "+" : ""}
                    {o.latest_eta_update.delta_days}d · {o.latest_eta_update.reason}
                  </div>
                </div>
              ) : "—"}
            </td>
            <td className="p-3">
              {o.open_exception_count > 0 ? (
                <Link to={`/exceptions`}>
                  <Badge className="bg-red-100 text-red-700">
                    {o.open_exception_count} 异常
                  </Badge>
                </Link>
              ) : (
                <span className="text-slate-300 text-xs">无</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function TransitBoardPage() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["transit-board"],
    queryFn: () => v6TransitApi.getBoard(),
    refetchInterval: 60_000,  // 60s 自动刷新
  });

  const checkMut = useMutation({
    mutationFn: () => v6TransitApi.checkEtaDelays(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["transit-board"] }),
  });

  if (q.isLoading) return <div className="p-8">加载中...</div>;
  if (q.isError) return <div className="p-8 text-red-600">加载失败: {String(q.error)}</div>;
  const b = q.data!;

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold">头程看板</h1>
        <Badge variant="secondary" className="text-[10px]">v0.6.3</Badge>
        <Button
          size="sm"
          variant="outline"
          onClick={() => checkMut.mutate()}
          disabled={checkMut.isPending}
          className="ml-auto"
        >
          {checkMut.isPending ? "检测中..." : "立即检测延误"}
        </Button>
        {checkMut.data && (
          <span className="text-xs text-slate-500">
            新建 {checkMut.data.new_exceptions_count} 个异常
          </span>
        )}
      </div>

      {/* 摘要 */}
      <div className="grid grid-cols-5 gap-3">
        <Card>
          <CardContent className="p-3">
            <div className="text-xs text-slate-500">总在途</div>
            <div className="text-2xl font-semibold">{b.total}</div>
          </CardContent>
        </Card>
        {Object.entries(b.by_status).map(([k, v]) => (
          <Card key={k}>
            <CardContent className="p-3">
              <div className="text-xs text-slate-500">{STATUS_LABEL[k] || k}</div>
              <div className="text-2xl font-semibold">{v}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* 延误 (优先看) */}
      <Card className="border-red-300">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-red-700">
            <span>⚠️ 延误 ({b.delayed.length})</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <OverviewTable rows={b.delayed} />
        </CardContent>
      </Card>

      {/* 临近 ETA 1 天 */}
      {b.upcoming_eta_1d.length > 0 && (
        <Card className="border-orange-300">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-orange-700">
              <span>⏰ 1 天内到港 ({b.upcoming_eta_1d.length})</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <OverviewTable rows={b.upcoming_eta_1d} />
          </CardContent>
        </Card>
      )}

      {/* 临近 ETA 7 天 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>📅 7 天内到港 ({b.upcoming_eta_7d.length})</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <OverviewTable rows={b.upcoming_eta_7d} />
        </CardContent>
      </Card>

      {/* 在途 */}
      <Card>
        <CardHeader>
          <CardTitle>在途业务单 ({b.in_transit.length})</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <OverviewTable rows={b.in_transit} />
        </CardContent>
      </Card>
    </div>
  );
}
