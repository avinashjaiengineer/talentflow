import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CalendarCheck, Mail, Phone, PhoneOff, Send, User, Video } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { api, type Application, type Call, type CallPurpose, type Message } from "../api";
import { Badge, Button, Card, ErrorNote, cn, formatSlot, timeAgo } from "./ui";

const KIND_LABEL: Record<Message["kind"], string> = {
  outreach: "Outreach email",
  invitation: "Interview invitation",
  calendar_invite: "Calendar invite",
};

const STATUS_TONE: Record<string, string> = {
  draft: "bg-amber-100 text-amber-800",
  queued: "bg-sky-100 text-sky-700",
  sent: "bg-emerald-100 text-emerald-700",
  failed: "bg-rose-100 text-rose-700",
};

function useIntegrations() {
  const { data } = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 60_000 });
  return data?.integrations;
}

function Section({ title, icon, right, children }: { title: string; icon: ReactNode; right?: ReactNode; children: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          {icon}
          {title}
        </h4>
        {right}
      </div>
      {children}
    </Card>
  );
}

// ---------------------------------------------------------------- email

export function EmailsSection({ app }: { app: Application }) {
  const integrations = useIntegrations();
  if (!app.messages.length) return null;
  const outbox = integrations?.email === "outbox";
  return (
    <Section title="Emails" icon={<Mail className="size-4" />}>
      {outbox && (
        <p className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Email delivery isn't connected, so "Send" records the email here and you send it yourself. An admin can connect Outlook (see
          docs/INTEGRATIONS.md).
        </p>
      )}
      <div className="space-y-3">
        {app.messages.map((m) => (
          <EmailCard key={m.id} message={m} joinUrl={m.kind === "calendar_invite" ? app.scheduling?.meeting?.join_url ?? null : null} />
        ))}
      </div>
    </Section>
  );
}

function EmailCard({ message: m, joinUrl }: { message: Message; joinUrl: string | null }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(m.subject);
  const [body, setBody] = useState(m.body);
  const refresh = () => qc.invalidateQueries();
  const save = useMutation({ mutationFn: () => api.editMessage(m.id, { subject, body }), onSuccess: () => { setEditing(false); refresh(); } });
  const send = useMutation({ mutationFn: () => api.sendMessage(m.id), onSuccess: refresh });
  const editable = m.status === "draft" || m.status === "failed";
  const statusText =
    m.status === "sent"
      ? m.provider === "graph" ? `sent via Outlook ${m.sent_at ? timeAgo(m.sent_at) : ""}` : "recorded (not delivered)"
      : m.status;

  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium text-slate-700">{KIND_LABEL[m.kind]}</span>
        <Badge className={STATUS_TONE[m.status]}>{statusText}</Badge>
        {m.to && <span className="text-slate-500">to {m.to}</span>}
      </div>
      {editing ? (
        <div className="space-y-2">
          <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} />
          <textarea className="input min-h-40" value={body} onChange={(e) => setBody(e.target.value)} />
          <div className="flex gap-2">
            <Button onClick={() => save.mutate()} loading={save.isPending}>Save</Button>
            <Button variant="secondary" onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </div>
      ) : (
        <>
          <p className="text-sm font-medium">{m.subject}</p>
          <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{m.body}</p>
          {joinUrl && (
            <a href={joinUrl} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-sm text-indigo-600 hover:underline">
              <Video className="size-4" /> Teams meeting link
            </a>
          )}
        </>
      )}
      {m.error && <p className="mt-2 text-xs text-rose-700">{m.error}</p>}
      {editable && !editing && (
        <div className="mt-3 flex gap-2">
          <Button onClick={() => send.mutate()} loading={send.isPending} disabled={!m.to}>
            <Send className="size-4" /> Send
          </Button>
          <Button variant="secondary" onClick={() => setEditing(true)}>Edit</Button>
          {!m.to && <span className="self-center text-xs text-rose-700">Add the candidate's email address first</span>}
        </div>
      )}
      <ErrorNote error={save.error ?? send.error} />
    </div>
  );
}

// ---------------------------------------------------------------- calls

const PURPOSE_LABEL: Record<CallPurpose, string> = {
  prescreen: "Pre-screen call",
  schedule: "Scheduling call",
  reminder: "Reminder call",
};

const CALL_STATUS: Record<Call["status"], { label: string; tone: string }> = {
  scheduled: { label: "scheduled", tone: "bg-slate-100 text-slate-700" },
  queued: { label: "starting…", tone: "bg-sky-100 text-sky-700" },
  dialing: { label: "dialing…", tone: "bg-sky-100 text-sky-700" },
  in_progress: { label: "live", tone: "bg-emerald-100 text-emerald-700" },
  completed: { label: "completed", tone: "bg-slate-100 text-slate-700" },
  no_answer: { label: "no answer", tone: "bg-amber-100 text-amber-800" },
  declined: { label: "declined", tone: "bg-amber-100 text-amber-800" },
  failed: { label: "failed", tone: "bg-rose-100 text-rose-700" },
  canceled: { label: "canceled", tone: "bg-slate-100 text-slate-500" },
};

const ACTIVE = new Set(["scheduled", "queued", "dialing", "in_progress"]);

export function CallsSection({ app }: { app: Application }) {
  const qc = useQueryClient();
  const integrations = useIntegrations();
  const request = useMutation({
    mutationFn: (purpose: CallPurpose) => api.requestCall(app.id, purpose),
    onSuccess: () => qc.invalidateQueries(),
  });
  const sched = app.scheduling;
  const busy = app.calls.some((c) => ACTIVE.has(c.status));
  const options: { purpose: CallPurpose; hint: string }[] = [];
  if (app.stage === "contacted" || app.stage === "screened")
    options.push({ purpose: "prescreen", hint: "Confirms interest and asks a few questions about the role" });
  if (app.stage === "interview_scheduled" && sched && !sched.confirmed_slot)
    options.push({ purpose: "schedule", hint: "Offers the proposed slots and books the one they pick" });
  if (sched?.confirmed_slot && app.stage === "interview_scheduled")
    options.push({ purpose: "reminder", hint: "Calls the day before to confirm they'll attend" });

  if (!options.length && !app.calls.length) return null;
  const simulated = integrations?.voice === "simulated";

  return (
    <Section
      title="AI calls"
      icon={<Phone className="size-4" />}
      right={app.candidate.do_not_call ? <Badge className="bg-rose-100 text-rose-700">Do not call</Badge> : undefined}
    >
      {simulated && options.length > 0 && (
        <p className="mb-3 rounded-md bg-sky-50 px-3 py-2 text-xs text-sky-800">
          Calls are <strong>simulated</strong>: you type the candidate's replies and the AI answers exactly as it would on a real call.
        </p>
      )}
      {!app.candidate.do_not_call && options.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {options.map((o) => (
            <Button key={o.purpose} variant="secondary" title={o.hint} disabled={busy} loading={request.isPending && request.variables === o.purpose}
              onClick={() => request.mutate(o.purpose)}>
              <Phone className="size-4" /> {o.purpose === "reminder" ? "Schedule reminder call" : o.purpose === "schedule" ? "Call to schedule" : "Pre-screen call"}
            </Button>
          ))}
        </div>
      )}
      {!simulated && !app.candidate.phone && options.length > 0 && (
        <p className="mb-3 text-xs text-rose-700">Add a phone number to the candidate (Talent pool) before calling.</p>
      )}
      <ErrorNote error={request.error} />
      <div className="space-y-3">
        {[...app.calls].reverse().map((c) => <CallCard key={c.id} call={c} />)}
      </div>
    </Section>
  );
}

function CallCard({ call }: { call: Call }) {
  const qc = useQueryClient();
  const cancel = useMutation({ mutationFn: () => api.cancelCall(call.id), onSuccess: () => qc.invalidateQueries() });
  const live = call.status === "in_progress" && call.provider === "simulated";
  const meta = CALL_STATUS[call.status];
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium text-slate-700">{PURPOSE_LABEL[call.purpose]}</span>
        <Badge className={meta.tone}>{meta.label}</Badge>
        {call.provider === "twilio" && call.to_number && <span className="text-slate-500">{call.to_number}</span>}
        {call.scheduled_for && call.status === "scheduled" && <span className="text-slate-500">at {formatSlot(call.scheduled_for)}</span>}
        {call.requested_by && <span className="text-slate-400">requested by {call.requested_by}</span>}
        {(call.status === "scheduled" || call.status === "queued") && (
          <button className="ml-auto text-xs text-slate-500 underline hover:text-rose-600" onClick={() => cancel.mutate()}>Cancel</button>
        )}
      </div>
      {call.outcome.opt_out && <p className="mt-2 text-xs font-medium text-rose-700">Candidate asked not to be called again.</p>}
      {call.outcome.wants_human && <p className="mt-2 text-xs font-medium text-amber-700">Candidate asked to speak with a recruiter.</p>}
      {call.outcome.booked_slot && <p className="mt-2 flex items-center gap-1 text-xs font-medium text-emerald-700"><CalendarCheck className="size-3.5" /> Booked {formatSlot(call.outcome.booked_slot)}</p>}
      {call.outcome.reminder_status && (
        <p className="mt-2 text-xs font-medium text-slate-700">
          {call.outcome.reminder_status === "confirmed" ? "✓ Confirmed they'll attend" : "Asked to reschedule"}
        </p>
      )}
      {call.summary && <CallSummary summary={call.summary} />}
      {(live || call.transcript.length > 1) && (
        live ? <Simulator call={call} /> : (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-slate-500">Transcript ({call.transcript.length} turns)</summary>
            <Transcript call={call} />
          </details>
        )
      )}
      {call.error && <p className="mt-2 text-xs text-rose-700">{call.error}</p>}
    </div>
  );
}

function CallSummary({ summary }: { summary: NonNullable<Call["summary"]> }) {
  const facts = [
    ["Interested", summary.interested == null ? null : summary.interested ? "Yes" : "No"],
    ["Notice period", summary.notice_period],
    ["Salary expectation", summary.salary_expectation],
    ["Availability", summary.availability],
  ].filter(([, v]) => v);
  return (
    <div className="mt-2 space-y-2 text-sm">
      <p className="text-slate-700">{summary.summary}</p>
      {facts.length > 0 && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          {facts.map(([k, v]) => (
            <div key={k}>
              <dt className="text-slate-500">{k}</dt>
              <dd className="font-medium text-slate-800">{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {summary.concerns.length > 0 && (
        <ul className="list-disc pl-4 text-xs text-amber-800">{summary.concerns.map((c) => <li key={c}>{c}</li>)}</ul>
      )}
    </div>
  );
}

function Transcript({ call }: { call: Call }) {
  return (
    <ol className="mt-2 space-y-2">
      {call.transcript.map((t, i) => (
        <li key={i} className={cn("flex gap-2", t.role === "candidate" && "flex-row-reverse")}>
          <div className={cn("mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full", t.role === "agent" ? "bg-teal-100 text-teal-700" : "bg-slate-200 text-slate-600")}>
            {t.role === "agent" ? <Bot className="size-3.5" /> : <User className="size-3.5" />}
          </div>
          <p className={cn("max-w-[85%] rounded-2xl px-3 py-2 text-sm", t.role === "agent" ? "bg-teal-50 text-slate-800" : "bg-indigo-600 text-white")}>
            {t.text}
          </p>
        </li>
      ))}
    </ol>
  );
}

function Simulator({ call }: { call: Call }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const reply = useMutation({
    mutationFn: () => api.simulateReply(call.id, text),
    onSuccess: () => {
      setText("");
      qc.invalidateQueries();
    },
  });
  const hangUp = useMutation({ mutationFn: () => api.hangUp(call.id), onSuccess: () => qc.invalidateQueries() });
  useEffect(() => end.current?.scrollIntoView({ block: "nearest" }), [call.transcript.length]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) reply.mutate();
  };
  return (
    <div className="mt-3 rounded-lg bg-slate-50 p-3">
      <p className="mb-2 text-xs font-medium text-slate-500">Simulated call. You're the candidate; the AI is speaking.</p>
      <div className="max-h-80 overflow-y-auto">
        <Transcript call={call} />
        {reply.isPending && <p className="mt-2 text-xs text-slate-500">AI is replying…</p>}
        <div ref={end} />
      </div>
      <form onSubmit={submit} className="mt-3 flex gap-2">
        <input className="input" autoFocus placeholder="Say something as the candidate…" value={text} onChange={(e) => setText(e.target.value)} disabled={reply.isPending} />
        <Button type="submit" loading={reply.isPending} disabled={!text.trim()}>Say</Button>
        <Button type="button" variant="danger" onClick={() => hangUp.mutate()} loading={hangUp.isPending} title="Hang up">
          <PhoneOff className="size-4" />
        </Button>
      </form>
      <ErrorNote error={reply.error ?? hangUp.error} />
    </div>
  );
}
