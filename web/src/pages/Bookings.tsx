import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Plus, Mail, Trash2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger } from "@/components/ui/dialog";
import { apiClient, type Agent, type Booking } from "@/lib/api";
import { formatDate } from "@/lib/utils";

const CONTAINER_TYPES = ["20GP", "40GP", "40HQ", "45HQ", "20RF", "40RF", "20OT", "40OT"];

export function Bookings() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<Partial<Booking> & { agent_id?: string }>({
    carrier: "MAERSK",
    pol: "",
    pod: "",
    container_type: "40HQ",
    container_count: 1,
  });

  const { data, isLoading } = useQuery({ queryKey: ["bookings-list"], queryFn: () => apiClient.listBookings({ page: 1, page_size: 50 }) });
  const { data: agents } = useQuery({ queryKey: ["agents-list"], queryFn: () => apiClient.listAgents() });

  const create = useMutation({
    mutationFn: (data: Partial<Booking> & { agent_id?: string }) => apiClient.createBooking(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bookings-list"] });
      setOpen(false);
    },
  });

  const sendEmail = useMutation({
    mutationFn: (id: string) => apiClient.sendBookingEmail(id),
  });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">📦 订舱管理</h1>
          <p className="text-sm text-slate-500 mt-1">共 {data?.total ?? 0} 条</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="h-4 w-4" /> 新建订舱
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-xl">
            <DialogHeader>
              <DialogTitle>新建订舱</DialogTitle>
            </DialogHeader>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>船公司 *</Label>
                <Input value={form.carrier ?? ""} onChange={(e) => setForm({ ...form, carrier: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>订舱代理</Label>
                <Select value={form.agent_id ?? ""} onValueChange={(v) => setForm({ ...form, agent_id: v })}>
                  <SelectTrigger><SelectValue placeholder="选择代理" /></SelectTrigger>
                  <SelectContent>
                    {agents?.map((a: Agent) => (
                      <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label>POL *</Label>
                <Input value={form.pol ?? ""} onChange={(e) => setForm({ ...form, pol: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>POD *</Label>
                <Input value={form.pod ?? ""} onChange={(e) => setForm({ ...form, pod: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label>柜型</Label>
                <Select value={form.container_type ?? "40HQ"} onValueChange={(v) => setForm({ ...form, container_type: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {CONTAINER_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label>柜量</Label>
                <Input type="number" min={1} value={form.container_count ?? 1} onChange={(e) => setForm({ ...form, container_count: Number(e.target.value) })} />
              </div>
              <div className="space-y-1 col-span-2">
                <Label>客户名</Label>
                <Input value={form.customer_name ?? ""} onChange={(e) => setForm({ ...form, customer_name: e.target.value })} />
              </div>
              <div className="space-y-1 col-span-2">
                <Label>货物品名</Label>
                <Input value={form.commodity ?? ""} onChange={(e) => setForm({ ...form, commodity: e.target.value })} />
              </div>
            </div>
            <DialogFooter>
              <Button onClick={() => create.mutate(form)} disabled={create.isPending || !form.carrier || !form.pol || !form.pod}>
                创建
              </Button>
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
                  <TableHead>订舱号</TableHead>
                  <TableHead>船公司</TableHead>
                  <TableHead>航线</TableHead>
                  <TableHead>柜型</TableHead>
                  <TableHead>客户</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>创建</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.items.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell className="font-medium">{b.booking_no}</TableCell>
                    <TableCell>{b.carrier}</TableCell>
                    <TableCell>{b.pol} → {b.pod}</TableCell>
                    <TableCell>{b.container_count}×{b.container_type}</TableCell>
                    <TableCell>{b.customer_name ?? "—"}</TableCell>
                    <TableCell>
                      <Badge variant={b.status === "confirmed" ? "success" : b.status === "draft" ? "secondary" : "info"}>
                        {b.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-slate-500">{formatDate(b.created_at)}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => sendEmail.mutate(b.id)}
                        disabled={sendEmail.isPending}
                      >
                        <Mail className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {data?.items.length === 0 && (
                  <TableRow><TableCell colSpan={8} className="text-center py-8 text-slate-400">暂无</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
