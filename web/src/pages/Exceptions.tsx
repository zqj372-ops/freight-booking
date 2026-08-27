// v0.6.1 异常中心 - 全局异常列表 + AI 跟进状态
// 路径: /exceptions
import { Link } from "react-router-dom";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { v5Api, v6ExceptionApi } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const SEVERITY_CLS: Record<string, string> = {
  info: "bg-blue-100 text-blue-700",
  warning: "bg-yellow-100 text-yellow-700",
  critical: "bg-red-100 text-red-700",
};

const STATUS_CLS: Record<string, string> = {
  open: "bg-orange-100 text-orange-700",
  resolved: "bg-green-100 text-green-700",
  auto_closed: "bg-gray-100 text-gray-700",
};

export function Exceptions() {
  const [status, setStatus] = useState<string>("open");
  const [severity, setSeverity] = useState<string>("");
  const [days, setDays] = useState(30);

  const q = useQuery({
    queryKey: ["exceptions", status, severity, days],
    queryFn: () =>
      v5Api.listExceptions({
        status: status || undefined,
        severity: severity || undefined,
        days,
        limit: 200,
      }),
    refetchInterval: 60_000,
  });

  const summaryQ = useQuery({
    queryKey: ["exception-summary", days],
    queryFn: () => v5Api.getExceptionSummary(days),
  });

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold">异常中心</h1>
        <Badge variant="secondary" className="text-[10px]">v0.6 AI 跟进</Badge>
      </div>

      {/* 摘要 */}
      {summaryQ.data && (
        <div className="grid grid-cols-4 gap-3">
          <Card>
            <CardContent className="p-3">
              <div className="text-xs text-slate-500">总异常</div>
              <div className="text-2xl font-semibold">{summaryQ.data.total_count}</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-3">
              <div className="text-xs text-slate-500">未关闭</div>
              <div className="text-2xl font-semibold text-orange-600">{summaryQ.data.open_count}</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-3">
              <div className="text-xs text-slate-500">已解决</div>
              <div className="text-2xl font-semibold text-green-600">{summaryQ.data.resolved_count}</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-3">
              <div className="text-xs text-slate-500">自动关闭</div>
              <div className="text-2xl font-semibold text-gray-600">{summaryQ.data.auto_closed_count}</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* 筛选 */}
      <Card>
        <CardContent className="p-3 flex gap-3 items-center">
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          >
            <option value="">全部状态</option>
            <option value="open">open</option>
            <option value="resolved">resolved</option>
            <option value="auto_closed">auto_closed</option>
          </select>
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          >
            <option value="">全部严重度</option>
            <option value="info">info</option>
            <option value="warning">warning</option>
            <option value="critical">critical</option>
          </select>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="border rounded px-2 py-1 text-sm"
          >
            <option value={7}>最近 7 天</option>
            <option value={30}>最近 30 天</option>
            <option value={90}>最近 90 天</option>
          </select>
          <span className="text-xs text-slate-400 ml-auto">
            {q.data?.length ?? 0} 条
          </span>
        </CardContent>
      </Card>

      {/* 列表 */}
      <Card>
        <CardContent className="p-0">
          {q.isLoading ? (
            <div className="p-8 text-center text-slate-400">加载中...</div>
          ) : !q.data || q.data.length === 0 ? (
            <div className="p-8 text-center text-slate-400">暂无异常</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="p-3 text-left">代码</th>
                  <th className="p-3 text-left">严重度</th>
                  <th className="p-3 text-left">状态</th>
                  <th className="p-3 text-left">检测时间</th>
                  <th className="p-3 text-left">操作</th>
                </tr>
              </thead>
              <tbody>
                {q.data.map((e) => (
                  <tr key={e.id} className="border-t hover:bg-slate-50">
                    <td className="p-3 font-mono text-xs">{e.code}</td>
                    <td className="p-3">
                      <Badge className={SEVERITY_CLS[e.severity]}>{e.severity}</Badge>
                    </td>
                    <td className="p-3">
                      <Badge className={STATUS_CLS[e.status]}>{e.status}</Badge>
                    </td>
                    <td className="p-3 text-xs text-slate-500">
                      {new Date(e.detected_at).toLocaleString("zh-CN")}
                    </td>
                    <td className="p-3">
                      <Link
                        to={`/exceptions/${e.id}`}
                        className="text-sky-600 hover:underline text-sm"
                      >
                        查看 timeline →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
