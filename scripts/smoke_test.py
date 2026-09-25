"""End-to-end smoke test against a running TalentFlow deployment.

    python scripts/smoke_test.py http://<server>            # credentials from deploy/.env.production
    python scripts/smoke_test.py http://<server> --env path/to/.env

Walks one candidate through the whole pipeline with the real agents (Claude when the
server has an API key) and checks the security basics. Creates a job named
"[smoke test] ..." and demo candidates; delete the job afterwards if you like.
Standard library only.
"""

import argparse
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESUME = """Priya Raman
Senior Software Engineer, 8 years building backend systems
priya.raman+{tag}@example.com | Austin, TX
Staff-level Python and FastAPI services at a fintech handling 20k requests/sec.
Designed PostgreSQL schemas and led a migration to Kubernetes with Docker and Terraform on AWS.
Mentored four engineers and ran the API design review guild.
Skills: Python, FastAPI, PostgreSQL, Redis, Kafka, Docker, Kubernetes, AWS, REST API design"""


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method: str, path: str, body=None, expect=(200, 201, 202, 204)):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(req, timeout=60) as res:
                status, headers, raw = res.status, res.headers, res.read()
        except urllib.error.HTTPError as e:
            status, headers, raw = e.code, e.headers, e.read()
        if status not in expect:
            raise AssertionError(f"{method} {path} -> {status}: {raw[:300]!r}")
        return status, headers, (json.loads(raw) if raw and raw[:1] in b"[{" else None)


def read_env(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def wait_for(c: Client, app_id: str, stages: set[str], timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, _, app = c.call("GET", f"/api/applications/{app_id}")
        if app["stage"] in stages:
            return app
        if app["error"] and "retrying" not in app["error"]:
            raise AssertionError(f"agent failed at {app['stage']}: {app['error']}")
        time.sleep(2)
    raise AssertionError(f"timed out waiting for {stages}; still at {app['stage']} ({app['error']})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--env", default=str(ROOT / "deploy" / ".env.production"))
    ap.add_argument("--timeout", type=float, default=300, help="seconds to wait for each agent step")
    args = ap.parse_args()
    env = read_env(Path(args.env))
    c = Client(args.base_url)
    tag = uuid.uuid4().hex[:6]
    t0 = time.monotonic()

    def step(msg):
        print(f"[{time.monotonic() - t0:6.1f}s] {msg}", flush=True)

    _, headers, health = c.call("GET", "/api/health")
    step(f"health ok: v{health['version']} env={health['environment']} llm={health['llm']} db={health['database']}")
    assert health["environment"] == "production", "server is not in production mode"
    assert headers.get("X-Content-Type-Options") == "nosniff" and "default-src 'self'" in headers.get("Content-Security-Policy", "")
    c.call("GET", "/api/ready")
    c.call("GET", "/api/jobs", expect=(401,))
    c.call("GET", "/docs", expect=(200,))  # SPA fallback, not Swagger: docs are off in production
    step("security headers present, API requires sign-in, readiness ok")

    c.call("POST", "/api/auth/login", {"email": env["ADMIN_EMAIL"], "password": "definitely-wrong"}, expect=(401,))
    c.call("POST", "/api/auth/login", {"email": env["ADMIN_EMAIL"], "password": env["ADMIN_PASSWORD"]})
    _, _, me = c.call("GET", "/api/auth/me")
    step(f"signed in as {me['email']} ({me['role']})")

    _, _, job = c.call("POST", "/api/jobs", {
        "title": f"[smoke test {tag}] Senior Backend Engineer",
        "department": "Engineering", "location": "Remote",
        "description": "Own Python APIs end to end on PostgreSQL and Kubernetes; mentor engineers.",
        "requirements": ["5+ years backend development", "Python", "PostgreSQL", "Kubernetes"],
    })
    _, _, cand = c.call("POST", "/api/candidates", {"resume_text": RESUME.format(tag=tag)})
    step(f"resume parsed by the agent: {cand['name']} | {cand['headline']} | skills={cand['skills'][:5]}")

    _, _, app = c.call("POST", f"/api/jobs/{job['id']}/applications", {"candidate_id": cand["id"], "auto_screen": True})
    app = wait_for(c, app["id"], {"screened"}, args.timeout)
    s = app["screening"]
    step(f"screening agent: {s['score']}/100 -> {s['recommendation']}: {s['summary'][:140]}")
    assert s["requirements"], "screening returned no requirement breakdown"

    _, _, task = c.call("POST", f"/api/jobs/{job['id']}/source", {"limit": 3, "auto_screen": False})
    deadline = time.monotonic() + args.timeout
    while task["status"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(2)
        _, _, task = c.call("GET", f"/api/tasks/{task['id']}")
    assert task["status"] == "succeeded", f"sourcing task ended {task['status']}: {task['last_error']}"
    step(f"sourcing agent: {task['result']['count']} additional matches from the pool")

    c.call("POST", f"/api/approvals/{app['pending_approval']['id']}/decide", {"approve": True, "comment": "smoke test"})
    app = wait_for(c, app["id"], {"contacted"}, args.timeout)
    step(f"outreach agent: \"{app['outreach']['subject']}\"")

    c.call("POST", f"/api/applications/{app['id']}/replied")
    app = wait_for(c, app["id"], {"interview_scheduled"}, args.timeout)
    slot = app["scheduling"]["proposed_slots"][0]
    c.call("POST", f"/api/applications/{app['id']}/confirm-slot", {"slot": slot})
    step(f"scheduling agent: booked {slot}")

    c.call("POST", f"/api/applications/{app['id']}/notes", {
        "notes": "Excellent system design: sharded the payments ledger cleanly. Deep PostgreSQL knowledge. "
                 "Clear communicator. Lighter on Kubernetes networking than expected."
    })
    app = wait_for(c, app["id"], {"evaluated"}, args.timeout)
    card = app["scorecard"]
    step(f"evaluation agent: {card['overall_rating']}/5 -> {card['recommendation']}")

    c.call("POST", f"/api/approvals/{app['pending_approval']['id']}/decide", {"approve": True})
    _, _, app = c.call("GET", f"/api/applications/{app['id']}")
    assert app["stage"] == "offer"
    _, _, events = c.call("GET", f"/api/events?application_id={app['id']}")
    step(f"offer approved; {len(events)} events in the audit log")
    print(f"\nPASS: full pipeline in {time.monotonic() - t0:.0f}s against {args.base_url}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        sys.exit(1)
