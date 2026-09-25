import { Loader2, X } from "lucide-react";
import { type ButtonHTMLAttributes, type ReactNode, useEffect } from "react";
import type { Stage } from "../api";

export function cn(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "danger" | "ghost";
const variants: Record<Variant, string> = {
  primary: "bg-indigo-600 text-white hover:bg-indigo-500 shadow-sm",
  secondary: "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 shadow-xs",
  danger: "bg-white text-rose-600 border border-rose-200 hover:bg-rose-50",
  ghost: "text-slate-600 hover:bg-slate-100",
};

export function Button({
  variant = "primary",
  loading,
  className,
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        className,
      )}
    >
      {loading && <Loader2 className="size-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("rounded-xl border border-slate-200 bg-white shadow-xs", className)}>{children}</div>;
}

export function Badge({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", className ?? "bg-slate-100 text-slate-700")}>
      {children}
    </span>
  );
}

export const STAGE_META: Record<Stage, { label: string; className: string; working?: boolean }> = {
  sourced: { label: "Sourced", className: "bg-slate-100 text-slate-700" },
  screening: { label: "Screening…", className: "bg-sky-100 text-sky-700", working: true },
  screened: { label: "Needs review", className: "bg-amber-100 text-amber-800" },
  outreach: { label: "Writing email…", className: "bg-sky-100 text-sky-700", working: true },
  contacted: { label: "Contacted", className: "bg-violet-100 text-violet-700" },
  scheduling: { label: "Scheduling…", className: "bg-sky-100 text-sky-700", working: true },
  interview_scheduled: { label: "Interview", className: "bg-indigo-100 text-indigo-700" },
  evaluation: { label: "Evaluating…", className: "bg-sky-100 text-sky-700", working: true },
  evaluated: { label: "Offer decision", className: "bg-amber-100 text-amber-800" },
  offer: { label: "Offer", className: "bg-emerald-100 text-emerald-700" },
  rejected: { label: "Rejected", className: "bg-rose-100 text-rose-700" },
  failed: { label: "Failed", className: "bg-rose-100 text-rose-700" },
};

export function StageBadge({ stage }: { stage: Stage }) {
  const meta = STAGE_META[stage];
  return (
    <Badge className={meta.className}>
      {meta.working && <Loader2 className="mr-1 size-3 animate-spin" />}
      {meta.label}
    </Badge>
  );
}

export function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) return null;
  const tone = score >= 70 ? "bg-emerald-100 text-emerald-700" : score >= 50 ? "bg-amber-100 text-amber-800" : "bg-rose-100 text-rose-700";
  return <Badge className={tone}>{score}</Badge>;
}

export function Modal({
  open,
  onClose,
  title,
  children,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 sm:p-8" onMouseDown={onClose}>
      <div
        className={cn("w-full rounded-2xl bg-white shadow-xl", wide ? "max-w-4xl" : "max-w-lg")}
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" aria-label="Close">
            <X className="size-5" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 px-6 py-14 text-center">
      <div className="mb-3 text-slate-400">{icon}</div>
      <p className="font-medium text-slate-700">{title}</p>
      {children && <div className="mt-1 max-w-sm text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error instanceof Error ? error.message : String(error)}</p>;
}

export function timeAgo(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function formatSlot(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
