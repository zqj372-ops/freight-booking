// v0.6.2 清单复核详情 - 14 项核对 + 确认/签收
// 路径: /checklist-reviews/:id
import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  v6ChecklistApi,
  type ChecklistItem,
  type ChecklistItemCategory,
  type ChecklistSeverity,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const SEVERITY_CLS: Record<ChecklistSeverity, string> = {
  pass: "bg-green-100 text-green-700",
  warning: "bg-yellow-100 text-yellow-700",
  critical: "bg-red-100 text-red-700",
};

const SEVERITY_LABEL: Record<ChecklistSeverity, string> = {
  pass: "通过",
  warning: "警告",
  critical: "严重",
};

const CATEGORY_LABEL: Record<ChecklistItemCategory, string> = {
  container: "柜号/封条",
  declaration: "申报 vs 实际",
  hs_code: "HS / 危险品",
  cutoff_doc: "截关文件",
};

const STATUS_CLS: Record<string, string> = {
  draft: "bg-gray-100 text-gray-700",
  completed: "bg-blue-100 text-blue-700",
  signed_off: "bg-green-100 text-green-700",
  auto_closed: "bg-gray-200 text-gray-500",
};

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  completed: "已完成",
  signed_off: "已签收",
  auto_closed: "自动关闭",
};

function ItemRow({
  item,
  onAck,
  acking,
}: {
  item: ChecklistItem;
  onAck: (id: string) => void;
  acking: string | null;
}) {
  const isAcking = acking === item.id;
  return (
    <tr className="border-t">
      <td className="p-3">
        <Badge className={SEVERITY_CLS[item.severity]}>{SEVERITY_LABEL[item.severity]}</Badge>
      </td>
      <td className="p-3 text-sm font-mono text-xs">{item.code}</td>
      <td className="p-3 text-sm">{item.label}</td>
      <td className="p-3 text-sm">
        <div className="text-slate-500 text-xs">期望</div>
        <div>{item.expected_value || "—"}</div>
      </td>
      <td className="p-3 text-sm">
        <div className="text-slate-500 text-xs">实际</div>
        <div>{item.actual_value || "—"}</div>
        {item.delta_pct != null && (
          <div className="text-[10px] text-slate-400 mt-1">
            差 {item.delta?.toFixed(2)} ({item.delta_pct.toFixed(1)}%)
          </div>
        )}
      </td>
      <td className="p-3 text-xs">
        {item.acknowledged_at ? (
          <span className="text-emerald-600">
            ✓ 已确认
            <br />
            <span className="text-[10px] text-slate-400">
              {new Date(item.acknowledged_at).toLocaleString("zh-CN")}
            </span>
          </span>
        ) : item.severity !== "pass" ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onAck(item.id)}
            disabled={isAcking}
          >
            {isAcking ? "处理中..." : "确认"}
          </Button>
        ) : (
          <span className="text-slate-300">—</span>
        )}
      </td>
    </tr>
  );
}

export function ChecklistReviewDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [acking, setAcking] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["checklist-review", id],
    queryFn: () => v6ChecklistApi.getReview(id!),
    enabled: !!id,
  });

  const ackMut = useMutation({
    mutationFn: (item_id: string) => v6ChecklistApi.acknowledgeItem(id!, item_id, "操作员确认"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["checklist-review", id] }),
    onSettled: () => setAcking(null),
  });

  const signoffMut = useMutation({
    mutationFn: () => v6ChecklistApi.signoff(id!, "操作员签收"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["checklist-review", id] }),
  });

  if (q.isLoading) return <div className="p-8">加载中...</div>;
  if (q.isError) return <div className="p-8 text-red-600">加载失败: {String(q.error)}</div>;
  const r = q.data!;

  // 按 category 分组
  const byCategory: Record<string, ChecklistItem[]> = {};
  for (const it of r.items) {
    if (!byCategory[it.category]) byCategory[it.category] = [];
    byCategory[it.category].push(it);
  }

  return (
    <div className="p-6 space-y-4 max-w-6xl">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => nav(`/shipments/${r.shipment_id}`)}>
          ← 返回 shipment
        </Button>
        <h1 className="text-2xl font-semibold">清单复核详情</h1>
        <Badge variant="secondary" className="text-[10px]">v0.6.2</Badge>
      </div>

      {/* 汇总卡片 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 flex-wrap">
            <span>复核 #{r.id.slice(0, 8)}</span>
            <Badge className={STATUS_CLS[r.status] || "bg-gray-100"}>
              {STATUS_LABEL[r.status] || r.status}
            </Badge>
            <Badge className={SEVERITY_CLS[r.overall_severity]}>
              overall: {SEVERITY_LABEL[r.overall_severity]}
            </Badge>
            <span className="text-sm text-slate-500 ml-auto">
              {r.review_type} · {new Date(r.created_at).toLocaleString("zh-CN")}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-4 gap-3 text-sm">
            <div>
              <div className="text-slate-500 text-xs">总项数</div>
              <div className="text-2xl font-semibold">{r.total_items}</div>
            </div>
            <div>
              <div className="text-slate-500 text-xs">通过</div>
              <div className="text-2xl font-semibold text-green-600">{r.passed_items}</div>
            </div>
            <div>
              <div className="text-slate-500 text-xs">警告</div>
              <div className="text-2xl font-semibold text-yellow-600">{r.warning_items}</div>
            </div>
            <div>
              <div className="text-slate-500 text-xs">严重</div>
              <div className="text-2xl font-semibold text-red-600">{r.critical_items}</div>
            </div>
          </div>
          {r.trigger_reason && (
            <div className="mt-3 text-xs text-slate-500">
              <span className="font-medium">触发原因:</span> {r.trigger_reason}
            </div>
          )}
          {r.related_exception_ids && r.related_exception_ids.length > 0 && (
            <div className="mt-2 text-xs text-slate-500">
              <span className="font-medium text-red-600">
                已自动建 {r.related_exception_ids.length} 个异常 (v0.6.1 AI 跟进已挂上)
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 按 category 分组显示 */}
      {(Object.keys(byCategory) as ChecklistItemCategory[]).map((cat) => (
        <Card key={cat}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <span>{CATEGORY_LABEL[cat]}</span>
              <Badge variant="outline">{byCategory[cat].length} 项</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="p-3 text-left">严重度</th>
                  <th className="p-3 text-left">代码</th>
                  <th className="p-3 text-left">项</th>
                  <th className="p-3 text-left">期望</th>
                  <th className="p-3 text-left">实际</th>
                  <th className="p-3 text-left">操作</th>
                </tr>
              </thead>
              <tbody>
                {byCategory[cat].map((it) => (
                  <ItemRow
                    key={it.id}
                    item={it}
                    onAck={(iid) => {
                      setAcking(iid);
                      ackMut.mutate(iid);
                    }}
                    acking={acking}
                  />
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      ))}

      {/* 签收按钮 */}
      {r.status === "draft" && (
        <Card className="border-blue-300 bg-blue-50/30">
          <CardContent className="p-4 flex items-center gap-3">
            <div className="flex-1">
              <div className="font-medium">签收整个复核</div>
              <div className="text-xs text-slate-500">
                允许带 critical/warning 签收 (用于"已知问题, 决定发船")
              </div>
            </div>
            <Button
              onClick={() => signoffMut.mutate()}
              disabled={signoffMut.isPending}
            >
              {signoffMut.isPending ? "签收中..." : "签收"}
            </Button>
          </CardContent>
        </Card>
      )}

      {r.status === "signed_off" && (
        <Card className="border-green-300 bg-green-50/30">
          <CardContent className="p-4 text-sm">
            ✓ 已签收 · {r.reviewed_by_user_name} ·{" "}
            {r.signed_off_at && new Date(r.signed_off_at).toLocaleString("zh-CN")}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
