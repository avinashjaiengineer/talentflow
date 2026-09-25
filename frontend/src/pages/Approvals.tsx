import { useQuery } from "@tanstack/react-query";
import { CheckSquare } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import ApplicationPanel from "../components/ApplicationPanel";
import { Badge, Button, Card, Empty, Modal, PageHeader, ScoreBadge, cn, timeAgo } from "../components/ui";

const TABS = [
  { key: "pending", label: "Waiting" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
] as const;

export default function ApprovalsPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("pending");
  const [selected, setSelected] = useState<string | null>(null);
  const { data: approvals, isLoading } = useQuery({
    queryKey: ["approvals", tab],
    queryFn: () => api.approvals(tab),
    refetchInterval: 5_000,
  });

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle={tab === "pending" ? "Offer decisions first, then strongest candidates. Agents recommend; you decide." : "Agents recommend; people decide."}
      />
      <div className="mb-4 flex gap-1 rounded-lg bg-slate-100 p-1 text-sm sm:inline-flex">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn("flex-1 rounded-md px-4 py-1.5 font-medium", tab === t.key ? "bg-white shadow-xs" : "text-slate-600 hover:text-slate-900")}
          >
            {t.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : !approvals?.length ? (
        <Empty icon={<CheckSquare className="size-8" />} title={tab === "pending" ? "You're all caught up" : "Nothing here yet"}>
          {tab === "pending" && "When the screening or evaluation agent finishes, its recommendation will wait here for you."}
        </Empty>
      ) : (
        <div className="space-y-3">
          {approvals.map((a) => (
            <Card key={a.id} className="flex flex-wrap items-center gap-4 p-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium">{a.candidate_name}</p>
                  <span className="text-sm text-slate-500">for {a.job_title}</span>
                  <Badge className={a.kind === "offer" ? "bg-emerald-100 text-emerald-700" : "bg-indigo-100 text-indigo-700"}>
                    {a.kind === "offer" ? "Offer decision" : "Advance after screening"}
                  </Badge>
                  {a.score != null && a.score_max != null && <ScoreBadge score={Math.round((a.score / a.score_max) * 100)} label={`${a.score}/${a.score_max}`} />}
                </div>
                <p className="mt-1 line-clamp-2 text-sm text-slate-600">{a.recommendation}</p>
                <p className="mt-1 text-xs text-slate-500">
                  {a.decided_at ? `${a.status} by ${a.decided_by} ${timeAgo(a.decided_at)}` : `requested ${timeAgo(a.created_at)}`}
                  {a.comment && ` · "${a.comment}"`}
                </p>
              </div>
              <Button variant={tab === "pending" ? "primary" : "secondary"} onClick={() => setSelected(a.application_id)}>
                {tab === "pending" ? "Review" : "View"}
              </Button>
            </Card>
          ))}
        </div>
      )}

      <Modal open={!!selected} onClose={() => setSelected(null)} title="Review candidate" wide>
        {selected && <ApplicationPanel applicationId={selected} />}
      </Modal>
    </>
  );
}
