import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  DndContext, DragOverlay, type DragEndEvent, type DragStartEvent,
  PointerSensor, useSensor, useSensors, useDroppable, useDraggable,
} from "@dnd-kit/core";
import { Search, RefreshCw, Plus, Truck, Ship, MapPin, Package, X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { apiClient, type KanbanItem, type TrackingStatus } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";

const STATUS_ORDER: TrackingStatus[] = [
  "booked", "empty_picked_up", "loaded", "departed", "in_transit",
  "arrived", "delivered", "completed", "exception",
];

const STATUS_LABEL: Record<TrackingStatus, string> = {
  booked: "已订舱",
  empty_picked_up: "已提箱",
  loaded: "已装船",
  departed: "已开船",
  in_transit: "在途",
  arrived: "已到港",
  delivered: "已提货",
  completed: "已完成",
  exception: "异常",
};

const STATUS_ICON: Record<TrackingStatus, typeof Ship> = {
  booked: Package,
  empty_picked_up: Package,
  loaded: Package,
  departed: Ship,
  in_transit: Truck,
  arrived: MapPin,
  delivered: MapPin,
  completed: Package,
  exception: MapPin,
};

const STATUS_COLOR: Record<TrackingStatus, string> = {
  booked: "bg-slate-100 border-slate-300",
  empty_picked_up: "bg-amber-50 border-amber-200",
  loaded: "bg-amber-100 border-amber-300",
  departed: "bg-sky-100 border-sky-300",
  in_transit: "bg-sky-200 border-sky-400",
  arrived: "bg-emerald-100 border-emerald-300",
  delivered: "bg-emerald-200 border-emerald-400",
  completed: "bg-emerald-300 border-emerald-500",
  exception: "bg-rose-100 border-rose-300",
};

function DraggableCard({ item, onClick }: { item: KanbanItem; onClick: () => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: item.booking_id,
    data: { item },
  });
  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      onClick={onClick}
      className={cn(
        "p-2.5 rounded-md border bg-white shadow-sm hover:shadow-md transition-shadow cursor-grab active:cursor-grabbing",
        isDragging && "opacity-30",
      )}
    >
      <div className="text-sm font-medium text-slate-900">{item.booking_no}</div>
      <div className="text-xs text-slate-500 mt-0.5">
        {item.carrier} · {item.container}
      </div>
      <div className="text-xs text-slate-600 mt-1">
        📍 {item.pol} → {item.pod}
      </div>
      {item.customer_name && (
        <div className="text-xs text-slate-500 mt-0.5">👤 {item.customer_name}</div>
      )}
    </div>
  );
}

function DroppableColumn({
  status, label, count, items, onItemClick,
}: {
  status: TrackingStatus;
  label: string;
  count: number;
  items: KanbanItem[];
  onItemClick: (item: KanbanItem) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: status });
  const Icon = STATUS_ICON[status];
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex flex-col rounded-lg border-2 transition-colors min-w-[200px] flex-1",
        STATUS_COLOR[status],
        isOver && "ring-2 ring-sky-400 ring-offset-1",
      )}
    >
      <div className="px-3 py-2 flex items-center justify-between border-b">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-700">
          <Icon className="h-3.5 w-3.5" />
          {label}
        </div>
        <Badge variant="secondary" className="text-[10px] px-1.5">{count}</Badge>
      </div>
      <div className="flex-1 p-2 space-y-1.5 min-h-[100px]">
        {items.map((it) => (
          <DraggableCard key={it.booking_id} item={it} onClick={() => onItemClick(it)} />
        ))}
      </div>
    </div>
  );
}

export function Tracking() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [carrier, setCarrier] = useState("");
  const [activeItem, setActiveItem] = useState<KanbanItem | null>(null);
  const [editing, setEditing] = useState<KanbanItem | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["kanban", search, carrier],
    queryFn: () => apiClient.getKanban({ search: search || undefined, carrier: carrier || undefined }),
  });

  const { data: events } = useQuery({
    queryKey: ["tracking-events", editing?.booking_id],
    queryFn: () => apiClient.getTrackingEvents(editing!.booking_id),
    enabled: !!editing,
  });

  const addEvent = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof apiClient.addTrackingEvent>[1] }) =>
      apiClient.addTrackingEvent(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kanban"] });
      qc.invalidateQueries({ queryKey: ["tracking-events", editing?.booking_id] });
    },
  });

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const onDragStart = (e: DragStartEvent) => {
    setActiveItem(e.active.data.current?.item as KanbanItem);
  };
  const onDragEnd = (e: DragEndEvent) => {
    setActiveItem(null);
    if (!e.over) return;
    const item = e.active.data.current?.item as KanbanItem;
    const target = e.over.id as TrackingStatus;
    if (item.last_status === target) return;
    // 推进
    addEvent.mutate({
      id: item.booking_id,
      data: { status: target, occurred_at: new Date().toISOString() },
    });
  };

  return (
    <div className="p-6 max-w-full space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-semibold">🗺️ 运单跟踪</h1>
          <p className="text-sm text-slate-500 mt-1">共 {data?.total ?? 0} 个订舱 · 拖拽卡片推进状态</p>
        </div>
        <div className="flex gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
            <Input className="pl-8 w-48" placeholder="订舱号 / 客户" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <Input className="w-32" placeholder="船公司" value={carrier} onChange={(e) => setCarrier(e.target.value.toUpperCase())} />
          <Button variant="outline" size="sm" onClick={() => qc.invalidateQueries({ queryKey: ["kanban"] })}>
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="text-sm text-slate-400 py-8 text-center">加载中…</div>
      ) : (
        <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
          <div className="flex gap-3 overflow-x-auto pb-4">
            {data?.columns.map((col) => (
              <DroppableColumn
                key={col.status}
                status={col.status}
                label={col.label}
                count={col.count}
                items={col.items}
                onItemClick={(it) => setEditing(it)}
              />
            ))}
          </div>
          <DragOverlay>
            {activeItem ? <DraggableCard item={activeItem} onClick={() => {}} /> : null}
          </DragOverlay>
        </DndContext>
      )}

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editing?.booking_no} · {editing?.carrier}</DialogTitle>
          </DialogHeader>
          {editing && (
            <div className="space-y-3">
              <div className="text-sm text-slate-600">
                📍 {editing.pol} → {editing.pod} · {editing.container} · {editing.customer_name}
              </div>
              <div className="text-sm font-medium">跟踪时间线</div>
              <div className="space-y-1 max-h-48 overflow-y-auto border rounded p-2">
                {events?.map((ev) => (
                  <div key={ev.id} className="text-xs flex items-start gap-2 p-1.5 hover:bg-slate-50 rounded">
                    <Badge variant="outline" className="text-[10px]">{ev.status}</Badge>
                    <span className="text-slate-500 w-32 shrink-0">{formatDate(ev.occurred_at, true)}</span>
                    <span className="text-slate-700 flex-1">
                      {ev.location && `📍 ${ev.location}`}
                      {ev.vessel_name && ` · 🚢 ${ev.vessel_name}`}
                      {ev.container_no && ` · 📦 ${ev.container_no}`}
                      {ev.remark && ` · ${ev.remark}`}
                    </span>
                  </div>
                ))}
                {events?.length === 0 && <div className="text-xs text-slate-400">暂无事件</div>}
              </div>
              <AddEventForm
                onSubmit={(data) => editing && addEvent.mutate({ id: editing.booking_id, data })}
                isPending={addEvent.isPending}
              />
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              <X className="h-4 w-4" /> 关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function AddEventForm({ onSubmit, isPending }: { onSubmit: (data: any) => void; isPending: boolean }) {
  const [status, setStatus] = useState<TrackingStatus>("empty_picked_up");
  const [location, setLocation] = useState("");
  const [vessel, setVessel] = useState("");
  const [voyage, setVoyage] = useState("");
  const [container, setContainer] = useState("");
  const [remark, setRemark] = useState("");

  return (
    <div className="border-t pt-3 space-y-2">
      <div className="text-sm font-medium">添加节点</div>
      <div className="grid grid-cols-3 gap-2">
        <Select value={status} onValueChange={(v) => setStatus(v as TrackingStatus)}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {STATUS_ORDER.map((s) => <SelectItem key={s} value={s}>{STATUS_LABEL[s]}</SelectItem>)}
          </SelectContent>
        </Select>
        <Input placeholder="地点" value={location} onChange={(e) => setLocation(e.target.value)} />
        <Input placeholder="船名" value={vessel} onChange={(e) => setVessel(e.target.value)} />
        <Input placeholder="航次" value={voyage} onChange={(e) => setVoyage(e.target.value)} />
        <Input placeholder="柜号" value={container} onChange={(e) => setContainer(e.target.value)} />
        <Input placeholder="备注" value={remark} onChange={(e) => setRemark(e.target.value)} />
      </div>
      <Button
        size="sm"
        onClick={() => onSubmit({
          status,
          occurred_at: new Date().toISOString(),
          location: location || null,
          vessel_name: vessel || null,
          voyage_no: voyage || null,
          container_no: container || null,
          remark: remark || null,
        })}
        disabled={isPending}
      >
        <Plus className="h-4 w-4" /> 添加
      </Button>
    </div>
  );
}
