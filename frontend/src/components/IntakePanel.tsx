import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Inbox, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type IntakeItem } from "../api";
import { Badge, Button, Card, ErrorNote, timeAgo } from "./ui";

const STATUS: Record<IntakeItem["status"], { label: string; className: string }> = {
  imported: { label: "Imported", className: "bg-emerald-100 text-emerald-700" },
  duplicate: { label: "Already in pool", className: "bg-sky-100 text-sky-700" },
  skipped: { label: "Skipped", className: "bg-slate-100 text-slate-600" },
  failed: { label: "Failed", className: "bg-rose-100 text-rose-700" },
};

/** Applications that the intake agent picked up from job portals, by email or webhook. */
export default function IntakePanel() {
  const qc = useQueryClient();
  const [showAll, setShowAll] = useState(false);
  const { data: status } = useQuery({
    queryKey: ["intake", "status"],
    queryFn: api.intakeStatus,
    refetchInterval: (q) => (q.state.data?.checking ? 2_000 : 30_000),
  });
  const { data: items = [] } = useQuery({
    queryKey: ["intake", "items"],
    queryFn: () => api.intakeItems(50),
    refetchInterval: status?.checking ? 2_000 : 30_000,
  });
  const check = useMutation({
    mutationFn: api.checkIntake,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["intake"] }),
  });

  // When a check finishes, new candidates may be in the pool.
  const wasChecking = useRef(false);
  useEffect(() => {
    if (wasChecking.current && !status?.checking) {
      qc.invalidateQueries({ queryKey: ["intake", "items"] });
      qc.invalidateQueries({ queryKey: ["candidates"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    }
    wasChecking.current = !!status?.checking;
  }, [status?.checking, qc]);

  if (!status) return null;
  const connected = status.mailbox_enabled || status.webhook_enabled;
  const shown = showAll ? items : items.slice(0, 5);

  return (
    <Card className="mb-6 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex gap-3">
          <div className="rounded-lg bg-teal-100 p-2 text-teal-700"><Inbox className="size-5" /></div>
          <div>
            <h2 className="font-semibold">Job portal intake</h2>
            <p className="text-sm text-slate-500">
              {status.mailbox_enabled ? (
                <>
                  Reading applications emailed to <strong className="font-medium text-slate-700">{status.mailbox}</strong>
                  {status.poll_minutes > 0 && <> every {status.poll_minutes} min</>}
                  {status.last_checked && <> · checked {timeAgo(status.last_checked)}</>}
                </>
              ) : status.webhook_enabled ? (
                "Receiving applications pushed to the intake webhook."
              ) : (
                "Not connected. Have Naukri, LinkedIn, and Indeed send applications to an Outlook mailbox, or push them to the webhook. See docs/INTEGRATIONS.md."
              )}
            </p>
            {connected && (
              <p className="mt-1 text-xs text-slate-500">
                The intake agent skips alerts and newsletters, matches each application to an open job
                {status.auto_screen ? ", and starts screening" : ""}. Returning applicants are matched by email.
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {status.webhook_enabled && <Badge className="bg-teal-100 text-teal-700">Webhook on</Badge>}
          {status.mailbox_enabled && (
            <Button variant="secondary" onClick={() => check.mutate()} loading={check.isPending || status.checking}>
              {!(check.isPending || status.checking) && <RefreshCw className="size-4" />}
              {status.checking ? "Checking…" : "Check inbox now"}
            </Button>
          )}
        </div>
      </div>
      <ErrorNote error={check.error} />

      {items.length > 0 && (
        <ul className="mt-4 divide-y divide-slate-100 border-t border-slate-100 text-sm">
          {shown.map((i) => (
            <li key={i.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
              <Badge className={STATUS[i.status].className}>{STATUS[i.status].label}</Badge>
              <span className="font-medium">{i.candidate_name ?? (i.subject || "Untitled email")}</span>
              {i.portal && <span className="text-slate-500">via {i.portal}</span>}
              <span className="min-w-0 flex-1 truncate text-slate-500">
                {i.job_title ? `→ ${i.job_title}` : i.detail}
              </span>
              <span className="text-xs text-slate-400">{timeAgo(i.received_at ?? i.created_at)}</span>
            </li>
          ))}
        </ul>
      )}
      {items.length > 5 && (
        <button className="mt-2 text-xs text-indigo-600 hover:underline" onClick={() => setShowAll(!showAll)}>
          {showAll ? "Show fewer" : `Show all ${items.length}`}
        </button>
      )}
    </Card>
  );
}
