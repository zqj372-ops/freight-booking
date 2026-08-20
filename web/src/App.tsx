import { Route, Routes } from "react-router-dom";
import { Layout } from "@/components/layout";
import { Dashboard } from "@/pages/Dashboard";
import { Shipments } from "@/pages/Shipments";
import { ShipmentDetail } from "@/pages/ShipmentDetail";
import { Partners } from "@/pages/Partners";
import { LegacyPlaceholder } from "@/pages/LegacyPlaceholder";
import { Settings } from "@/pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        {/* v0.5 主用路由 */}
        <Route index element={<Dashboard />} />
        <Route path="/shipments" element={<Shipments />} />
        <Route path="/shipments/:id" element={<ShipmentDetail />} />
        <Route path="/partners" element={<Partners />} />
        <Route path="/settings" element={<Settings />} />
        {/* v0.4 兼容路由 (deprecated) - 引导到 v0.5 */}
        <Route path="/so" element={<LegacyPlaceholder title="SO 收件箱" v0_5_path="/shipments" />} />
        <Route path="/bookings" element={<LegacyPlaceholder title="订舱管理" v0_5_path="/shipments" />} />
        <Route path="/tracking" element={<LegacyPlaceholder title="运单跟踪" v0_5_path="/shipments" />} />
        <Route path="/bills" element={<LegacyPlaceholder title="账单" v0_5_path="/shipments" />} />
        <Route path="/agents" element={<Partners />} />
        <Route path="/templates" element={<LegacyPlaceholder title="邮件模板" v0_5_path="/settings" />} />
        <Route path="/logs" element={<LegacyPlaceholder title="发送历史" v0_5_path="/shipments" />} />
      </Route>
    </Routes>
  );
}
