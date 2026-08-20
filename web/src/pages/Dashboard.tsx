// v0.5 Dashboard 工作台 (4 卡片 + 顶部 5 行 top)
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { v5Api, type DashboardTaskItem } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

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

function fmtCountdown(s: string | null | undefined): string {
  if (!s) return "—";
  const ms = new Date(s).getTime() - Date.now();
  if (ms < 0) return `逾期 ${(Math.abs(ms) / 3600000).toFixed(1)}h`;
  const hours = ms / 3600000;
  if (hours < 24) return `${hours.toFixed(1)}h`;
  return `${Math.floor(hours / 24)} 天`;
}

export function Dashboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => v5Api.getDashboard(),
    refetchInterval: 30_000, // 30s 刷新
  });

  const migration = useQuery({
    queryKey: ["migration-status"],
    queryFn: () => v5Api.getMigrationStatus(),
  });

  if (isLoading) return <div className="p-8">加载中...</div>;
  if (error) return <div className="p-8 text-red-600">{String(error)}</div>;

  const d = data!;

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">工作台</h1>

      {/* 4 卡片 */}
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

      {/* 颜色规则提示 */}
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

      {/* v0.5 初始化监控 */}
      <Card>
        <CardHeader>
          <CardTitle>v0.5 初始化监控</CardTitle>
        </CardHeader>
        <CardContent className="text-sm">
          {migration.data ? (
            <div className="space-y-1">
              <div>
                v0.5 Shipments: <strong>{migration.data.v0_5_counts.shipments}</strong> ·
                Partners: <strong>{migration.data.v0_5_counts.partners}</strong> ·
                Documents: <strong>{migration.data.v0_5_counts.documents}</strong> ·
                Tasks: <strong>{migration.data.v0_5_counts.tasks}</strong>
              </div>
              <div>
                v0.4 Bookings: <strong>{migration.data.v0_4_counts.bookings}</strong> ·
                SOs: <strong>{migration.data.v0_4_counts.sos}</strong> ·
                Agents: <strong>{migration.data.v0_4_counts.agents}</strong>
              </div>
              <div>
                LegacyEntityMap:{" "}
                {Object.entries(migration.data.legacy_map_by_v04_type)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(" · ") || "无"}
              </div>
              <Link to="/shipments" className="text-blue-600 hover:underline text-xs mt-2 inline-block">
                查看业务单 →
              </Link>
            </div>
          ) : (
            <div>加载迁移状态...</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
