// v0.6 预报货量统计 列表 + 录入 + 周汇总看板
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { v6Api, type Forecast, type ForecastStatus, type ForecastSource } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const STATUS_LABELS: Record<ForecastStatus, { label: string; cls: string }> = {
  forecasted: { label: "已预报", cls: "bg-gray-100 text-gray-800" },
  confirmed: { label: "多源确认", cls: "bg-green-100 text-green-800" },
  allocated: { label: "已配载", cls: "bg-blue-100 text-blue-800" },
  loaded: { label: "已装柜", cls: "bg-purple-100 text-purple-800" },
  cancelled: { label: "已取消", cls: "bg-gray-200 text-gray-500" },
};

const SOURCE_LABELS: Record<ForecastSource, string> = {
  sales: "物友销售",
  customer_service: "客服",
  shending: "深鼎",
  subsidiary: "分子公司",
  manual: "人工补录",
};

export function Forecasts() {
  const nav = useNavigate();
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [search, setSearch] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["forecasts", statusFilter, sourceFilter],
    queryFn: () =>
      v6Api.listForecasts({
        status: statusFilter === "all" ? undefined : statusFilter,
        source: sourceFilter === "all" ? undefined : sourceFilter,
        limit: 200,
      }),
  });

  const items: Forecast[] = (data ?? []).filter((f) => {
    if (!search) return true;
    const s = search.toLowerCase();
    return (
      f.customer_name.toLowerCase().includes(s) ||
      f.pol.toLowerCase().includes(s) ||
      f.pod.toLowerCase().includes(s) ||
      (f.source_ref ?? "").toLowerCase().includes(s)
    );
  });

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">预报货量 ({items.length})</h1>
        <div className="flex gap-2">
          <Input
            placeholder="搜索客户/港口/source_ref..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64"
          />
          <Select value={sourceFilter} onValueChange={setSourceFilter}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部来源</SelectItem>
              <SelectItem value="sales">物友销售</SelectItem>
              <SelectItem value="customer_service">客服</SelectItem>
              <SelectItem value="shending">深鼎</SelectItem>
              <SelectItem value="subsidiary">分子公司</SelectItem>
              <SelectItem value="manual">人工补录</SelectItem>
            </SelectContent>
          </Select>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部</SelectItem>
              <SelectItem value="forecasted">已预报</SelectItem>
              <SelectItem value="confirmed">已确认</SelectItem>
              <SelectItem value="allocated">已配载</SelectItem>
              <SelectItem value="loaded">已装柜</SelectItem>
              <SelectItem value="cancelled">已取消</SelectItem>
            </SelectContent>
          </Select>
          <Button onClick={() => nav("/forecasts/new")}>+ 新建预报</Button>
          <Button variant="outline" onClick={() => nav("/forecasts/weekly")}>周汇总</Button>
          <Button variant="outline" onClick={() => nav("/forecasts/import")}>CSV 导入</Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-gray-50 text-gray-600">
                  <th className="text-left p-3">来源</th>
                  <th className="text-left p-3">客户</th>
                  <th className="text-left p-3">航线</th>
                  <th className="text-left p-3">柜型×数</th>
                  <th className="text-left p-3">ETD</th>
                  <th className="text-left p-3">状态</th>
                  <th className="text-left p-3">source_ref</th>
                  <th className="text-left p-3">创建</th>
                </tr>
              </thead>
              <tbody>
                {isLoading && (
                  <tr><td colSpan={8} className="p-8 text-center text-gray-400">加载中...</td></tr>
                )}
                {items.map((f) => {
                  const st = STATUS_LABELS[f.status];
                  return (
                    <tr
                      key={f.id}
                      className="border-b hover:bg-blue-50 cursor-pointer"
                      onClick={() => nav(`/forecasts/${f.id}`)}
                    >
                      <td className="p-3 text-xs">
                        <Badge variant="outline">{SOURCE_LABELS[f.source]}</Badge>
                      </td>
                      <td className="p-3">{f.customer_name}</td>
                      <td className="p-3 text-xs">{f.pol} → {f.pod}</td>
                      <td className="p-3 text-xs">{f.container_count} × {f.container_type}</td>
                      <td className="p-3 text-xs">{f.target_etd}</td>
                      <td className="p-3">
                        <Badge className={st.cls}>{st.label}</Badge>
                      </td>
                      <td className="p-3 text-xs font-mono text-gray-500">
                        {f.source_ref ?? "—"}
                      </td>
                      <td className="p-3 text-xs text-gray-500">
                        {f.created_by_user_name ?? f.created_at.split("T")[0]}
                      </td>
                    </tr>
                  );
                })}
                {items.length === 0 && !isLoading && (
                  <tr>
                    <td colSpan={8} className="p-8 text-center text-gray-400">
                      暂无预报 (可点 "+ 新建预报" 或 "CSV 导入")
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
