export type Stage =
  | "sourced"
  | "screening"
  | "screened"
  | "outreach"
  | "contacted"
  | "scheduling"
  | "interview_scheduled"
  | "evaluation"
  | "evaluated"
  | "offer"
  | "rejected"
  | "failed";

export interface Job {
  id: string;
  title: string;
  department: string | null;
  location: string | null;
  description: string;
  requirements: string[];
  interviewer_emails: string[];
  status: "open" | "closed";
  created_at: string;
  stage_counts: Record<string, number>;
}

export interface Candidate {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  location: string | null;
  headline: string | null;
  skills: string[];
  years_experience: number | null;
  resume_filename: string | null;
  has_original_file: boolean;
  do_not_call: boolean;
  created_at: string;
  resume_text?: string;
  profile?: CandidateProfile | null;
}

export interface CandidateProfile {
  links: string[];
  employment_history: { title: string; company: string | null; location: string | null; start: string | null; end: string | null; summary: string | null }[];
  education: { degree: string | null; field: string | null; institution: string | null; year: string | null }[];
  certifications: string[];
  projects: string[];
  years_from_dates: number | null;
}

export interface Approval {
  id: string;
  application_id: string;
  kind: "advance" | "offer";
  status: "pending" | "approved" | "rejected";
  recommendation: string | null;
  decided_by: string | null;
  comment: string | null;
  created_at: string;
  decided_at: string | null;
  candidate_name: string | null;
  job_title: string | null;
  score: number | null;
  score_max: number | null;
}

export interface Screening {
  score: number;
  recommendation: "advance" | "hold" | "reject";
  summary: string;
  strengths: string[];
  gaps: string[];
  requirements: { requirement: string; status: "met" | "partial" | "not_met"; evidence: string }[];
}

export interface Scorecard {
  overall_rating: number;
  recommendation: "strong_hire" | "hire" | "no_hire" | "strong_no_hire";
  summary: string;
  competencies: { name: string; rating: number; evidence: string }[];
  risks: string[];
}

export interface Application {
  id: string;
  job_id: string;
  job_title: string;
  candidate: Candidate;
  stage: Stage;
  match_score: number | null;
  screening_score: number | null;
  screening: Screening | null;
  outreach: { subject: string; body: string; to: string | null; sent_at: string } | null;
  scheduling: {
    proposed_slots: string[];
    confirmed_slot: string | null;
    duration_minutes: number;
    invitation: { subject: string; body: string };
    meeting?: { provider: string; event_id: string | null; join_url: string | null; booked_at: string };
  } | null;
  interview_notes: string | null;
  scorecard: Scorecard | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  pending_approval: Approval | null;
  messages: Message[];
  calls: Call[];
}

export interface Message {
  id: string;
  kind: "outreach" | "invitation" | "calendar_invite";
  status: "draft" | "queued" | "sent" | "failed";
  to: string | null;
  subject: string;
  body: string;
  provider: string | null;
  error: string | null;
  sent_by: string | null;
  sent_at: string | null;
  created_at: string;
}

export type CallPurpose = "prescreen" | "schedule" | "reminder";

export interface Call {
  id: string;
  purpose: CallPurpose;
  status: "scheduled" | "queued" | "dialing" | "in_progress" | "completed" | "no_answer" | "declined" | "failed" | "canceled";
  provider: "simulated" | "twilio";
  to_number: string | null;
  context: { questions?: string[]; slots?: { iso: string; label: string }[]; interview_label?: string };
  transcript: { role: "agent" | "candidate"; text: string; at: string }[];
  outcome: { consent?: string; opt_out?: boolean; wants_human?: boolean; booked_slot?: string; reminder_status?: string };
  summary: {
    summary: string;
    interested?: boolean | null;
    notice_period?: string | null;
    salary_expectation?: string | null;
    availability?: string | null;
    answers: { question: string; answer: string }[];
    concerns: string[];
  } | null;
  error: string | null;
  requested_by: string | null;
  scheduled_for: string | null;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
}

export interface Event {
  id: number;
  application_id: string | null;
  job_id: string | null;
  actor: string;
  type: string;
  message: string;
  data: Record<string, unknown> | null;
  created_at: string;
  candidate_name: string | null;
  job_title: string | null;
}

export interface Health {
  status: string;
  version: string;
  environment: string;
  llm: string;
  models: Record<string, string>;
  embeddings: string;
  database: string;
  integrations: { email: "outbox" | "graph"; calendar: "local" | "graph"; voice: "simulated" | "twilio"; intake: "off" | "graph" };
}

export interface Stats {
  open_jobs: number;
  candidates: number;
  pending_approvals: number;
  queued_tasks: number;
  stages: Record<string, number>;
}

export interface User {
  id: string;
  email: string;
  name: string;
  role: "admin" | "recruiter";
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface Task {
  id: number;
  kind: "agent_step" | "source" | "intake";
  status: "queued" | "running" | "succeeded" | "failed";
  application_id: string | null;
  job_id: string | null;
  result: { application_ids?: string[]; count: number } | null;
  attempts: number;
  last_error: string | null;
}

export interface JobDraft {
  title: string;
  department: string | null;
  location: string | null;
  description: string;
  requirements: string[];
}

export interface IntakeItem {
  id: string;
  source: "mailbox" | "webhook";
  portal: string | null;
  subject: string | null;
  sender: string | null;
  status: "imported" | "duplicate" | "skipped" | "failed";
  detail: string | null;
  candidate_id: string | null;
  job_id: string | null;
  application_id: string | null;
  received_at: string | null;
  created_at: string;
  candidate_name: string | null;
  job_title: string | null;
}

export interface IntakeStatus {
  mailbox_enabled: boolean;
  mailbox: string | null;
  poll_minutes: number;
  webhook_enabled: boolean;
  auto_screen: boolean;
  last_checked: string | null;
  checking: boolean;
}

export interface IntegrationCheck {
  area: string;
  name: string;
  ok: boolean | null;
  detail: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const UNAUTHORIZED_EVENT = "tf:unauthorized";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { credentials: "same-origin", ...init });
  if (res.status === 401 && !path.startsWith("/auth/login")) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  login: (email: string, password: string) => request<{ user: User }>("/auth/login", json("POST", { email, password })),
  logout: () => request<void>("/auth/logout", json("POST")),
  me: () => request<User>("/auth/me"),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("/auth/password", json("POST", { current_password, new_password })),
  users: () => request<User[]>("/users"),
  createUser: (body: { email: string; name: string; password: string; role: User["role"] }) => request<User>("/users", json("POST", body)),
  updateUser: (id: string, body: Partial<Pick<User, "name" | "role" | "is_active">> & { password?: string }) =>
    request<User>(`/users/${id}`, json("PATCH", body)),
  task: (id: number) => request<Task>(`/tasks/${id}`),

  system: () => request<Health>("/system"),
  checkIntegrations: () => request<IntegrationCheck[]>("/system/integrations/check"),
  sendTestEmail: () => request<{ sent_to: string }>("/system/integrations/test-email", json("POST")),
  stats: () => request<Stats>("/stats"),
  events: (params: { application_id?: string; job_id?: string; limit?: number } = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]));
    return request<Event[]>(`/events?${q}`);
  },

  jobs: () => request<Job[]>("/jobs"),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  createJob: (body: Pick<Job, "title" | "department" | "location" | "description" | "requirements" | "interviewer_emails">) =>
    request<Job>("/jobs", json("POST", body)),
  updateJob: (id: string, body: Partial<Job>) => request<Job>(`/jobs/${id}`, json("PATCH", body)),
  draftJob: (brief: string) => request<JobDraft>("/jobs/draft", json("POST", { brief })),
  deleteJob: (id: string) => request<void>(`/jobs/${id}`, { method: "DELETE" }),
  jobApplications: (id: string) => request<Application[]>(`/jobs/${id}/applications`),
  source: (id: string, limit: number) => request<Task>(`/jobs/${id}/source`, json("POST", { limit, auto_screen: true })),
  addToJob: (jobId: string, candidateId: string) =>
    request<Application>(`/jobs/${jobId}/applications`, json("POST", { candidate_id: candidateId, auto_screen: true })),

  candidates: (q?: string) => request<Candidate[]>(`/candidates${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  candidate: (id: string) => request<Candidate>(`/candidates/${id}`),
  candidateApplications: (id: string) => request<Application[]>(`/candidates/${id}/applications`),
  uploadResume: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Candidate>("/candidates/upload", { method: "POST", body: form });
  },
  createCandidate: (body: { resume_text: string; name?: string; email?: string }) =>
    request<Candidate>("/candidates", json("POST", body)),
  updateCandidate: (id: string, body: Partial<Pick<Candidate, "name" | "email" | "phone" | "location" | "do_not_call">>) =>
    request<Candidate>(`/candidates/${id}`, json("PATCH", body)),
  editMessage: (id: string, body: Partial<Pick<Message, "to" | "subject" | "body">>) => request<Message>(`/messages/${id}`, json("PATCH", body)),
  sendMessage: (id: string) => request<Message>(`/messages/${id}/send`, json("POST")),
  requestCall: (applicationId: string, purpose: CallPurpose) =>
    request<Call>(`/applications/${applicationId}/calls`, json("POST", { purpose })),
  cancelCall: (id: string) => request<Call>(`/calls/${id}/cancel`, json("POST")),
  simulateReply: (id: string, text: string) => request<Call>(`/calls/${id}/simulate`, json("POST", { text })),
  hangUp: (id: string) => request<Call>(`/calls/${id}/hang-up`, json("POST")),
  deleteCandidate: (id: string) => request<void>(`/candidates/${id}`, { method: "DELETE" }),

  intakeStatus: () => request<IntakeStatus>("/intake/status"),
  intakeItems: (limit = 50) => request<IntakeItem[]>(`/intake/items?limit=${limit}`),
  checkIntake: () => request<Task>("/intake/check", json("POST")),

  application: (id: string) => request<Application>(`/applications/${id}`),
  screen: (id: string) => request<Application>(`/applications/${id}/screen`, json("POST")),
  retry: (id: string) => request<Application>(`/applications/${id}/retry`, json("POST")),
  replied: (id: string) => request<Application>(`/applications/${id}/replied`, json("POST")),
  confirmSlot: (id: string, slot: string) => request<Application>(`/applications/${id}/confirm-slot`, json("POST", { slot })),
  submitNotes: (id: string, notes: string) => request<Application>(`/applications/${id}/notes`, json("POST", { notes })),
  reject: (id: string, reason?: string) => request<Application>(`/applications/${id}/reject`, json("POST", { reason })),

  approvals: (status?: "pending" | "approved" | "rejected") =>
    request<Approval[]>(`/approvals${status ? `?status=${status}` : ""}`),
  decide: (id: string, approve: boolean, comment?: string) =>
    request<Application>(`/approvals/${id}/decide`, json("POST", { approve, comment })),
};
