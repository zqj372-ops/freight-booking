import { Route, Routes } from "react-router-dom";
import { Layout } from "@/components/layout";
import { Dashboard } from "@/pages/Dashboard";
import { Shipments } from "@/pages/Shipments";
import { ShipmentDetail } from "@/pages/ShipmentDetail";
import { Partners } from "@/pages/Partners";
import { LegacyPlaceholder } from "@/pages/LegacyPlaceholder";
import { Settings } from "@/pages/Settings";
import { BookingRequests } from "@/pages/BookingRequests";
import { BookingRequestDetail } from "@/pages/BookingRequestDetail";
import { EmailThreads } from "@/pages/EmailThreads";
import { EmailThreadDetail } from "@/pages/EmailThreadDetail";
import { OperationsDashboard } from "@/pages/OperationsDashboard";
import { Forecasts } from "@/pages/Forecasts";
import { ForecastNew } from "@/pages/ForecastNew";
import { ForecastWeekly } from "@/pages/ForecastWeekly";
import { ForecastImport } from "@/pages/ForecastImport";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        {/* v0.5 主用路由 */}
        <Route index element={<Dashboard />} />
        <Route path="/shipments" element={<Shipments />} />
        <Route path="/shipments/:id" element={<ShipmentDetail />} />
        <Route path="/booking-requests" element={<BookingRequests />} />
        <Route path="/booking-requests/:id" element={<BookingRequestDetail />} />
        <Route path="/email-threads" element={<EmailThreads />} />
        <Route path="/email-threads/:id" element={<EmailThreadDetail />} />
        <Route path="/ops" element={<OperationsDashboard />} />
        <Route path="/partners" element={<Partners />} />
        <Route path="/settings" element={<Settings />} />
        {/* v0.6 预报货量统计 */}
        <Route path="/forecasts" element={<Forecasts />} />
        <Route path="/forecasts/new" element={<ForecastNew />} />
        <Route path="/forecasts/weekly" element={<ForecastWeekly />} />
        <Route path="/forecasts/import" element={<ForecastImport />} />
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
