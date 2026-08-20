// v0.5 运营驾驶舱 (4 tab: 任务 / 异常 / KPI / 迁移监控)
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { v5Api, type DashboardTaskItem, type KpiDashboard, type ExceptionSummary } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

// ============ Tab 1: 任务 (原 4 卡片) ============

function CardCount({
  title,
  count,
  hint,
  hintItems,
  bgClass,
  urgent,
}: {
  title: string;
  count: number;
  hint?: string;
  hintItems?: DashboardTaskItem[];
  bgClass: string;
  urgent?: boolean;
}) {
  return (
    <Card className={bgClass}>
      <CardContent className="p-4">
        <div className="text-sm text-gray-600">{title}</div>
        <div className={`text-4xl font-bold mt-1 ${urgent ? "text-red-600" : "text-gray-900"}`}>
          {count}
        </div>
        {hint && <div className="text-xs text-gray-500 mt-1">{hint}</div>}
        {hintItems && hintItems.length > 0 && (
          <div className="mt-3 space-y-1 text-xs">
            {hintItems.slice(0, 3).map((t) => (
              <Link
                key={t.task_id}
                to={`/shipments/${t.shipment_id}`}
                className="flex justify-between hover:bg-white/50 px-1 py-0.5 rounded"
              >
                <span className="truncate">{t.title}</span>
                <span className="text-gray-500 ml-2">
                  {t.job_no} · {fmtCountdown(t.due_at)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function TasksTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => v5Api.getDashboard(),
    refetchInterval: 30_000,
  });

  if (isLoading || !data) return <div className="p-4 text-gray-500">加载中...</div>;
  const d = data;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-4">
        <CardCount
          title="逾期任务"
          count={d.overdue_tasks}
          hint="必须先处理"
          hintItems={d.overdue_tasks_top}
          bgClass="border-l-4 border-red-400 bg-red-50"
          urgent
        />
        <CardCount
          title="今日到期"
          count={d.due_today}
          hint="按截止时间排序"
          hintItems={d.due_today_top}
          bgClass="border-l-4 border-yellow-400 bg-yellow-50"
        />
        <CardCount
          title="待 SO"
          count={d.awaiting_so}
          hint="订舱已发, 等 SO"
          bgClass="border-l-4 border-blue-400 bg-blue-50"
        />
        <CardCount
          title="7 日内到港"
          count={d.arriving_within_7d}
          hint="检查请款/电放/AN"
          bgClass="border-l-4 border-purple-400 bg-purple-50"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>颜色规则</CardTitle>
        </CardHeader>
        <CardContent className="text-sm flex flex-wrap gap-3">
          <Badge className="bg-green-100 text-green-800">绿色=完成</Badge>
          <Badge className="bg-blue-100 text-blue-800">蓝色=正常进行</Badge>
          <Badge className="bg-purple-100 text-purple-800">紫色=等待外部</Badge>
          <Badge className="bg-yellow-100 text-yellow-800">黄色=即将到期</Badge>
          <Badge className="bg-red-100 text-red-800">红色=逾期/异常</Badge>
          <Badge className="bg-gray-100 text-gray-500">灰色=不适用</Badge>
        </CardContent>
      </Card>
    </div>
  );
}

// ============ Tab 2: 异常 ============

function ExceptionsTab() {
  const [days, setDays] = useState(30);
  const summary = useQuery({
    queryKey: ["exception-summary", days],
    queryFn: () => v5Api.getExceptionSummary(days),
  });
  const openList = useQuery({
    queryKey: ["exceptions-open", days],
    queryFn: () => v5Api.listExceptions({ status: "open", days, limit: 50 }),
    refetchInterval: 30_000,
  });

  const s: ExceptionSummary | undefined = summary.data;
  if (summary.isLoading) return <div className="p-4 text-gray-500">加载中...</div>;

  return (
    <div className="space-y-4">
      {/* 总览卡片 */}
      <div className="grid grid-cols-5 gap-4">
        <StatCard label="总异常" value={s?.total_count ?? 0} hint={`最近 ${days} 天`} />
        <StatCard
          label="未解决"
          value={s?.open_count ?? 0}
          cls="text-red-600"
          hint="需立即处理"
        />
        <StatCard label="已解决" value={s?.resolved_count ?? 0} cls="text-green-600" />
        <StatCard label="自动关闭" value={s?.auto_closed_count ?? 0} cls="text-gray-500" />
        <StatCard
          label="解决率"
          value={`${((s?.resolution_rate ?? 0) * 100).toFixed(0)}%`}
          hint="resolved/total"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* by_severity */}
        <Card>
          <CardHeader><CardTitle>按严重度</CardTitle></CardHeader>
          <CardContent>
            {s && Object.keys(s.by_severity).length > 0 ? (
              <div className="space-y-2">
                {(["critical", "warning", "info"] as const).map((sev) => {
                  const cnt = s.by_severity[sev] ?? 0;
                  const max = Math.max(...Object.values(s.by_severity), 1);
                  return (
                    <div key={sev} className="flex items-center gap-2">
                      <div className="w-20 text-sm">{severityLabel(sev)}</div>
                      <div className="flex-1 bg-gray-100 rounded h-6">
                        <div
                          className={`h-6 rounded ${severityBar(sev)}`}
                          style={{ width: `${(cnt / max) * 100}%` }}
                        />
                      </div>
                      <div className="w-12 text-right font-mono">{cnt}</div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="text-gray-400 text-sm">无数据</div>
            )}
          </CardContent>
        </Card>

        {/* by_code TOP 10 */}
        <Card>
          <CardHeader><CardTitle>TOP 10 异常类型</CardTitle></CardHeader>
          <CardContent>
            {s && s.by_code.length > 0 ? (
              <div className="space-y-1 text-sm">
                {s.by_code.slice(0, 10).map((c) => (
                  <div key={c.code} className="flex justify-between border-b pb-1">
                    <span className="font-mono text-xs">{c.code}</span>
                    <span className="space-x-2">
                      <Badge className="bg-red-100 text-red-700 text-[10px]">
                        open {c.open}
                      </Badge>
                      <span className="text-gray-500">/ {c.total}</span>
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-gray-400 text-sm">无数据</div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* TOP 异常业务单 + Open 列表 */}
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader><CardTitle>TOP 10 异常业务单</CardTitle></CardHeader>
          <CardContent>
            {s && s.by_shipment_top.length > 0 ? (
              <div className="space-y-1 text-sm">
                {s.by_shipment_top.map((x) => (
                  <Link
                    key={x.shipment_id}
                    to={`/shipments/${x.shipment_id}`}
                    className="flex justify-between hover:bg-gray-50 px-2 py-1 rounded"
                  >
                    <span className="font-mono text-xs">{x.job_no}</span>
                    <Badge className="bg-red-100 text-red-700 text-[10px]">
                      {x.open_count} 个 open
                    </Badge>
                  </Link>
                ))}
              </div>
            ) : (
              <div className="text-gray-400 text-sm">无数据</div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>未解决异常列表</CardTitle>
          </CardHeader>
          <CardContent>
            {openList.data && openList.data.length > 0 ? (
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {openList.data.map((e) => (
                  <Link
                    key={e.id}
                    to={`/shipments/${e.shipment_id}`}
                    className="block border rounded p-2 hover:bg-gray-50"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs">{e.code}</span>
                      <Badge className={severityBadgeCls(e.severity)}>{e.severity}</Badge>
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                      业务单: {e.shipment_id.slice(0, 8)}… · {fmtDate(e.detected_at)}
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <div className="text-gray-400 text-sm">无未解决异常 🎉</div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ============ Tab 3: KPI ============

function KpiTab() {
  const [days, setDays] = useState(90);
  const kpi = useQuery({
    queryKey: ["kpi", days],
    queryFn: () => v5Api.getKpi(days),
  });
  const d: KpiDashboard | undefined = kpi.data;
  if (kpi.isLoading) return <div className="p-4 text-gray-500">加载中...</div>;

  return (
    <div className="space-y-4">
      {/* 总览 */}
      <div className="grid grid-cols-5 gap-4">
        <StatCard label="总业务单" value={d?.total_shipments ?? 0} hint={`最近 ${days} 天`} />
        <StatCard label="进行中" value={d?.in_progress ?? 0} cls="text-blue-600" />
        <StatCard label="已完成" value={d?.completed ?? 0} cls="text-green-600" />
        <StatCard label="已取消" value={d?.cancelled ?? 0} cls="text-gray-500" />
        <StatCard
          label="取消率"
          value={`${((d?.cancel_rate ?? 0) * 100).toFixed(1)}%`}
          hint="cancelled/total"
        />
      </div>

      {/* 录入完整度 + 响应时长 */}
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>录入完整度 (avg {((d?.completeness.avg_rate ?? 0) * 100).toFixed(0)}%)</CardTitle>
          </CardHeader>
          <CardContent>
            {d && d.completeness.fields.length > 0 ? (
              <div className="space-y-1 text-sm">
                {d.completeness.fields.map((f) => (
                  <div key={f.field} className="flex items-center gap-2">
                    <div className="w-32 truncate text-xs">{f.field}</div>
                    <div className="flex-1 bg-gray-100 rounded h-4">
                      <div
                        className={`h-4 rounded ${
                          f.rate >= 0.8
                            ? "bg-green-500"
                            : f.rate >= 0.5
                            ? "bg-yellow-500"
                            : "bg-red-500"
                        }`}
                        style={{ width: `${f.rate * 100}%` }}
                      />
                    </div>
                    <div className="w-20 text-right font-mono text-xs">
                      {f.filled}/{f.total} ({(f.rate * 100).toFixed(0)}%)
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-gray-400 text-sm">无数据</div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>订舱响应时长 (P50/P90)</CardTitle></CardHeader>
          <CardContent>
            {d && d.response_time.samples > 0 ? (
              <div className="space-y-3">
                <StatCard
                  label="样本数"
                  value={d.response_time.samples}
                  cls="text-gray-600"
                />
                <StatCard
                  label="平均时长"
                  value={
                    d.response_time.avg_hours !== null
                      ? `${d.response_time.avg_hours.toFixed(2)} 小时`
                      : "—"
                  }
                />
                <StatCard
                  label="P50"
                  value={
                    d.response_time.p50_hours !== null
                      ? `${d.response_time.p50_hours.toFixed(2)} 小时`
                      : "—"
                  }
                  cls="text-blue-600"
                />
                <StatCard
                  label="P90"
                  value={
                    d.response_time.p90_hours !== null
                      ? `${d.response_time.p90_hours.toFixed(2)} 小时`
                      : "—"
                  }
                  cls="text-orange-600"
                />
              </div>
            ) : (
              <div className="text-gray-400 text-sm">暂无已确认的订舱申请</div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* 客户 / 航线 / 船公司 TOP 10 */}
      <div className="grid grid-cols-3 gap-4">
        <TopListCard
          title="TOP 10 客户"
          items={(d?.by_customer ?? []).map((c) => ({
            label: c.customer_name,
            value: c.count,
            link: null,
          }))}
        />
        <TopListCard
          title="TOP 10 航线"
          items={(d?.by_route ?? []).map((r) => ({
            label: r.route,
            value: r.count,
            link: `/shipments?pol=${r.pol}&pod=${r.pod}`,
          }))}
        />
        <TopListCard
          title="TOP 10 船公司"
          items={(d?.by_carrier ?? []).map((c) => ({
            label: c.carrier,
            value: c.count,
            link: null,
          }))}
        />
      </div>

      {/* 月度趋势 */}
      <Card>
        <CardHeader><CardTitle>月度趋势 (最近 6 月)</CardTitle></CardHeader>
        <CardContent>
          {d && d.monthly_trend.length > 0 ? (
            <div className="space-y-1 text-sm">
              {d.monthly_trend.map((m) => {
                const max = Math.max(...d.monthly_trend.map((x) => x.count), 1);
                return (
                  <div key={m.month} className="flex items-center gap-2">
                    <div className="w-20 font-mono">{m.month}</div>
                    <div className="flex-1 bg-gray-100 rounded h-5">
                      <div
                        className="h-5 rounded bg-blue-500"
                        style={{ width: `${(m.count / max) * 100}%` }}
                      />
                    </div>
                    <div className="w-12 text-right">{m.count}</div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="text-gray-400 text-sm">无数据</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ============ Tab 4: 迁移监控 ============

function MigrationTab() {
  const m = useQuery({
    queryKey: ["migration-status"],
    queryFn: () => v5Api.getMigrationStatus(),
    refetchInterval: 60_000,
  });
  const stats = useQuery({
    queryKey: ["api-stats"],
    queryFn: () => v5Api.getApiStats(),
    refetchInterval: 60_000,
  });

  if (m.isLoading) return <div className="p-4 text-gray-500">加载中...</div>;
  const data = m.data;
  if (!data) return <div className="p-4 text-gray-400">无数据</div>;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader><CardTitle>v0.5 表行数</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            {Object.entries(data.v0_5_counts ?? {}).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span>{k}</span>
                <span className="font-mono">{String(v)}</span>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>v0.4 兼容表行数</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            {Object.entries(data.v0_4_counts ?? {}).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span>{k}</span>
                <span className="font-mono">{String(v)}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>LegacyEntityMap (按 v04 类型)</CardTitle></CardHeader>
        <CardContent>
          {data.legacy_map_by_v04_type && Object.keys(data.legacy_map_by_v04_type).length > 0 ? (
            <div className="space-y-1 text-sm">
              {Object.entries(data.legacy_map_by_v04_type).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span className="font-mono">{k}</span>
                  <span className="font-mono">{String(v)}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-gray-400 text-sm">无映射</div>
          )}
        </CardContent>
      </Card>

      {stats.data && (
        <Card>
          <CardHeader><CardTitle>API 调用统计 (前 10)</CardTitle></CardHeader>
          <CardContent className="text-sm">
            <pre className="bg-gray-50 p-3 rounded text-xs overflow-x-auto">
              {JSON.stringify(stats.data, null, 2).slice(0, 2000)}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ============ 共用子组件 ============

function StatCard({
  label,
  value,
  hint,
  cls = "text-gray-900",
}: {
  label: string;
  value: number | string;
  hint?: string;
  cls?: string;
}) {
  return (
    <Card>
      <CardContent className="p-3">
        <div className="text-xs text-gray-500">{label}</div>
        <div className={`text-2xl font-bold mt-1 ${cls}`}>{value}</div>
        {hint && <div className="text-[10px] text-gray-400 mt-0.5">{hint}</div>}
      </CardContent>
    </Card>
  );
}

function TopListCard({
  title,
  items,
}: {
  title: string;
  items: Array<{ label: string; value: number; link: string | null }>;
}) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent>
        {items.length > 0 ? (
          <div className="space-y-1 text-sm">
            {items.map((it, i) => (
              <div key={i} className="flex items-center gap-2">
                <div className="w-6 text-right text-gray-500 font-mono text-xs">{i + 1}</div>
                <div className="flex-1 truncate">
                  {it.link ? (
                    <Link to={it.link} className="text-blue-600 hover:underline">
                      {it.label}
                    </Link>
                  ) : (
                    it.label
                  )}
                </div>
                <div className="font-mono text-xs">{it.value}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-gray-400 text-sm">无数据</div>
        )}
      </CardContent>
    </Card>
  );
}

// ============ 工具函数 ============

function severityLabel(sev: string) {
  return sev === "critical" ? "紧急" : sev === "warning" ? "重要" : "一般";
}

function severityBar(sev: string) {
  return sev === "critical" ? "bg-red-500" : sev === "warning" ? "bg-yellow-500" : "bg-blue-400";
}

function severityBadgeCls(sev: string) {
  return sev === "critical"
    ? "bg-red-100 text-red-800"
    : sev === "warning"
    ? "bg-yellow-100 text-yellow-800"
    : "bg-blue-100 text-blue-800";
}

function fmtCountdown(s: string | null | undefined): string {
  if (!s) return "—";
  const ms = new Date(s).getTime() - Date.now();
  if (ms < 0) return `逾期 ${(Math.abs(ms) / 3600000).toFixed(1)}h`;
  const hours = ms / 3600000;
  if (hours < 24) return `${hours.toFixed(1)}h`;
  return `${Math.floor(hours / 24)} 天`;
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return s;
  }
}

// ============ 主组件 ============

export function OperationsDashboard() {
  const [tab, setTab] = useState("tasks");

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">运营驾驶舱</h1>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="tasks">任务</TabsTrigger>
          <TabsTrigger value="exceptions">异常</TabsTrigger>
          <TabsTrigger value="kpi">KPI</TabsTrigger>
          <TabsTrigger value="migration">迁移监控</TabsTrigger>
        </TabsList>

        <TabsContent value="tasks">
          <TasksTab />
        </TabsContent>
        <TabsContent value="exceptions">
          <ExceptionsTab />
        </TabsContent>
        <TabsContent value="kpi">
          <KpiTab />
        </TabsContent>
        <TabsContent value="migration">
          <MigrationTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
