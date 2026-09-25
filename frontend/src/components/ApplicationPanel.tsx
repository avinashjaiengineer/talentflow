import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarCheck, Check, CheckCircle2, CircleDashed, RotateCw, Star, Video, X, XCircle } from "lucide-react";
import { type ReactNode, useState } from "react";
import { api, type Application } from "../api";
import { CallsSection, EmailsSection } from "./Communication";
import EventList from "./EventList";
import { Badge, Button, Card, ErrorNote, STAGE_META, ScoreBadge, StageBadge, cn, formatSlot } from "./ui";

export function useApplicationActions(id: string) {
  const qc = useQueryClient();
  const onSuccess = () => qc.invalidateQueries();
  return {
    decide: useMutation({ mutationFn: (v: { approvalId: string; approve: boolean; comment?: string }) => api.decide(v.approvalId, v.approve, v.comment), onSuccess }),
    replied: useMutation({ mutationFn: () => api.replied(id), onSuccess }),
    confirmSlot: useMutation({ mutationFn: (slot: string) => api.confirmSlot(id, slot), onSuccess }),
    notes: useMutation({ mutationFn: (notes: string) => api.submitNotes(id, notes), onSuccess }),
    reject: useMutation({ mutationFn: (reason?: string) => api.reject(id, reason), onSuccess }),
    retry: useMutation({ mutationFn: () => api.retry(id), onSuccess }),
    screen: useMutation({ mutationFn: () => api.screen(id), onSuccess }),
  };
}

function needsPolling(app: Application): boolean {
  return (
    STAGE_META[app.stage].working ||
    app.messages.some((m) => m.status === "queued") ||
    app.calls.some((c) => ["queued", "dialing", "in_progress"].includes(c.status) || (c.status === "completed" && !c.summary)) ||
    (!!app.scheduling?.confirmed_slot && !app.scheduling.meeting)
  );
}

export default function ApplicationPanel({ applicationId }: { applicationId: string }) {
  const { data: app, error } = useQuery({
    queryKey: ["application", applicationId],
    queryFn: () => api.application(applicationId),
    refetchInterval: (q) => (q.state.data && needsPolling(q.state.data) ? 1500 : false),
  });
  const { data: events = [] } = useQuery({
    queryKey: ["events", "application", applicationId, app?.updated_at],
    queryFn: () => api.events({ application_id: applicationId, limit: 50 }),
    enabled: !!app,
  });

  if (error) return <ErrorNote error={error} />;
  if (!app) return <p className="text-sm text-slate-500">Loading…</p>;
  const c = app.candidate;

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_280px]">
      <div className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-semibold">{c.name}</h3>
              <StageBadge stage={app.stage} />
            </div>
            <p className="text-sm text-slate-500">{c.headline}</p>
            <p className="text-xs text-slate-500">
              {[c.email, c.location, c.years_experience != null && `${c.years_experience} yrs`].filter(Boolean).join(" · ")}
            </p>
          </div>
          <div className="text-right text-xs text-slate-500">
            <div>for <span className="font-medium text-slate-700">{app.job_title}</span></div>
            {app.match_score != null && <div>Match similarity {Math.round(app.match_score * 100)}%</div>}
          </div>
        </div>

        {c.skills.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {c.skills.map((s) => <Badge key={s}>{s}</Badge>)}
          </div>
        )}

        <NextStep app={app} />
        {app.scorecard && <ScorecardView card={app.scorecard} />}
        {app.scheduling && <SchedulingView app={app} />}
        <CallsSection app={app} />
        <EmailsSection app={app} />
        {app.screening && <ScreeningView app={app} />}
      </div>

      <div>
        <h4 className="mb-3 text-sm font-semibold text-slate-700">Timeline</h4>
        <EventList events={events} compact />
      </div>
    </div>
  );
}

function NextStep({ app }: { app: Application }) {
  const a = useApplicationActions(app.id);
  const [comment, setComment] = useState("");
  const [notes, setNotes] = useState("");
  const approval = app.pending_approval;
  const closed = app.stage === "offer" || app.stage === "rejected";
  const busy = Object.values(a).some((m) => m.isPending);
  const firstError = Object.values(a).find((m) => m.error)?.error;

  return (
    <Card className="space-y-3 border-indigo-200 bg-indigo-50/40 p-4">
      {app.error && (
        <div className="flex items-start gap-2 rounded-lg bg-rose-50 p-3 text-sm text-rose-700">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <div className="flex-1">
            <p className="font-medium">The agent hit an error</p>
            <p>{app.error}</p>
          </div>
          <Button variant="secondary" onClick={() => a.retry.mutate()} loading={a.retry.isPending}>
            <RotateCw className="size-4" /> Retry
          </Button>
        </div>
      )}

      {approval && (
        <>
          <div>
            <p className="text-sm font-semibold text-slate-800">
              {approval.kind === "advance" ? "Approval needed: advance to outreach?" : "Approval needed: make an offer?"}
            </p>
            <p className="mt-1 text-sm text-slate-600">Agent recommendation: {approval.recommendation}</p>
          </div>
          <input className="input" placeholder="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
          <div className="flex gap-2">
            <Button onClick={() => a.decide.mutate({ approvalId: approval.id, approve: true, comment })} disabled={busy} loading={a.decide.isPending}>
              <Check className="size-4" /> {approval.kind === "advance" ? "Advance" : "Make offer"}
            </Button>
            <Button variant="danger" onClick={() => a.decide.mutate({ approvalId: approval.id, approve: false, comment })} disabled={busy}>
              <X className="size-4" /> Reject
            </Button>
          </div>
        </>
      )}

      {app.stage === "sourced" && (
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-slate-700">Sourced but not yet screened.</p>
          <Button onClick={() => a.screen.mutate()} loading={a.screen.isPending}>Run screening agent</Button>
        </div>
      )}

      {app.stage === "contacted" && (
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-slate-700">Send the outreach email (below) or run a pre-screen call. When the candidate replies, move on.</p>
          <Button onClick={() => a.replied.mutate()} loading={a.replied.isPending}>Candidate replied → schedule</Button>
        </div>
      )}

      {app.stage === "interview_scheduled" && (
        <div className="space-y-2">
          <p className="text-sm font-semibold text-slate-800">After the interview, paste the interviewer's notes</p>
          <textarea
            className="input min-h-28"
            placeholder="e.g. Strong system design; clear communicator; lighter on Kubernetes than expected…"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <Button onClick={() => a.notes.mutate(notes)} disabled={notes.trim().length < 10} loading={a.notes.isPending}>
            Run evaluation agent
          </Button>
        </div>
      )}

      {STAGE_META[app.stage].working && !app.error && (
        <p className="flex items-center gap-2 text-sm text-sky-700">
          <CircleDashed className="size-4 animate-spin" /> {STAGE_META[app.stage].label}
        </p>
      )}
      {app.stage === "offer" && (
        <p className="flex items-center gap-2 text-sm font-medium text-emerald-700"><CheckCircle2 className="size-4" /> Offer approved</p>
      )}
      {app.stage === "rejected" && (
        <p className="flex items-center gap-2 text-sm font-medium text-rose-700"><XCircle className="size-4" /> Rejected</p>
      )}

      {!closed && !approval && (
        <button className="text-xs text-slate-500 underline hover:text-rose-600" onClick={() => a.reject.mutate(undefined)} disabled={busy}>
          Reject candidate
        </button>
      )}
      <ErrorNote error={firstError} />
    </Card>
  );
}

function Section({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <h4 className="text-sm font-semibold text-slate-700">{title}</h4>
        {right}
      </div>
      {children}
    </Card>
  );
}

const REQ_ICON = { met: "text-emerald-600", partial: "text-amber-600", not_met: "text-rose-600" } as const;

function ScreeningView({ app }: { app: Application }) {
  const s = app.screening!;
  return (
    <Section title="Screening" right={<div className="flex items-center gap-2"><Badge>{s.recommendation}</Badge><ScoreBadge score={s.score} /></div>}>
      <p className="text-sm text-slate-700">{s.summary}</p>
      <ul className="mt-3 space-y-2">
        {s.requirements.map((r) => (
          <li key={r.requirement} className="flex gap-2 text-sm">
            <span className={cn("mt-0.5 font-bold", REQ_ICON[r.status])}>{r.status === "met" ? "✓" : r.status === "partial" ? "~" : "✗"}</span>
            <div>
              <span className="font-medium">{r.requirement}</span>
              <span className="text-slate-500"> — {r.evidence}</span>
            </div>
          </li>
        ))}
      </ul>
      {(s.strengths.length > 0 || s.gaps.length > 0) && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <List title="Strengths" items={s.strengths} />
          <List title="Gaps" items={s.gaps} />
        </div>
      )}
    </Section>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{title}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm text-slate-700">
        {items.map((i) => <li key={i}>{i}</li>)}
      </ul>
    </div>
  );
}

function SchedulingView({ app }: { app: Application }) {
  const s = app.scheduling!;
  const { confirmSlot } = useApplicationActions(app.id);
  return (
    <Section title={`Interview (${s.duration_minutes} min)`}>
      <div className="flex flex-wrap gap-2">
        {s.proposed_slots.map((slot) => {
          const confirmed = s.confirmed_slot === slot;
          return (
            <button
              key={slot}
              disabled={app.stage !== "interview_scheduled" || confirmSlot.isPending}
              onClick={() => confirmSlot.mutate(slot)}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-sm transition",
                confirmed ? "border-emerald-500 bg-emerald-50 font-medium text-emerald-700" : "border-slate-300 hover:border-indigo-400 disabled:hover:border-slate-300",
              )}
            >
              {confirmed && "✓ "}
              {formatSlot(slot)}
            </button>
          );
        })}
      </div>
      {!s.confirmed_slot && app.stage === "interview_scheduled" && (
        <p className="mt-2 text-xs text-slate-500">
          Send the invitation email (below) or use "Call to schedule". When the candidate picks a slot, click it to book the meeting.
        </p>
      )}
      {s.confirmed_slot && !s.meeting && <p className="mt-2 text-xs text-sky-700">Booking the meeting…</p>}
      {s.meeting && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <CalendarCheck className="size-4 text-emerald-600" />
          {s.meeting.provider === "graph" ? "Booked in Outlook; invitations sent." : "Booked in TalentFlow. Calendar isn't connected, so send the invite yourself."}
          {s.meeting.join_url && (
            <a href={s.meeting.join_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-indigo-600 hover:underline">
              <Video className="size-3.5" /> Join Teams meeting
            </a>
          )}
        </p>
      )}
    </Section>
  );
}

const REC_LABEL = { strong_hire: "Strong hire", hire: "Hire", no_hire: "No hire", strong_no_hire: "Strong no hire" };

function ScorecardView({ card }: { card: NonNullable<Application["scorecard"]> }) {
  return (
    <Section title="Scorecard" right={<Badge className={card.overall_rating >= 4 ? "bg-emerald-100 text-emerald-700" : card.overall_rating >= 3 ? "bg-amber-100 text-amber-800" : "bg-rose-100 text-rose-700"}>{REC_LABEL[card.recommendation]} · {card.overall_rating}/5</Badge>}>
      <p className="text-sm text-slate-700">{card.summary}</p>
      <ul className="mt-3 space-y-2">
        {card.competencies.map((c) => (
          <li key={c.name} className="text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{c.name}</span>
              <Stars n={c.rating} />
            </div>
            <p className="text-slate-500">{c.evidence}</p>
          </li>
        ))}
      </ul>
      <div className="mt-3"><List title="Risks to probe" items={card.risks} /></div>
    </Section>
  );
}

function Stars({ n }: { n: number }) {
  return (
    <span className="flex" aria-label={`${n} out of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Star key={i} className={cn("size-3.5", i <= n ? "fill-amber-400 text-amber-400" : "text-slate-300")} />
      ))}
    </span>
  );
}
