import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";

const STATUS_VARIANT: Record<string, "default" | "info" | "destructive" | "success" | "warning" | "secondary"> = {
  pending: "secondary",
  sent: "success",
  failed: "destructive",
  retrying: "warning",
};

export function EmailLogs() {
  const { data, isLoading } = useQuery({ queryKey: ["email-logs"], queryFn: () => apiClient.listEmailLogs({ page: 1, page_size: 100 }) });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">📜 发送历史</h1>
        <p className="text-sm text-slate-500 mt-1">最近 100 条邮件</p>
      </div>
      <Card>
        <CardHeader><CardTitle>共 {data?.length ?? 0} 条</CardTitle></CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="text-sm text-slate-400 py-8 text-center">加载中…</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>时间</TableHead>
                  <TableHead>收件人</TableHead>
                  <TableHead>主题</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>重试</TableHead>
                  <TableHead>错误</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.map((l) => (
                  <TableRow key={l.id}>
                    <TableCell className="text-xs text-slate-500 whitespace-nowrap">
                      {formatDate(l.created_at, true)}
                    </TableCell>
                    <TableCell className="text-sm font-mono">
                      {l.to_emails.join(", ")}
                    </TableCell>
                    <TableCell className="max-w-md truncate" title={l.subject}>{l.subject}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[l.status] ?? "secondary"}>{l.status}</Badge>
                    </TableCell>
                    <TableCell className="text-xs">{l.retry_count}</TableCell>
                    <TableCell className="text-xs text-rose-600 max-w-xs truncate" title={l.error ?? ""}>
                      {l.error ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
                {data?.length === 0 && (
                  <TableRow><TableCell colSpan={6} className="text-center py-8 text-slate-400">暂无</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
