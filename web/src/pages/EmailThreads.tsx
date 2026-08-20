// v0.5 EmailThreads 列表页 (邮件线程, 按 shipment 聚合)
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { v5Api, type EmailThread } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
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
  active: { label: "活跃", cls: "bg-green-100 text-green-800" },
  closed: { label: "已关闭", cls: "bg-gray-200 text-gray-500" },
  spam: { label: "垃圾", cls: "bg-red-100 text-red-800" },
};

export function EmailThreads() {
  const nav = useNavigate();
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [search, setSearch] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["email-threads", statusFilter],
    queryFn: () =>
      v5Api.listEmailThreads({
        limit: 200,
        status: statusFilter === "all" ? undefined : statusFilter,
      }),
  });

  if (isLoading) return <div className="p-8 text-gray-500">加载中...</div>;
  if (error) return <div className="p-8 text-red-600">加载失败: {String(error)}</div>;

  const items: EmailThread[] = (data ?? []).filter((t) => {
    if (!search) return true;
    const s = search.toLowerCase();
    return (
      t.subject.toLowerCase().includes(s) ||
      (t.subject_prefix ?? "").toLowerCase().includes(s)
    );
  });

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">邮件线程 ({items.length})</h1>
        <div className="flex gap-2">
          <Input
            placeholder="搜索主题..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64"
          />
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部</SelectItem>
              <SelectItem value="active">活跃</SelectItem>
              <SelectItem value="closed">已关闭</SelectItem>
              <SelectItem value="spam">垃圾</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="divide-y">
            {items.map((t) => {
              const st = STATUS_LABELS[t.status] ?? { label: t.status, cls: "bg-gray-100" };
              return (
                <div
                  key={t.id}
                  className="p-4 hover:bg-blue-50 cursor-pointer"
                  onClick={() => nav(`/email-threads/${t.id}`)}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="font-medium text-gray-900">{t.subject}</div>
                      <div className="text-xs text-gray-500 mt-1 flex items-center gap-2">
                        {t.subject_prefix && (
                          <span className="font-mono">{t.subject_prefix}</span>
                        )}
                        {t.shipment_id && (
                          <span
                            onClick={(e) => {
                              e.stopPropagation();
                              nav(`/shipments/${t.shipment_id}`);
                            }}
                            className="text-blue-600 hover:underline"
                          >
                            业务单: {t.shipment_id.slice(0, 8)}…
                          </span>
                        )}
                        <span>· 创建 {fmtDate(t.created_at)}</span>
                        <span>· 最近活动 {fmtDate(t.updated_at)}</span>
                      </div>
                    </div>
                    <Badge className={st.cls}>{st.label}</Badge>
                  </div>
                </div>
              );
            })}
            {items.length === 0 && (
              <div className="p-8 text-center text-gray-400">暂无邮件线程</div>
            )}
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
