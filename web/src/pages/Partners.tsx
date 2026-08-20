// v0.5 Partners 合作方列表
import { useQuery } from "@tanstack/react-query";
import { v5Api, type Partner } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const typeLabel: Record<string, string> = {
  customer: "客户",
  carrier: "船公司",
  agent_l1: "一级代理",
  agent_l2: "二级代理",
  trucking: "拖车行",
  warehouse: "仓库",
  customs_broker: "报关行",
};

export function Partners() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["partners"],
    queryFn: () => v5Api.listPartners(),
  });

  if (isLoading) return <div className="p-8">加载中...</div>;
  if (error) return <div className="p-8 text-red-600">{String(error)}</div>;

  const items: Partner[] = data ?? [];

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">合作方 ({items.length})</h1>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="p-3 text-left">类型</th>
                  <th className="p-3 text-left">名称</th>
                  <th className="p-3 text-left">简称</th>
                  <th className="p-3 text-left">联系人</th>
                  <th className="p-3 text-left">电话</th>
                  <th className="p-3 text-left">邮箱</th>
                  <th className="p-3 text-left">CC</th>
                  <th className="p-3 text-left">擅长航线</th>
                  <th className="p-3 text-left">状态</th>
                </tr>
              </thead>
              <tbody>
                {items.map((p) => (
                  <tr key={p.id} className="border-t">
                    <td className="p-3">
                      <Badge variant="secondary">{typeLabel[p.partner_type] ?? p.partner_type}</Badge>
                    </td>
                    <td className="p-3 font-medium">{p.name}</td>
                    <td className="p-3 font-mono text-xs">{p.short_code ?? "—"}</td>
                    <td className="p-3">{p.contact_person ?? "—"}</td>
                    <td className="p-3 text-xs">{p.contact_phone ?? "—"}</td>
                    <td className="p-3 text-xs">{p.primary_email ?? "—"}</td>
                    <td className="p-3 text-xs">
                      {p.cc_emails.length > 0 ? p.cc_emails.join(", ") : "—"}
                    </td>
                    <td className="p-3 text-xs">
                      {p.preferred_routes.length > 0 ? p.preferred_routes.join(", ") : "—"}
                    </td>
                    <td className="p-3">
                      <Badge className={p.is_active ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-500"}>
                        {p.is_active ? "启用" : "停用"}
                      </Badge>
                    </td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={9} className="p-8 text-center text-gray-400">
                      暂无合作方
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
