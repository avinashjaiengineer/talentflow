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
  created_at: string;
  resume_text?: string;
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
  } | null;
  interview_notes: string | null;
  scorecard: Scorecard | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  pending_approval: Approval | null;
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
  kind: "agent_step" | "source";
  status: "queued" | "running" | "succeeded" | "failed";
  application_id: string | null;
  job_id: string | null;
  result: { application_ids: string[]; count: number } | null;
  attempts: number;
  last_error: string | null;
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

  health: () => request<Health>("/health"),
  stats: () => request<Stats>("/stats"),
  events: (params: { application_id?: string; job_id?: string; limit?: number } = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]));
    return request<Event[]>(`/events?${q}`);
  },

  jobs: () => request<Job[]>("/jobs"),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  createJob: (body: Pick<Job, "title" | "department" | "location" | "description" | "requirements">) =>
    request<Job>("/jobs", json("POST", body)),
  updateJob: (id: string, body: Partial<Job>) => request<Job>(`/jobs/${id}`, json("PATCH", body)),
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
  deleteCandidate: (id: string) => request<void>(`/candidates/${id}`, { method: "DELETE" }),

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
