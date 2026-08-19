import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger } from "@/components/ui/dialog";
import { apiClient, type Agent } from "@/lib/api";

export function Agents() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<Partial<Agent>>({ name: "", is_active: true });

  const { data, isLoading } = useQuery({ queryKey: ["agents-list"], queryFn: () => apiClient.listAgents() });
  const create = useMutation({
    mutationFn: (data: Partial<Agent>) => apiClient.createAgent(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents-list"] });
      setOpen(false);
    },
  });
  const del = useMutation({
    mutationFn: (id: string) => apiClient.deleteAgent(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents-list"] }),
  });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">👥 订舱代理</h1>
          <p className="text-sm text-slate-500 mt-1">共 {data?.length ?? 0} 个</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button><Plus className="h-4 w-4" /> 新增</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>新增订舱代理</DialogTitle></DialogHeader>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1 col-span-2">
                <Label>名称 *</Label>
                <Input value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>代号</Label>
                <Input value={form.code ?? ""} onChange={(e) => setForm({ ...form, code: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>联系人</Label>
                <Input value={form.contact_person ?? ""} onChange={(e) => setForm({ ...form, contact_person: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>电话</Label>
                <Input value={form.contact_phone ?? ""} onChange={(e) => setForm({ ...form, contact_phone: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>联系邮箱</Label>
                <Input value={form.contact_email ?? ""} onChange={(e) => setForm({ ...form, contact_email: e.target.value })} />
              </div>
              <div className="space-y-1 col-span-2">
                <Label>订舱收件邮箱 (发邮件用)</Label>
                <Input value={form.booking_email ?? ""} onChange={(e) => setForm({ ...form, booking_email: e.target.value })} />
              </div>
              <div className="space-y-1 col-span-2">
                <Label>抄送邮箱 (逗号分隔)</Label>
                <Input
                  value={form.cc_emails?.join(",") ?? ""}
                  onChange={(e) => setForm({ ...form, cc_emails: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                />
              </div>
              <div className="space-y-1 col-span-2">
                <Label>擅长航线 (逗号分隔)</Label>
                <Input
                  value={form.service_routes?.join(",") ?? ""}
                  onChange={(e) => setForm({ ...form, service_routes: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                />
              </div>
            </div>
            <DialogFooter>
              <Button onClick={() => create.mutate(form)} disabled={!form.name || create.isPending}>创建</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="text-sm text-slate-400 py-8 text-center">加载中…</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>名称 / 代号</TableHead>
                  <TableHead>联系人</TableHead>
                  <TableHead>订舱邮箱</TableHead>
                  <TableHead>擅长航线</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>
                      <div className="font-medium">{a.name}</div>
                      <div className="text-xs text-slate-500">{a.code ?? "—"}</div>
                    </TableCell>
                    <TableCell>
                      <div className="text-sm">{a.contact_person ?? "—"}</div>
                      <div className="text-xs text-slate-500">{a.contact_phone ?? ""}</div>
                    </TableCell>
                    <TableCell className="text-sm font-mono">{a.booking_email ?? "—"}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {a.service_routes?.slice(0, 3).map((r) => (
                          <Badge key={r} variant="secondary" className="text-[10px]">{r}</Badge>
                        ))}
                        {(a.service_routes?.length ?? 0) > 3 && <span className="text-xs text-slate-400">+{a.service_routes.length - 3}</span>}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={a.is_active ? "success" : "secondary"}>
                        {a.is_active ? "启用" : "停用"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => del.mutate(a.id)} disabled={del.isPending}>
                        <Trash2 className="h-4 w-4 text-rose-500" />
                      </Button>
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
