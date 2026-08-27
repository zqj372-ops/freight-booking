import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  Package,
  ListTodo,
  Inbox,
  AlertTriangle,
  Users,
  Receipt,
  Settings as SettingsIcon,
  Anchor,
  Mail,
  ClipboardList,
  Activity,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

const nav = [
  { to: "/", icon: LayoutDashboard, label: "工作台" },
  { to: "/shipments", icon: Package, label: "业务单" },
  { to: "/forecasts", icon: TrendingUp, label: "预报货量", v06: true },
  { to: "/booking-requests", icon: ClipboardList, label: "订舱申请" },
  { to: "/email-threads", icon: Mail, label: "邮件中心" },
  { to: "/tasks", icon: ListTodo, label: "任务中心", v06: true },
  { to: "/exceptions", icon: AlertTriangle, label: "异常中心", v06: true },
  { to: "/ops", icon: Activity, label: "运营驾驶舱" },
  { to: "/so", icon: Inbox, label: "SO 收件箱", legacy: true },
  { to: "/partners", icon: Users, label: "合作方" },
  { to: "/bills", icon: Receipt, label: "账单", legacy: true },
  { to: "/settings", icon: SettingsIcon, label: "系统设置" },
];

export function Layout() {
  return (
    <div className="flex h-screen w-full bg-slate-50">
      {/* Sidebar */}
      <aside className="w-56 border-r bg-white flex flex-col">
        <div className="h-14 flex items-center gap-2 px-4 border-b">
          <Anchor className="h-5 w-5 text-sky-600" />
          <span className="font-semibold text-slate-900">二掌柜订舱</span>
          <Badge variant="secondary" className="ml-auto text-[10px]">v0.5</Badge>
        </div>
        <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors",
                  isActive
                    ? "bg-sky-50 text-sky-700 font-medium"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-900",
                )
              }
            >
              <item.icon className="h-4 w-4" />
              <span className="flex-1">{item.label}</span>
              {item.legacy && (
                <span className="text-[10px] text-slate-400">v0.4</span>
              )}
              {item.v06 && (
                <span className="text-[10px] text-orange-400">v0.6</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 text-[10px] text-slate-400 border-t">
          FreightFlow AI v0.5 © 2026
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
