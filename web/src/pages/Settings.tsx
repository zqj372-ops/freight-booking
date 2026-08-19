import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { RefreshCw, Mail, Server, AlertCircle } from "lucide-react";
import { apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export function Settings() {
  const qc = useQueryClient();
  const [apiStatus, setApiStatus] = useState<{ status?: string; version?: string; error?: string }>({});

  const { data: ingestions } = useQuery({ queryKey: ["ingestions"], queryFn: () => apiClient.listIngestions() });

  const ingest = useMutation({
    mutationFn: (source: "mock" | "imap") => apiClient.ingestNow(source),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ingestions"] }),
  });

  const checkHealth = async () => {
    try {
      const h = await apiClient.health();
      setApiStatus(h);
    } catch (e) {
      setApiStatus({ error: String(e) });
    }
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">⚙️ 系统设置</h1>
        <p className="text-sm text-slate-500 mt-1">API 状态 / IMAP / OCR 引擎</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-4 w-4" /> API 状态
          </CardTitle>
          <CardDescription>FastAPI 后端连接</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <Button onClick={checkHealth} variant="outline" size="sm">
            <RefreshCw className="h-4 w-4" /> 检查连接
          </Button>
          {apiStatus.error && (
            <div className="text-sm text-rose-600 flex items-center gap-1">
              <AlertCircle className="h-4 w-4" /> {apiStatus.error}
            </div>
          )}
          {apiStatus.status === "ok" && (
            <div className="text-sm text-emerald-600">
              ✅ 在线 · 版本 v{apiStatus.version}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Mail className="h-4 w-4" /> IMAP 自动拉取
          </CardTitle>
          <CardDescription>配置邮箱服务器, 自动把 SO 邮件附件入库</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="text-xs text-slate-600 space-y-1">
            <p>在 <code className="bg-slate-100 px-1 rounded">.env</code> 配置:</p>
            <pre className="bg-slate-50 p-3 rounded border text-[11px] leading-relaxed">
{`IMAP_ENABLED=true
IMAP_HOST=imap.exmail.qq.com
IMAP_PORT=993
IMAP_USERNAME=ops@yourdomain.com
IMAP_PASSWORD=<授权码>
IMAP_USE_SSL=true
IMAP_FILTER_SUBJECT_KEYWORDS=SO,Booking,订舱,BL,提单
IMAP_POLL_INTERVAL_SECONDS=300`}
            </pre>
            <p>不配凭据 → 自动走 <code className="bg-slate-100 px-1 rounded">samples/imap/*.eml</code> mock 模式</p>
          </div>
          <div className="flex gap-2">
            <Button onClick={() => ingest.mutate("mock")} disabled={ingest.isPending} size="sm" variant="outline">
              <RefreshCw className="h-4 w-4" /> 手动拉取 (mock)
            </Button>
            <Button onClick={() => ingest.mutate("imap")} disabled={ingest.isPending} size="sm" variant="outline">
              <RefreshCw className="h-4 w-4" /> 手动拉取 (真实)
            </Button>
          </div>
          {ingest.data && (
            <div className="text-xs bg-slate-50 p-2 rounded border">
              ✅ 拉 {ingest.data.total_fetched} · 新 {ingest.data.new_count} · 跳 {ingest.data.skip_count}
              {ingest.data.error && <div className="text-rose-600">错误: {ingest.data.error}</div>}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>IMAP 拉取历史</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-1">
            {ingestions?.slice(0, 10).map((ing) => (
              <div key={ing.id} className="flex items-center justify-between text-sm p-2 rounded hover:bg-slate-50">
                <div>
                  <span className="text-slate-900 font-medium">{ing.source}</span>
                  <span className="text-slate-400 ml-2 text-xs">{formatDate(ing.started_at, true)}</span>
                </div>
                <div className="flex gap-2 text-xs">
                  <Badge variant="outline">拉 {ing.total_fetched}</Badge>
                  <Badge variant="info">新 {ing.new_count}</Badge>
                  <Badge variant="secondary">跳 {ing.skip_count}</Badge>
                  <Badge variant={ing.status === "success" ? "success" : "destructive"}>{ing.status}</Badge>
                </div>
              </div>
            ))}
            {ingestions?.length === 0 && <div className="text-sm text-slate-400">暂无</div>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>OCR 引擎</CardTitle>
          <CardDescription>PaddleOCR (中文 SOTA, Apache 2.0)</CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-slate-600">
          <p>后端默认装好, 首次跑 OCR 会下载模型 (~100MB)。</p>
          <p className="mt-2 text-xs text-slate-400">如需换其他 OCR 引擎, 改 <code>app/services/ocr_service.py</code>。</p>
        </CardContent>
      </Card>
    </div>
  );
}
