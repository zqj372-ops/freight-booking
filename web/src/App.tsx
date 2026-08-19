import { Route, Routes } from "react-router-dom";
import { Layout } from "@/components/layout";
import { Dashboard } from "@/pages/Dashboard";
import { SOInbox } from "@/pages/SOInbox";
import { Bookings } from "@/pages/Bookings";
import { Tracking } from "@/pages/Tracking";
import { Bills } from "@/pages/Bills";
import { Agents } from "@/pages/Agents";
import { EmailTemplates } from "@/pages/EmailTemplates";
import { EmailLogs } from "@/pages/EmailLogs";
import { Settings } from "@/pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="/so" element={<SOInbox />} />
        <Route path="/bookings" element={<Bookings />} />
        <Route path="/tracking" element={<Tracking />} />
        <Route path="/bills" element={<Bills />} />
        <Route path="/agents" element={<Agents />} />
        <Route path="/templates" element={<EmailTemplates />} />
        <Route path="/logs" element={<EmailLogs />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
