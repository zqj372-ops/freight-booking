// v0.6 预报录入表单
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { v6Api, v5Api, type ForecastSource } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export function ForecastNew() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [form, setForm] = useState({
    source: "sales" as ForecastSource,
    source_ref: "",
    customer_id: "",
    pol: "CNSHA",
    pod: "USLAX",
    container_type: "40HQ",
    container_count: 1,
    target_etd: new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10),
    commodity: "",
    weight_kg: 0,
    volume_cbm: 0,
    pieces: 0,
    is_dangerous: false,
    notes: "",
  });
  const [customerName, setCustomerName] = useState("");

  const { data: partners } = useQuery({
    queryKey: ["partners"],
    queryFn: () => v5Api.listPartners(),
  });
  const customers = (partners ?? []).filter((p) => p.partner_type === "customer");

  const create = useMutation({
    mutationFn: (data: typeof form) => v6Api.createForecast({
      source: data.source,
      source_ref: data.source_ref || null,
      customer_id: data.customer_id,
      customer_name: customerName,
      pol: data.pol,
      pod: data.pod,
      container_type: data.container_type,
      container_count: data.container_count,
      target_etd: data.target_etd,
      commodity: data.commodity || null,
      weight_kg: data.weight_kg || null,
      volume_cbm: data.volume_cbm || null,
      pieces: data.pieces || null,
      is_dangerous: data.is_dangerous,
      notes: data.notes || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["forecasts"] });
      nav("/forecasts");
    },
  });

  function setField<K extends keyof typeof form>(k: K, v: typeof form[K]) {
    setForm({ ...form, [k]: v });
  }

  return (
    <div className="p-6 space-y-4 max-w-3xl mx-auto">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">新建预报</h1>
        <Button variant="outline" onClick={() => nav("/forecasts")}>← 返回</Button>
      </div>

      <Card>
        <CardHeader><CardTitle>基础信息</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>来源</Label>
              <Select value={form.source} onValueChange={(v) => setField("source", v as ForecastSource)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="sales">物友销售</SelectItem>
                  <SelectItem value="customer_service">客服</SelectItem>
                  <SelectItem value="shending">深鼎</SelectItem>
                  <SelectItem value="subsidiary">分子公司</SelectItem>
                  <SelectItem value="manual">人工补录</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>上游单号 (source_ref, 可选)</Label>
              <Input
                value={form.source_ref}
                onChange={(e) => setField("source_ref", e.target.value)}
                placeholder="WO-001 / 客户单号..."
              />
            </div>
            <div>
              <Label>客户</Label>
              <Select value={form.customer_id} onValueChange={(v) => {
                setField("customer_id", v);
                const c = customers.find((p) => p.id === v);
                if (c) setCustomerName(c.name);
              }}>
                <SelectTrigger><SelectValue placeholder="选择客户" /></SelectTrigger>
                <SelectContent>
                  {customers.length === 0 && (
                    <SelectItem value="__empty" disabled>暂无客户 (先去 /partners 建)</SelectItem>
                  )}
                  {customers.map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>目标开船日 (ETD)</Label>
              <Input
                type="date"
                value={form.target_etd}
                onChange={(e) => setField("target_etd", e.target.value)}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>航线 + 柜型</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>起运港 POL</Label>
              <Input
                value={form.pol}
                onChange={(e) => setField("pol", e.target.value.toUpperCase())}
                maxLength={5}
                placeholder="CNSHA"
              />
            </div>
            <div>
              <Label>目的港 POD</Label>
              <Input
                value={form.pod}
                onChange={(e) => setField("pod", e.target.value.toUpperCase())}
                maxLength={5}
                placeholder="USLAX"
              />
            </div>
            <div>
              <Label>柜型</Label>
              <Select value={form.container_type} onValueChange={(v) => setField("container_type", v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="20GP">20GP</SelectItem>
                  <SelectItem value="40GP">40GP</SelectItem>
                  <SelectItem value="40HQ">40HQ</SelectItem>
                  <SelectItem value="45HQ">45HQ</SelectItem>
                  <SelectItem value="20OT">20OT</SelectItem>
                  <SelectItem value="40OT">40OT</SelectItem>
                  <SelectItem value="20FR">20FR</SelectItem>
                  <SelectItem value="40FR">40FR</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>柜数</Label>
              <Input
                type="number"
                value={form.container_count}
                onChange={(e) => setField("container_count", Number(e.target.value))}
                min={1}
                max={100}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>货物 (可选)</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>品名</Label>
              <Input
                value={form.commodity}
                onChange={(e) => setField("commodity", e.target.value)}
              />
            </div>
            <div>
              <Label>重量 (KG)</Label>
              <Input
                type="number"
                value={form.weight_kg}
                onChange={(e) => setField("weight_kg", Number(e.target.value))}
              />
            </div>
            <div>
              <Label>体积 (CBM)</Label>
              <Input
                type="number"
                value={form.volume_cbm}
                onChange={(e) => setField("volume_cbm", Number(e.target.value))}
                step="0.01"
              />
            </div>
            <div>
              <Label>件数</Label>
              <Input
                type="number"
                value={form.pieces}
                onChange={(e) => setField("pieces", Number(e.target.value))}
              />
            </div>
            <div className="flex items-center gap-2 pt-6">
              <input
                type="checkbox"
                id="is_dangerous"
                checked={form.is_dangerous}
                onChange={(e) => setField("is_dangerous", e.target.checked)}
              />
              <Label htmlFor="is_dangerous">危险品</Label>
            </div>
          </div>
        </CardContent>
      </Card>

      <div>
        <Label>备注</Label>
        <Input
          value={form.notes}
          onChange={(e) => setField("notes", e.target.value)}
          placeholder="可选备注..."
        />
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={() => nav("/forecasts")}>取消</Button>
        <Button
          disabled={create.isPending || !form.customer_id}
          onClick={() => create.mutate(form)}
        >
          {create.isPending ? "提交中..." : "提交"}
        </Button>
      </div>
      {create.error && (
        <div className="text-red-600 text-sm">
          错误: {String(create.error)}
        </div>
      )}
    </div>
  );
}
