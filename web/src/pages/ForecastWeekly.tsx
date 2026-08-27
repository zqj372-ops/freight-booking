// v0.6 预报 周汇总看板 + 截单预警
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { v6Api, type ForecastWeeklySummary } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function nextWeekStart(d: Date): string {
  const wd = d.getDay();
  const offset = wd === 0 ? -6 : 1 - wd;  // monday
  const monday = new Date(d);
  monday.setDate(d.getDate() + offset);
  const next = new Date(monday);
  next.setDate(next.getDate() + 7);
  return next.toISOString().slice(0, 10);
}

function thisWeekStart(d: Date): string {
  const wd = d.getDay();
  const offset = wd === 0 ? -6 : 1 - wd;
  const monday = new Date(d);
  monday.setDate(d.getDate() + offset);
  return monday.toISOString().slice(0, 10);
}

export function ForecastWeekly() {
  const today = new Date();
  const [weekStart, setWeekStart] = useState(thisWeekStart(today));

  const { data, isLoading } = useQuery({
    queryKey: ["forecast-weekly", weekStart],
    queryFn: () => v6Api.getWeeklySummary(weekStart, 3),
  });

  const summary: ForecastWeeklySummary | undefined = data;
  const stats = summary
    ? {
        total: summary.total_forecast_count,
        allocated: summary.total_allocated_count,
        rate: summary.total_forecast_count > 0
          ? Math.round((summary.total_allocated_count / summary.total_forecast_count) * 100)
          : 0,
        alerts: summary.cut_off_alerts.length,
      }
    : { total: 0, allocated: 0, rate: 0, alerts: 0 };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">周汇总 (货量统计)</h1>
        <div className="flex gap-2 items-center">
          <Button
            variant="outline"
            onClick={() => setWeekStart(thisWeekStart(today))}
          >
            本周
          </Button>
          <Input
            type="date"
            value={weekStart}
            onChange={(e) => setWeekStart(e.target.value)}
            className="w-36"
          />
          <Button
            variant="outline"
            onClick={() => setWeekStart(nextWeekStart(today))}
          >
            下周 →
          </Button>
        </div>
      </div>

      {/* 总览卡片 */}
      <div className="grid grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="text-sm text-gray-600">预报柜数</div>
            <div className="text-3xl font-bold text-gray-900 mt-1">{stats.total}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="text-sm text-gray-600">已配载</div>
            <div className="text-3xl font-bold text-blue-600 mt-1">{stats.allocated}</div>
            <div className="text-xs text-gray-500 mt-1">配载率 {stats.rate}%</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="text-sm text-gray-600">待配载</div>
            <div className="text-3xl font-bold text-yellow-600 mt-1">
              {stats.total - stats.allocated}
            </div>
          </CardContent>
        </Card>
        <Card className={stats.alerts > 0 ? "border-l-4 border-red-400 bg-red-50" : ""}>
          <CardContent className="p-4">
            <div className="text-sm text-gray-600">截单预警 (≤3 天)</div>
            <div className={`text-3xl font-bold mt-1 ${stats.alerts > 0 ? "text-red-600" : "text-gray-900"}`}>
              {stats.alerts}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 截单预警 */}
      {stats.alerts > 0 && (
        <Card className="border-l-4 border-red-400">
          <CardHeader>
            <CardTitle className="text-red-600">⚠ 截单预警 (CY Cut-off ≤ 3 天)</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead className="bg-red-50 text-gray-600">
                <tr>
                  <th className="text-left p-3">客户</th>
                  <th className="text-left p-3">航线</th>
                  <th className="text-left p-3">柜数</th>
                  <th className="text-left p-3">CY Cut-off</th>
                  <th className="text-left p-3">剩余天数</th>
                  <th className="text-left p-3">业务单</th>
                </tr>
              </thead>
              <tbody>
                {summary?.cut_off_alerts.map((a) => (
                  <tr key={a.forecast_id} className="border-t">
                    <td className="p-3">{a.customer_name}</td>
                    <td className="p-3 text-xs">{a.pol} → {a.pod}</td>
                    <td className="p-3">{a.container_count}</td>
                    <td className="p-3 text-xs">{a.cy_cutoff_at.slice(0, 10)}</td>
                    <td className="p-3">
                      <Badge className="bg-red-100 text-red-800">
                        {a.days_remaining} 天
                      </Badge>
                    </td>
                    <td className="p-3 text-xs">
                      <Link
                        to={`/shipments/${a.shipment_id}`}
                        className="text-blue-600 hover:underline"
                      >
                        {a.shipment_id.slice(0, 8)}…
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* 周汇总表 (按 pol/pod × customer) */}
      <Card>
        <CardHeader>
          <CardTitle>
            路线 × 客户 ({summary?.rows.length ?? 0} 行) ·
            周 {summary?.week_start} ~ {summary?.week_end}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-gray-50 text-gray-600">
                  <th className="text-left p-3">航线</th>
                  <th className="text-left p-3">客户</th>
                  <th className="text-right p-3">预报总数</th>
                  <th className="text-right p-3">已确认</th>
                  <th className="text-right p-3">已配载</th>
                  <th className="text-right p-3">待配载</th>
                  <th className="text-left p-3">来源分布</th>
                </tr>
              </thead>
              <tbody>
                {isLoading && (
                  <tr><td colSpan={7} className="p-8 text-center text-gray-400">加载中...</td></tr>
                )}
                {summary?.rows.map((r, i) => {
                  const breakdownStr = Object.entries(r.source_breakdown)
                    .map(([k, v]) => `${k}=${v}`).join(" · ");
                  return (
                    <tr key={i} className="border-b hover:bg-gray-50">
                      <td className="p-3 text-xs font-mono">{r.pol} → {r.pod}</td>
                      <td className="p-3">{r.customer_name}</td>
                      <td className="p-3 text-right font-mono">{r.total_count}</td>
                      <td className="p-3 text-right text-green-600">{r.confirmed_count}</td>
                      <td className="p-3 text-right text-blue-600">{r.allocated_count}</td>
                      <td className="p-3 text-right text-yellow-600">{r.pending_count}</td>
                      <td className="p-3 text-xs text-gray-500">{breakdownStr || "—"}</td>
                    </tr>
                  );
                })}
                {summary && summary.rows.length === 0 && (
                  <tr>
                    <td colSpan={7} className="p-8 text-center text-gray-400">
                      本周无预报
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
