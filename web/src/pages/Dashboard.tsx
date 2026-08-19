import { useQuery } from "@tanstack/react-query";
import { Inbox, Package, Receipt, Mail, RefreshCw, TrendingUp, AlertCircle, Wallet } from "lucide-react";
import { Link } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/utils";

export function Dashboard() {
  const { data: soData } = useQuery({ queryKey: ["so-list"], queryFn: () => apiClient.listSO({ page: 1, page_size: 5 }) });
  const { data: bookingsData } = useQuery({ queryKey: ["bookings-list"], queryFn: () => apiClient.listBookings({ page: 1, page_size: 5 }) });
  const { data: billsData } = useQuery({ queryKey: ["bills-list"], queryFn: () => apiClient.listBills({ page: 1, page_size: 5 }) });
  const { data: kanban } = useQuery({ queryKey: ["kanban"], queryFn: () => apiClient.getKanban() });
  const { data: finance } = useQuery({ queryKey: ["finance-dashboard"], queryFn: () => apiClient.financeDashboard() });
  const { data: ingestions, refetch: refetchIngestions } = useQuery({
    queryKey: ["ingestions"],
    queryFn: () => apiClient.listIngestions(),
  });

  const stats = [
    {
      label: "SO 待处理",
      value: soData?.total ?? 0,
      sub: `${soData?.items.filter((s) => s.status === "pending" || s.status === "ocr_done").length ?? 0} 待 OCR/修正`,
      icon: Inbox,
      href: "/so",
      color: "text-sky-600 bg-sky-50",
    },
    {
      label: "订舱总数",
      value: bookingsData?.total ?? 0,
      sub: `${bookingsData?.items.filter((b) => b.status === "draft").length ?? 0} 草稿`,
      icon: Package,
      href: "/bookings",
      color: "text-emerald-600 bg-emerald-50",
    },
    {
      label: "账单未对账",
      value: billsData?.total ?? 0,
      sub: `${billsData?.items.filter((b) => b.status === "ocr_done").length ?? 0} OCR 待确认`,
      icon: Receipt,
      href: "/bills",
      color: "text-amber-600 bg-amber-50",
    },
    {
      label: "运单跟踪",
      value: kanban?.total ?? 0,
      sub: kanban?.columns.find((c) => c.status === "in_transit")?.count
        ? `${kanban.columns.find((c) => c.status === "in_transit")?.count} 在途`
        : "查看 Kanban",
      icon: Mail,
      href: "/tracking",
      color: "text-violet-600 bg-violet-50",
    },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">工作台</h1>
          <p className="text-sm text-slate-500 mt-1">今日待办 + 关键指标 + 财务概览</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => apiClient.ingestNow().then(() => refetchIngestions())}
        >
          <RefreshCw className="h-4 w-4" /> 拉取邮件
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((s) => (
          <Link key={s.label} to={s.href}>
            <Card className="hover:shadow-md transition-shadow cursor-pointer">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-slate-600">{s.label}</CardTitle>
                <div className={`h-8 w-8 rounded-md flex items-center justify-center ${s.color}`}>
                  <s.icon className="h-4 w-4" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-semibold">{s.value}</div>
                <p className="text-xs text-slate-500 mt-1">{s.sub}</p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {/* 财务 KPI (闭环关键) */}
      {finance && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Wallet className="h-4 w-4" /> 财务概览
            </CardTitle>
            <CardDescription>应收/已收/未收 + 逾期 + 按船公司余额</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <div className="text-xs text-slate-500">应收总额</div>
                <div className="text-lg font-semibold text-slate-900">{formatMoney(finance.receivable_total, "CNY")}</div>
              </div>
              <div>
                <div className="text-xs text-slate-500">已收</div>
                <div className="text-lg font-semibold text-emerald-600 flex items-center gap-1">
                  <TrendingUp className="h-3.5 w-3.5" />
                  {formatMoney(finance.receivable_paid, "CNY")}
                </div>
              </div>
              <div>
                <div className="text-xs text-slate-500">未收</div>
                <div className="text-lg font-semibold text-amber-600">{formatMoney(finance.receivable_pending, "CNY")}</div>
              </div>
              <div>
                <div className="text-xs text-slate-500">逾期账单</div>
                <div className={`text-lg font-semibold flex items-center gap-1 ${finance.overdue_count > 0 ? "text-rose-600" : "text-slate-400"}`}>
                  {finance.overdue_count > 0 && <AlertCircle className="h-3.5 w-3.5" />}
                  {finance.overdue_count} 笔
                </div>
              </div>
            </div>
            {Object.keys(finance.by_carrier || {}).length > 0 && (
              <div className="mt-3 pt-3 border-t">
                <div className="text-xs text-slate-500 mb-1.5">按船公司未收余额 (Top 5)</div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(finance.by_carrier).map(([c, amt]) => (
                    <Badge key={c} variant="secondary" className="text-xs">
                      {c}: {formatMoney(amt, "CNY")}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>最近 SO</CardTitle>
            <CardDescription>5 条最新订舱单</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {soData?.items.slice(0, 5).map((so) => (
                <div key={so.id} className="flex items-center justify-between p-2 rounded hover:bg-slate-50">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium truncate">
                      {so.carrier || "?"} {so.so_number || "—"}
                    </div>
                    <div className="text-xs text-slate-500 truncate">
                      {so.pol} → {so.pod} · {so.container_count}×{so.container_type}
                    </div>
                  </div>
                  <Badge variant={so.status === "ocr_done" ? "info" : "secondary"}>
                    {so.status}
                  </Badge>
                </div>
              )) ?? <div className="text-sm text-slate-400">暂无</div>}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>最近账单</CardTitle>
            <CardDescription>5 条最新账单</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {billsData?.items.slice(0, 5).map((b) => (
                <div key={b.id} className="flex items-center justify-between p-2 rounded hover:bg-slate-50">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium truncate">
                      {b.bill_no} · {b.seller_name || "?"}
                    </div>
                    <div className="text-xs text-slate-500">
                      {b.total_amount} {b.currency} · {formatDate(b.issued_at)}
                    </div>
                  </div>
                  <Badge variant={b.status === "paid" ? "success" : b.status === "confirmed" ? "info" : "secondary"}>
                    {b.status}
                  </Badge>
                </div>
              )) ?? <div className="text-sm text-slate-400">暂无</div>}
            </div>
          </CardContent>
        </Card>
      </div>

      {ingestions && ingestions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>IMAP 拉取历史</CardTitle>
            <CardDescription>最近 5 次拉取会话</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-1">
              {ingestions.slice(0, 5).map((ing) => (
                <div key={ing.id} className="flex items-center justify-between text-sm p-2 rounded hover:bg-slate-50">
                  <div>
                    <span className="text-slate-900">{ing.source}</span>
                    <span className="text-slate-400 ml-2">{formatDate(ing.started_at, true)}</span>
                  </div>
                  <div className="flex gap-2 text-xs">
                    <Badge variant="outline">拉 {ing.total_fetched}</Badge>
                    <Badge variant="info">新 {ing.new_count}</Badge>
                    <Badge variant="secondary">跳 {ing.skip_count}</Badge>
                    {ing.error_count > 0 && <Badge variant="destructive">错 {ing.error_count}</Badge>}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
