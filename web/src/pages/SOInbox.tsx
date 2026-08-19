import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, RefreshCw, FileText, Check, X } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { apiClient, type SOListItem, type SOStatus } from "@/lib/api";
import { formatDate } from "@/lib/utils";

const STATUS_LABEL: Record<SOStatus, string> = {
  pending: "待 OCR",
  ocr_done: "OCR 完成",
  ocr_failed: "OCR 失败",
  confirmed: "已确认",
  rejected: "已拒收",
};

const STATUS_VARIANT: Record<SOStatus, "default" | "info" | "destructive" | "success" | "secondary"> = {
  pending: "secondary",
  ocr_done: "info",
  ocr_failed: "destructive",
  confirmed: "success",
  rejected: "secondary",
};

export function SOInbox() {
  const qc = useQueryClient();
  const [status, setStatus] = useState<string>("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<SOListItem | null>(null);
  const [editFields, setEditFields] = useState<Record<string, string>>({});

  const { data, isLoading } = useQuery({
    queryKey: ["so-list", page, status],
    queryFn: () => apiClient.listSO({ page, page_size: 20, status: status || undefined }),
  });

  const upload = useMutation({
    mutationFn: (file: File) => apiClient.uploadSO(file, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["so-list"] }),
  });

  const reocr = useMutation({
    mutationFn: (id: string) => apiClient.reocrSO(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["so-list"] }),
  });

  const confirm = useMutation({
    mutationFn: (id: string) => apiClient.confirmSO(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["so-list"] });
      setEditing(null);
    },
  });

  const update = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Record<string, unknown> }) => apiClient.updateSO(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["so-list"] });
      setEditing(null);
    },
  });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">📥 SO 收件箱</h1>
          <p className="text-sm text-slate-500 mt-1">上传 PDF / 图片, PaddleOCR 自动识别字段</p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>上传</CardTitle>
          <CardDescription>支持 PDF / PNG / JPG / TIFF</CardDescription>
        </CardHeader>
        <CardContent>
          <label className="flex items-center justify-center w-full h-32 border-2 border-dashed rounded-md cursor-pointer hover:bg-slate-50">
            <div className="flex flex-col items-center text-slate-500">
              <Upload className="h-6 w-6 mb-2" />
              <span className="text-sm">点击或拖拽文件到此处</span>
            </div>
            <input
              type="file"
              className="hidden"
              multiple
              accept=".pdf,.png,.jpg,.jpeg,.tiff"
              onChange={(e) => {
                Array.from(e.target.files ?? []).forEach((f) => upload.mutate(f));
                e.target.value = "";
              }}
            />
          </label>
          {upload.isPending && <p className="text-xs text-slate-500 mt-2">上传中…</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>SO 列表</CardTitle>
            <CardDescription>共 {data?.total ?? 0} 条</CardDescription>
          </div>
          <div className="flex gap-2">
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
              className="h-9 rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">全部状态</option>
              <option value="pending">待 OCR</option>
              <option value="ocr_done">OCR 完成</option>
              <option value="ocr_failed">OCR 失败</option>
              <option value="confirmed">已确认</option>
            </select>
            <Button variant="outline" size="sm" onClick={() => qc.invalidateQueries({ queryKey: ["so-list"] })}>
              <RefreshCw className="h-4 w-4" /> 刷新
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="text-sm text-slate-400 py-8 text-center">加载中…</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>船公司 / 编号</TableHead>
                  <TableHead>航线</TableHead>
                  <TableHead>柜型</TableHead>
                  <TableHead>ETD</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>上传时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.items.map((so) => (
                  <TableRow key={so.id}>
                    <TableCell>
                      <div className="font-medium">{so.carrier || "?"}</div>
                      <div className="text-xs text-slate-500">{so.so_number || "—"}</div>
                    </TableCell>
                    <TableCell>
                      <div className="text-sm">{so.pol || "?"} → {so.pod || "?"}</div>
                    </TableCell>
                    <TableCell>
                      <span className="text-sm">
                        {so.container_count || 1}×{so.container_type || "40HQ"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="text-sm text-slate-600">
                        {so.etd ? formatDate(so.etd) : "—"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[so.status]}>{STATUS_LABEL[so.status]}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-slate-500">
                      {formatDate(so.created_at, true)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => {
                        setEditing(so);
                        setEditFields({
                          carrier: so.carrier ?? "",
                          so_number: so.so_number ?? "",
                          pol: so.pol ?? "",
                          pod: so.pod ?? "",
                          container_type: so.container_type ?? "40HQ",
                          container_count: String(so.container_count ?? 1),
                        });
                      }}>
                        <FileText className="h-4 w-4" /> 详情
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {data?.items.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center text-slate-400 py-8">
                      暂无数据
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>SO 详情 — {editing?.file_name}</DialogTitle>
            <DialogDescription>修正字段后保存</DialogDescription>
          </DialogHeader>
          {editing && (
            <div className="grid grid-cols-2 gap-3">
              {(["carrier", "so_number", "pol", "pod", "container_type", "container_count"] as const).map((k) => (
                <div key={k} className="space-y-1">
                  <label className="text-xs font-medium text-slate-600">{k}</label>
                  <Input
                    value={editFields[k] ?? ""}
                    onChange={(e) => setEditFields({ ...editFields, [k]: e.target.value })}
                  />
                </div>
              ))}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => reocr.mutate(editing!.id)} disabled={reocr.isPending}>
              <RefreshCw className="h-4 w-4" /> 重新 OCR
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                if (!editing) return;
                update.mutate({
                  id: editing.id,
                  data: {
                    carrier: editFields.carrier || null,
                    so_number: editFields.so_number || null,
                    pol: editFields.pol || null,
                    pod: editFields.pod || null,
                    container_type: editFields.container_type || null,
                    container_count: Number(editFields.container_count) || 1,
                  },
                });
              }}
              disabled={update.isPending}
            >
              <Check className="h-4 w-4" /> 保存
            </Button>
            <Button
              onClick={() => confirm.mutate(editing!.id)}
              disabled={confirm.isPending || !editing?.pol || !editing?.pod}
            >
              <Check className="h-4 w-4" /> 确认生成 Booking
            </Button>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              <X className="h-4 w-4" /> 关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
