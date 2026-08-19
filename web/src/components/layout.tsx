import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  Inbox,
  Package,
  Map,
  Receipt,
  Users,
  Mail,
  History,
  Settings as SettingsIcon,
  Anchor,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

const nav = [
  { to: "/", icon: LayoutDashboard, label: "工作台" },
  { to: "/so", icon: Inbox, label: "SO 收件箱" },
  { to: "/bookings", icon: Package, label: "订舱管理" },
  { to: "/tracking", icon: Map, label: "运单跟踪" },
  { to: "/bills", icon: Receipt, label: "账单中心" },
  { to: "/agents", icon: Users, label: "订舱代理" },
  { to: "/templates", icon: Mail, label: "邮件模板" },
  { to: "/logs", icon: History, label: "发送历史" },
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
          <Badge variant="secondary" className="ml-auto text-[10px]">v0.3</Badge>
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
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 text-[10px] text-slate-400 border-t">
          FreightFlow AI © 2026
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
