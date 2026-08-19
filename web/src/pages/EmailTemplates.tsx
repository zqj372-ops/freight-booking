import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export function EmailTemplates() {
  const { data, isLoading } = useQuery({ queryKey: ["templates"], queryFn: () => apiClient.listTemplates() });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">✉️ 邮件模板</h1>
        <p className="text-sm text-slate-500 mt-1">Jinja2 渲染, 用于订舱 / SO 通知 / 账单</p>
      </div>

      {isLoading ? (
        <div className="text-sm text-slate-400 py-8 text-center">加载中…</div>
      ) : (
        <div className="grid gap-3">
          {data?.map((t) => (
            <Card key={t.id}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-base">{t.name}</CardTitle>
                    <CardDescription className="mt-1">code: <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded">{t.code}</code></CardDescription>
                  </div>
                  <Badge variant={t.is_active ? "success" : "secondary"}>
                    {t.is_active ? "启用" : "停用"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-2">
                <div>
                  <div className="text-xs font-medium text-slate-500 mb-1">主题</div>
                  <div className="text-sm bg-slate-50 px-3 py-2 rounded border">{t.subject}</div>
                </div>
                <div>
                  <div className="text-xs font-medium text-slate-500 mb-1">正文</div>
                  <pre className="text-xs bg-slate-50 px-3 py-2 rounded border overflow-auto max-h-48 whitespace-pre-wrap">{t.body}</pre>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
