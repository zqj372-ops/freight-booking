/// <reference types="vite/client" />
import axios, { type AxiosInstance } from "axios";

// v0.5: 切到 v2 API (v0.4 deprecated, 仅 GET 兼容)
const baseURL = import.meta.env.VITE_API_BASE || "/api/v2";

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

// ===== v0.5 Types =====

export type BusinessPhase = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;

export interface ShipmentListItem {
  id: string;
  job_no: string;
  route_summary: string;
  carrier_partner: string;
  vessel_voyage: string;
  current_etd: string | null;
  current_eta: string | null;
  business_phase: BusinessPhase;
  business_phase_label: string;
  business_phase_color: string;
  next_action: string;
  next_due_at: string | null;
  countdown_hours: number | null;
  next_action_priority: string;
  operator_user_name: string | null;
  exception_label: string;
  progress: number;
  last_updated_at: string | null;
}

export interface ShipmentDetail {
  id: string;
  job_no: string;
  legacy_job_no: string | null;
  customer_name: string | null;
  customer_ref: string | null;
  pol: string;
  pod: string;
  final_destination: string | null;
  target_etd: string;
  etd: string | null;
  eta: string | null;
  stage: string;
  container_count: number;
  current_carrier: string | null;
  current_partner_id: string | null;
  commodity: string;
  weight_kg: number | null;
  volume_cbm: number | null;
  booking_remark: string | null;
  customs_status: string | null;
  inspection_status: string | null;
  rolled_status: string | null;
  payment_request_status: string | null;
  payment_proof_status: string | null;
  empty_return_status: string | null;
  bl_process_status: string | null;
  so_no: string | null;
  bl_no: string | null;
  carrier_booking_no: string | null;
  so_received_at: string | null;
  sealed_at: string | null;
  cy_cutoff_at: string | null;
  empty_return_due_at: string | null;
  si_cutoff_at: string | null;
  vgm_cutoff_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface BusinessPhaseInfo {
  shipment_id: string;
  phase: BusinessPhase;
  phase_label: string;
  color: string;
  progress: number;
  milestone_count: number;
  has_open_exception: boolean;
  next_due_at: string | null;
  next_task_title: string | null;
}

export interface DashboardStats {
  overdue_tasks: number;
  due_today: number;
  awaiting_so: number;
  arriving_within_7d: number;
  overdue_tasks_top: DashboardTaskItem[];
  due_today_top: DashboardTaskItem[];
}

export interface DashboardTaskItem {
  task_id: string;
  title: string;
  due_at: string | null;
  job_no: string | null;
  pol: string | null;
  pod: string | null;
  shipment_id: string;
}

export interface DocumentChecklistItem {
  code: string;
  label: string;
  required: boolean;
  status: string;
  count: number;
  expected: number;
  latest_doc_id: string | null;
  latest_received_at: string | null;
}

export interface DocumentChecklist {
  shipment_id: string;
  items: DocumentChecklistItem[];
  total_required: number;
  total_completed: number;
  completion: number;
}

export interface Partner {
  id: string;
  partner_type: string;
  name: string;
  short_code: string | null;
  primary_email: string | null;
  cc_emails: string[];
  contact_person: string | null;
  contact_phone: string | null;
  preferred_routes: string[];
  remark: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface BookingConfirmation {
  id: string;
  shipment_id: string;
  document_id: string | null;
  carrier: string | null;
  so_no: string | null;
  bl_no: string | null;
  vessel_name: string | null;
  voyage_no: string | null;
  pol: string | null;
  pod: string | null;
  etd: string | null;
  eta: string | null;
  si_cutoff_at: string | null;
  container_type: string | null;
  container_count: number | null;
  version: number;
  is_current: boolean;
  status: string;
  accepted_at: string | null;
}

export interface Container {
  id: string;
  shipment_id: string;
  container_no: string | null;
  seal_no: string | null;
  container_type: string;
  status: string;
  pickup_time: string | null;
  loaded_time: string | null;
  return_time: string | null;
}

export interface Milestone {
  id: string;
  shipment_id: string;
  code: string;
  occurred_at: string;
  recorded_at: string;
  source: string;
  vessel_name: string | null;
  voyage_no: string | null;
  container_no: string | null;
  location: string | null;
  remark: string | null;
}

export interface Task {
  id: string;
  shipment_id: string;
  code: string;
  title: string;
  description: string | null;
  due_at: string | null;
  assignee_user_id: string | null;
  assignee_user_name: string | null;
  status: string;
  completed_at: string | null;
}

export interface AuditLog {
  id: string;
  entity_type: string;
  entity_id: string;
  action: string;
  field_changes: Record<string, unknown> | null;
  reason: string | null;
  actor_type: string;
  actor_user_name: string | null;
  actor_job_name: string | null;
  created_at: string;
}

// ===== BookingRequest v0.5 =====

export interface BookingRequest {
  id: string;
  organization_id: string;
  shipment_id: string;
  partner_id: string;
  booking_request_no: string;
  request_version: number;
  supersedes_id: string | null;
  cargo_snapshot: Record<string, unknown>;
  requested_etd: string;
  requested_pol: string;
  requested_pod: string;
  requested_container_type: string;
  requested_container_count: number;
  carrier_preference: string | null;
  email_thread_id: string | null;
  email_message_id: string | null;
  status: "draft" | "sent" | "acknowledged" | "confirmed" | "rejected" | "cancelled";
  sent_at: string | null;
  acknowledged_at: string | null;
  confirmed_at: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  expected_response_by: string | null;
  response_sla_hours: number | null;
  remark: string | null;
  created_at: string;
  updated_at: string;
}

// ===== EmailThread v0.5 =====

export interface EmailThread {
  id: string;
  organization_id: string;
  subject: string;
  subject_prefix: string | null;
  shipment_id: string | null;
  booking_request_id: string | null;
  partner_id: string | null;
  status: "active" | "closed" | "spam";
  created_at: string;
  updated_at: string;
}

export interface EmailMessage {
  id: string;
  organization_id: string;
  thread_id: string;
  direction: "inbound" | "outbound";
  message_id: string | null;
  in_reply_to: string | null;
  references: string | null;
  from_addr: string;
  to_addrs: string[];
  cc_addrs: string[];
  subject: string;
  body_text: string | null;
  body_html: string | null;
  received_at: string | null;
  sent_at: string | null;
  status: "draft" | "queued" | "sent" | "failed" | "received" | "processing" | "processed" | "ignored";
  error: string | null;
  retry_count: number;
  source: string;
  raw_eml_path: string | null;
  matched_shipment_id: string | null;
  matched_booking_request_id: string | null;
  match_confidence: number | null;
  created_at: string;
  updated_at: string;
}

export interface EmailThreadWithMessages extends EmailThread {
  messages: EmailMessage[];
}

// ===== OperationalException v0.5 =====

export interface OperationalException {
  id: string;
  organization_id: string;
  shipment_id: string;
  code: string;
  severity: "info" | "warning" | "critical";
  status: "open" | "resolved" | "auto_closed";
  detected_at: string;
  detected_by: string;
  resolved_at: string | null;
  resolved_by: string | null;
  resolved_by_name: string | null;
  resolution: string | null;
  related_milestone_id: string | null;
  related_task_id: string | null;
  context: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface ExceptionSummary {
  days: number;
  total_count: number;
  open_count: number;
  resolved_count: number;
  auto_closed_count: number;
  resolution_rate: number;
  by_severity: Record<string, number>;
  by_code: Array<{ code: string; total: number; open: number; resolved: number; auto_closed: number }>;
  by_shipment_top: Array<{ shipment_id: string; job_no: string; open_count: number }>;
}

// ===== KPI Dashboard v0.5 =====

export interface KpiCompletenessField {
  field: string;
  filled: number;
  total: number;
  rate: number;
}

export interface KpiDashboard {
  days: number;
  total_shipments: number;
  in_progress: number;
  completed: number;
  cancelled: number;
  cancel_rate: number;
  completeness: {
    avg_rate: number;
    fields: KpiCompletenessField[];
  };
  by_customer: Array<{ customer_name: string; count: number }>;
  by_route: Array<{ route: string; pol: string; pod: string; count: number }>;
  by_carrier: Array<{ carrier: string; count: number }>;
  monthly_trend: Array<{ month: string; count: number }>;
  response_time: {
    samples: number;
    avg_hours: number | null;
    p50_hours: number | null;
    p90_hours: number | null;
  };
}

// ===== v0.5 API Client =====

export const v5Api = {
  // Dashboard
  getDashboard: () => api.get<DashboardStats>("/dashboard/").then((r) => r.data),
  getKpi: (days = 90) => api.get<KpiDashboard>("/dashboard/kpi", { params: { days } }).then((r) => r.data),

  // Shipments
  listShipments: (params: { stage?: string; limit?: number; offset?: number; search?: string } = {}) =>
    api.get<ShipmentListItem[]>("/shipments/", { params }).then((r) => r.data),
  getShipment: (id: string) => api.get<ShipmentDetail>(`/shipments/${id}`).then((r) => r.data),
  getBusinessPhase: (id: string) =>
    api.get<BusinessPhaseInfo>(`/workflow/shipments/${id}/business-phase`).then((r) => r.data),
  getDocumentChecklist: (id: string) =>
    api.get<DocumentChecklist>(`/shipments/${id}/document-checklist`).then((r) => r.data),
  getBookingConfirmations: (id: string) =>
    api.get<BookingConfirmation[]>(`/shipments/${id}/booking-confirmations`).then((r) => r.data),
  getContainers: (id: string) =>
    api.get<Container[]>(`/shipments/${id}/containers`).then((r) => r.data),
  getMilestones: (id: string) =>
    api.get<Milestone[]>(`/workflow/shipments/${id}/milestones`).then((r) => r.data),
  getTasks: (id: string) =>
    api.get<Task[]>(`/workflow/shipments/${id}/tasks`).then((r) => r.data),
  getAuditLogs: (id: string) =>
    api.get<AuditLog[]>(`/audit-logs/?entity_type=shipment&entity_id=${id}`).then((r) => r.data),

  // BookingRequest
  listBookingRequests: (params: { shipment_id?: string; status?: string; limit?: number; offset?: number } = {}) =>
    api.get<BookingRequest[]>("/booking-requests/", { params }).then((r) => r.data),
  getBookingRequest: (id: string) =>
    api.get<BookingRequest>(`/booking-requests/${id}`).then((r) => r.data),

  // EmailThread
  listEmailThreads: (params: { shipment_id?: string; status?: string; limit?: number; offset?: number } = {}) =>
    api.get<EmailThread[]>("/emails/threads", { params }).then((r) => r.data),
  getEmailThread: (id: string) =>
    api.get<EmailThreadWithMessages>(`/emails/threads/${id}`).then((r) => r.data),

  // OperationalException (全局, 跨 shipment)
  listExceptions: (params: { status?: string; severity?: string; code?: string; shipment_id?: string; days?: number; limit?: number; offset?: number } = {}) =>
    api.get<OperationalException[]>("/exceptions/", { params }).then((r) => r.data),
  getExceptionSummary: (days = 30) =>
    api.get<ExceptionSummary>("/exceptions/summary", { params: { days } }).then((r) => r.data),

  // Partners
  listPartners: () => api.get<Partner[]>("/partners/").then((r) => r.data),

  // Migration monitor (v0.5 初始化)
  getMigrationStatus: () => api.get("/migration/status").then((r) => r.data),
  getApiStats: () => api.get("/migration/api-stats").then((r) => r.data),
};
