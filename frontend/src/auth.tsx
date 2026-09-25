import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Workflow } from "lucide-react";
import { createContext, type FormEvent, type ReactNode, useContext, useEffect, useState } from "react";
import { ApiError, UNAUTHORIZED_EVENT, api, type User } from "./api";
import { Button, ErrorNote } from "./components/ui";

const AuthContext = createContext<{ user: User; logout: () => void } | null>(null);

// Drop the previous user's cached data but keep the ["me"] query itself: <AuthGate> is
// subscribed to it, and removing it (e.g. qc.clear()) would leave the gate watching a
// detached query that never sees the new value.
function resetSession(qc: QueryClient, user: User | null) {
  qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
  qc.setQueryData(["me"], user);
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthGate>");
  return ctx;
}

export function AuthGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const { data: user, isLoading, error } = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: (count, err) => !(err instanceof ApiError && err.status === 401) && count < 2,
    staleTime: 5 * 60_000,
  });

  useEffect(() => {
    // Any 401 (expired session, deactivated account) drops back to the sign-in screen.
    const onUnauthorized = () => qc.setQueryData(["me"], null);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [qc]);

  const logout = async () => {
    await api.logout().catch(() => undefined);
    resetSession(qc, null);
  };

  if (isLoading) return <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">Loading…</div>;
  if (!user) {
    const unexpected = error && !(error instanceof ApiError && error.status === 401) ? error : null;
    return <LoginPage startupError={unexpected} />;
  }
  return <AuthContext.Provider value={{ user, logout }}>{children}</AuthContext.Provider>;
}

function LoginPage({ startupError }: { startupError: unknown }) {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => api.login(email, password),
    onSuccess: ({ user }) => resetSession(qc, user),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <div className="flex size-10 items-center justify-center rounded-xl bg-indigo-600 text-white">
            <Workflow className="size-5" />
          </div>
          <span className="text-2xl font-semibold tracking-tight">TalentFlow</span>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-lg font-semibold">Sign in</h1>
          <div>
            <label className="label" htmlFor="email">Email</label>
            <input id="email" type="email" autoComplete="username" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="password">Password</label>
            <input id="password" type="password" autoComplete="current-password" required className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <ErrorNote error={login.error ?? startupError} />
          <Button type="submit" className="w-full" loading={login.isPending}>Sign in</Button>
        </form>
        <p className="mt-4 text-center text-xs text-slate-500">Accounts are created by your TalentFlow admin.</p>
      </div>
    </div>
  );
}
