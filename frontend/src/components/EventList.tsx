import { Bot, CalendarClock, ClipboardCheck, Inbox, Mail, PenLine, Search, User, Workflow } from "lucide-react";
import type { Event } from "../api";
import { cn, timeAgo } from "./ui";

const ACTORS: Record<string, { icon: typeof Bot; className: string }> = {
  intake: { icon: Inbox, className: "bg-teal-100 text-teal-700" },
  job_writer: { icon: PenLine, className: "bg-teal-100 text-teal-700" },
  sourcing: { icon: Search, className: "bg-teal-100 text-teal-700" },
  screening: { icon: ClipboardCheck, className: "bg-teal-100 text-teal-700" },
  outreach: { icon: Mail, className: "bg-teal-100 text-teal-700" },
  scheduling: { icon: CalendarClock, className: "bg-teal-100 text-teal-700" },
  evaluation: { icon: Bot, className: "bg-teal-100 text-teal-700" },
  orchestrator: { icon: Workflow, className: "bg-indigo-100 text-indigo-700" },
  human: { icon: User, className: "bg-amber-100 text-amber-700" },
};

export default function EventList({ events, compact }: { events: Event[]; compact?: boolean }) {
  if (!events.length) return <p className="py-6 text-center text-sm text-slate-500">No activity yet.</p>;
  return (
    <ol className="space-y-3">
      {events.map((e) => {
        const actor = ACTORS[e.actor] ?? ACTORS.orchestrator;
        const Icon = actor.icon;
        return (
          <li key={e.id} className="flex gap-3">
            <div className={cn("mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full", actor.className)}>
              <Icon className="size-3.5" />
            </div>
            <div className="min-w-0 flex-1">
              <p className={cn("text-sm text-slate-800", e.type === "agent_failed" && "text-rose-700")}>
                {!compact && e.candidate_name && <span className="font-medium">{e.candidate_name}: </span>}
                {e.message}
              </p>
              <p className="text-xs text-slate-500">
                <span className="capitalize">{e.actor}</span>
                {!compact && e.job_title && <> · {e.job_title}</>} · {timeAgo(e.created_at)}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
