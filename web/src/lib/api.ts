import axios, { type AxiosInstance } from "axios";

const baseURL = import.meta.env.VITE_API_BASE || "/api/v1";

export const api: AxiosInstance = axios.create({
  baseURL,
  timeout: 60_000,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    const detail = err.response?.data?.detail || err.message;
    return Promise.reject(new Error(typeof detail === "string" ? detail : JSON.stringify(detail)));
  },
);

// ===== Types =====

export type SOStatus =
  | "pending"
  | "ocr_done"
  | "ocr_failed"
  | "confirmed"
  | "rejected";

export interface SOListItem {
  id: string;
  status: SOStatus;
  carrier: string | null;
  so_number: string | null;
  pol: string | null;
  pod: string | null;
  etd: string | null;
  container_type: string | null;
  container_count: number | null;
  file_name: string;
  created_at: string;
}

export interface SOListResponse {
  items: SOListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface Booking {
  id: string;
  booking_no: string;
  carrier: string;
  pol: string;
  pod: string;
  etd: string | null;
  eta: string | null;
  cut_off: string | null;
  container_type: string;
  container_count: number;
  commodity: string | null;
  weight_kg: number | null;
  volume_cbm: number | null;
  customer_name: string | null;
  customer_ref: string | null;
  status: string;
  remark: string | null;
  created_at: string;
  updated_at: string;
}

export interface Agent {
  id: string;
  name: string;
  code: string | null;
  contact_person: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  contact_wechat: string | null;
  booking_email: string | null;
  cc_emails: string[];
  service_routes: string[];
  notes: string | null;
  is_active: boolean;
}

export type TrackingStatus =
  | "booked"
  | "empty_picked_up"
  | "loaded"
  | "departed"
  | "in_transit"
  | "arrived"
  | "delivered"
  | "completed"
  | "exception";

export interface KanbanItem {
  booking_id: string;
  booking_no: string;
  carrier: string;
  pol: string;
  pod: string;
  container: string;
  customer_name: string | null;
  etd: string | null;
  eta: string | null;
  last_status: TrackingStatus;
  last_update: string;
}

export interface KanbanColumn {
  status: TrackingStatus;
  label: string;
  items: KanbanItem[];
  count: number;
}

export interface KanbanResponse {
  columns: KanbanColumn[];
  total: number;
}

export interface TrackingEvent {
  id: string;
  booking_id: string;
  status: TrackingStatus;
  occurred_at: string;
  location: string | null;
  vessel_name: string | null;
  voyage_no: string | null;
  container_no: string | null;
  source: string;
  remark: string | null;
  created_at: string;
}

export type BillStatus =
  | "uploaded"
  | "ocr_processing"
  | "ocr_done"
  | "ocr_failed"
  | "confirmed"
  | "disputed"
  | "paid";

export interface Bill {
  id: string;
  bill_no: string;
  bill_kind: string;
  bill_type: string;
  status: BillStatus;
  currency: string;
  total_amount: number | null;
  tax_amount: number | null;
  amount_excl_tax: number | null;
  seller_name: string | null;
  seller_tax_no: string | null;
  buyer_name: string | null;
  buyer_tax_no: string | null;
  booking_id: string | null;
  file_name: string | null;
  file_size: number;
  line_items: Array<Record<string, unknown>>;
  issued_at: string | null;
  due_at: string | null;
  paid_at: string | null;
  remark: string | null;
  created_at: string;
  updated_at: string;
}

export interface EmailTemplate {
  id: string;
  code: string;
  name: string;
  subject: string;
  body: string;
  is_active: boolean;
}

export interface EmailLog {
  id: string;
  template_code: string | null;
  to_emails: string[];
  cc_emails: string[];
  subject: string;
  status: string;
  sent_at: string | null;
  error: string | null;
  retry_count: number;
  booking_id: string | null;
  so_id: string | null;
  created_at: string;
}

export interface IngestionRecord {
  id: string;
  source: string;
  mailbox: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  total_fetched: number;
  new_count: number;
  skip_count: number;
  error_count: number;
  error: string | null;
  so_ids: string[];
  created_at: string;
}

// ===== API =====

export const apiClient = {
  // SO
  listSO: (params: { page?: number; page_size?: number; status?: string; carrier?: string } = {}) =>
    api.get<SOListResponse>("/so/", { params }).then((r) => r.data),
  getSO: (id: string) => api.get(`/so/${id}`).then((r) => r.data),
  updateSO: (id: string, data: Record<string, unknown>) =>
    api.patch(`/so/${id}`, data).then((r) => r.data),
  confirmSO: (id: string) => api.post(`/so/${id}/confirm`).then((r) => r.data),
  reocrSO: (id: string) => api.post(`/so/${id}/reocr`).then((r) => r.data),
  uploadSO: (file: File, meta: { source_email?: string; source_subject?: string }) => {
    const fd = new FormData();
    fd.append("file", file);
    if (meta.source_email) fd.append("source_email", meta.source_email);
    if (meta.source_subject) fd.append("source_subject", meta.source_subject);
    return api
      .post("/so/upload", fd, { headers: { "Content-Type": "multipart/form-data" } })
      .then((r) => r.data);
  },

  // Bookings
  listBookings: (params: { page?: number; page_size?: number; status?: string } = {}) =>
    api.get<{ items: Booking[]; total: number }>("/bookings/", { params }).then((r) => r.data),
  getBooking: (id: string) => api.get<Booking>(`/bookings/${id}`).then((r) => r.data),
  createBooking: (data: Partial<Booking> & { agent_id?: string }) =>
    api.post<Booking>("/bookings/", data).then((r) => r.data),
  updateBooking: (id: string, data: Partial<Booking>) =>
    api.patch<Booking>(`/bookings/${id}`, data).then((r) => r.data),
  sendBookingEmail: (id: string, templateCode = "booking_request") =>
    api.post(`/bookings/${id}/send`, null, { params: { template_code: templateCode } }).then((r) => r.data),

  // Agents
  listAgents: () => api.get<Agent[]>("/agents/").then((r) => r.data),
  createAgent: (data: Partial<Agent>) => api.post<Agent>("/agents/", data).then((r) => r.data),
  updateAgent: (id: string, data: Partial<Agent>) =>
    api.patch<Agent>(`/agents/${id}`, data).then((r) => r.data),
  deleteAgent: (id: string) => api.delete(`/agents/${id}`).then((r) => r.data),

  // Tracking
  getKanban: (params: { carrier?: string; search?: string } = {}) =>
    api.get<KanbanResponse>("/tracking/kanban", { params }).then((r) => r.data),
  getTrackingStatus: (bookingId: string) =>
    api.get<{ current_status: TrackingStatus }>(`/tracking/bookings/${bookingId}/status`).then((r) => r.data),
  getTrackingEvents: (bookingId: string) =>
    api.get<TrackingEvent[]>(`/tracking/bookings/${bookingId}/events`).then((r) => r.data),
  addTrackingEvent: (bookingId: string, data: Partial<TrackingEvent>) =>
    api.post<TrackingEvent>(`/tracking/bookings/${bookingId}/events`, data).then((r) => r.data),

  // Bills
  listBills: (params: { page?: number; page_size?: number; status?: string; bill_type?: string } = {}) =>
    api.get<{ items: Bill[]; total: number }>("/bills/", { params }).then((r) => r.data),
  getBill: (id: string) => api.get<Bill>(`/bills/${id}`).then((r) => r.data),
  updateBill: (id: string, data: Partial<Bill>) =>
    api.patch<Bill>(`/bills/${id}`, data).then((r) => r.data),
  reocrBill: (id: string) => api.post(`/bills/${id}/reocr`).then((r) => r.data),
  confirmBill: (id: string) => api.post(`/bills/${id}/confirm`).then((r) => r.data),
  uploadBill: (file: File, meta: { bill_type?: string; booking_id?: string }) => {
    const fd = new FormData();
    fd.append("file", file);
    if (meta.bill_type) fd.append("bill_type", meta.bill_type);
    if (meta.booking_id) fd.append("booking_id", meta.booking_id);
    return api
      .post("/bills/upload", fd, { headers: { "Content-Type": "multipart/form-data" } })
      .then((r) => r.data);
  },

  // Email templates
  listTemplates: () => api.get<EmailTemplate[]>("/emails/templates").then((r) => r.data),
  previewTemplate: (id: string, context: Record<string, unknown>) =>
    api.post<{ subject: string; body: string }>(`/emails/templates/${id}/preview`, context).then((r) => r.data),

  // Email logs
  listEmailLogs: (params: { page?: number; page_size?: number } = {}) =>
    api.get<EmailLog[]>("/emails/logs", { params }).then((r) => r.data),

  // IMAP
  ingestNow: (source?: "mock" | "imap") =>
    api.post<{ new_count: number; skip_count: number; total_fetched: number; so_ids: string[]; error?: string }>(
      "/imap/ingest-now",
      null,
      { params: source ? { source } : {} },
    ).then((r) => r.data),
  listIngestions: () => api.get<IngestionRecord[]>("/imap/ingestions").then((r) => r.data),

  // Finance
  payBill: (id: string, data: { payment_method: string; payment_ref?: string }) =>
    api.post<{ id: string; status: string; paid_at: string | null }>(`/finance/bills/${id}/pay`, data).then((r) => r.data),
  reconcile: () =>
    api.post<{ matched: number; results: Array<{ bill_id: string; booking_id: string; score: number; reasons: string[] }> }>(
      "/finance/reconcile",
    ).then((r) => r.data),
  financeDashboard: () =>
    api.get<{
      receivable_total: number;
      receivable_paid: number;
      receivable_pending: number;
      payable_total: number;
      payable_paid: number;
      payable_pending: number;
      overdue_count: number;
      by_carrier: Record<string, number>;
    }>("/finance/dashboard").then((r) => r.data),

  // Health
  health: () => fetch("/health").then((r) => r.json()) as Promise<{ status: string; version: string }>,
};
