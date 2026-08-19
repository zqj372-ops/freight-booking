import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, Check, RefreshCw, X, FileText } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { apiClient, type Bill, type BillStatus } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/utils";

const STATUS_LABEL: Record<BillStatus, string> = {
  uploaded: "待 OCR",
  ocr_processing: "OCR 中",
  ocr_done: "OCR 完成",
  ocr_failed: "OCR 失败",
  confirmed: "已确认",
  disputed: "争议",
  paid: "已结清",
};

const STATUS_VARIANT: Record<BillStatus, "default" | "info" | "destructive" | "success" | "warning" | "secondary"> = {
  uploaded: "secondary",
  ocr_processing: "warning",
  ocr_done: "info",
  ocr_failed: "destructive",
  confirmed: "success",
  disputed: "warning",
  paid: "success",
};

export function Bills() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [billType, setBillType] = useState("");
  const [editing, setEditing] = useState<Bill | null>(null);
  const [editFields, setEditFields] = useState<Record<string, string>>({});

  const { data, isLoading } = useQuery({
    queryKey: ["bills-list", status, billType],
    queryFn: () => apiClient.listBills({ page: 1, page_size: 30, status: status || undefined, bill_type: billType || undefined }),
  });

  const upload = useMutation({
    mutationFn: (file: File) => apiClient.uploadBill(file, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bills-list"] }),
  });

  const reocr = useMutation({
    mutationFn: (id: string) => apiClient.reocrBill(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bills-list"] }),
  });

  const confirm = useMutation({
    mutationFn: (id: string) => apiClient.confirmBill(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bills-list"] });
      setEditing(null);
    },
  });

  const update = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Bill> }) => apiClient.updateBill(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bills-list"] });
      setEditing(null);
    },
  });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">💰 账单中心</h1>
          <p className="text-sm text-slate-500 mt-1">PaddleOCR 识别增值税发票 / 海运费 / 滞箱费</p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>上传</CardTitle>
          <CardDescription>PDF / PNG / JPG 自动 OCR 抽取字段</CardDescription>
        </CardHeader>
        <CardContent>
          <label className="flex items-center justify-center w-full h-24 border-2 border-dashed rounded-md cursor-pointer hover:bg-slate-50">
            <div className="flex items-center gap-2 text-slate-500 text-sm">
              <Upload className="h-4 w-4" />
              点击或拖拽账单文件
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
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>账单列表 · 共 {data?.total ?? 0} 条</CardTitle>
          <div className="flex gap-2">
            <Select value={billType} onValueChange={setBillType}>
              <SelectTrigger className="w-32"><SelectValue placeholder="类型" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="">全部</SelectItem>
                <SelectItem value="receivable">应收</SelectItem>
                <SelectItem value="payable">应付</SelectItem>
              </SelectContent>
            </Select>
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger className="w-36"><SelectValue placeholder="状态" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="">全部</SelectItem>
                {(Object.keys(STATUS_LABEL) as BillStatus[]).map((s) => (
                  <SelectItem key={s} value={s}>{STATUS_LABEL[s]}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" onClick={() => qc.invalidateQueries({ queryKey: ["bills-list"] })}>
              <RefreshCw className="h-4 w-4" />
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
                  <TableHead>账单号</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>购销方</TableHead>
                  <TableHead>金额</TableHead>
                  <TableHead>开票日</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.items.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell>
                      <div className="font-medium">{b.bill_no}</div>
                      <div className="text-xs text-slate-500">{b.bill_kind}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={b.bill_type === "receivable" ? "info" : "secondary"}>
                        {b.bill_type === "receivable" ? "应收" : "应付"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">
                      <div className="text-slate-900">{b.seller_name ?? "—"}</div>
                      <div className="text-xs text-slate-500">→ {b.buyer_name ?? "—"}</div>
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      {formatMoney(b.total_amount, b.currency)}
                    </TableCell>
                    <TableCell className="text-xs text-slate-500">{formatDate(b.issued_at)}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[b.status]}>{STATUS_LABEL[b.status]}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setEditing(b);
                          setEditFields({
                            bill_no: b.bill_no,
                            seller_name: b.seller_name ?? "",
                            seller_tax_no: b.seller_tax_no ?? "",
                            buyer_name: b.buyer_name ?? "",
                            buyer_tax_no: b.buyer_tax_no ?? "",
                            currency: b.currency,
                            total_amount: String(b.total_amount ?? 0),
                            tax_amount: String(b.tax_amount ?? 0),
                            amount_excl_tax: String(b.amount_excl_tax ?? 0),
                          });
                        }}
                      >
                        <FileText className="h-4 w-4" /> 详情
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {data?.items.length === 0 && (
                  <TableRow><TableCell colSpan={7} className="text-center py-8 text-slate-400">暂无</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>账单详情 — {editing?.file_name ?? "手动录入"}</DialogTitle>
          </DialogHeader>
          {editing && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1 col-span-2">
                <Label>账单号 *</Label>
                <Input value={editFields.bill_no ?? ""} onChange={(e) => setEditFields({ ...editFields, bill_no: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>销售方</Label>
                <Input value={editFields.seller_name ?? ""} onChange={(e) => setEditFields({ ...editFields, seller_name: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>销售方税号</Label>
                <Input value={editFields.seller_tax_no ?? ""} onChange={(e) => setEditFields({ ...editFields, seller_tax_no: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>购买方</Label>
                <Input value={editFields.buyer_name ?? ""} onChange={(e) => setEditFields({ ...editFields, buyer_name: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>购买方税号</Label>
                <Input value={editFields.buyer_tax_no ?? ""} onChange={(e) => setEditFields({ ...editFields, buyer_tax_no: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>币种</Label>
                <Input value={editFields.currency ?? "CNY"} onChange={(e) => setEditFields({ ...editFields, currency: e.target.value })} />
              </div>
              <div className="space-y-1" />
              <div className="space-y-1">
                <Label>价税合计</Label>
                <Input type="number" step={0.01} value={editFields.total_amount ?? "0"} onChange={(e) => setEditFields({ ...editFields, total_amount: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>税额</Label>
                <Input type="number" step={0.01} value={editFields.tax_amount ?? "0"} onChange={(e) => setEditFields({ ...editFields, tax_amount: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>不含税</Label>
                <Input type="number" step={0.01} value={editFields.amount_excl_tax ?? "0"} onChange={(e) => setEditFields({ ...editFields, amount_excl_tax: e.target.value })} />
              </div>
              {editing.line_items?.length > 0 && (
                <div className="col-span-2">
                  <Label className="mb-1 block">明细行 ({editing.line_items.length})</Label>
                  <pre className="text-xs bg-slate-50 p-2 rounded overflow-auto max-h-40">
                    {JSON.stringify(editing.line_items, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => editing && reocr.mutate(editing.id)} disabled={reocr.isPending}>
              <RefreshCw className="h-4 w-4" /> 重新 OCR
            </Button>
            <Button
              variant="outline"
              onClick={() => editing && update.mutate({
                id: editing.id,
                data: {
                  bill_no: editFields.bill_no,
                  seller_name: editFields.seller_name || null,
                  seller_tax_no: editFields.seller_tax_no || null,
                  buyer_name: editFields.buyer_name || null,
                  buyer_tax_no: editFields.buyer_tax_no || null,
                  currency: editFields.currency,
                  total_amount: Number(editFields.total_amount) || null,
                  tax_amount: Number(editFields.tax_amount) || null,
                  amount_excl_tax: Number(editFields.amount_excl_tax) || null,
                },
              })}
              disabled={update.isPending}
            >
              💾 保存
            </Button>
            <Button onClick={() => editing && confirm.mutate(editing.id)} disabled={confirm.isPending}>
              <Check className="h-4 w-4" /> 确认入账
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
