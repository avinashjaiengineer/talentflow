from types import SimpleNamespace

import httpx

from app.config import get_settings
from app.integrations.check import check_microsoft, check_twilio


def _ms_settings(monkeypatch, **extra):
    s = get_settings()
    values = {"email_provider": "graph", "calendar_provider": "graph", "ms_tenant_id": "t", "ms_client_id": "c",
              "ms_client_secret": "s", "ms_sender": "hr@acme.test", **extra}
    for k, v in values.items():
        monkeypatch.setattr(s, k, v)
    return s


def _graph_transport(token_status=200, schedule_status=200):
    def route(request: httpx.Request):
        if request.url.host == "login.microsoftonline.com":
            if token_status != 200:
                return httpx.Response(token_status, json={"error_description": "AADSTS7000215: Invalid client secret"})
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if schedule_status != 200:
            return httpx.Response(schedule_status, json={"error": {"message": "Access is denied"}})
        return httpx.Response(200, json={"value": []})

    return httpx.MockTransport(route)


def test_microsoft_checks_pass(monkeypatch):
    checks = check_microsoft(_ms_settings(monkeypatch), transport=_graph_transport())
    by = {c.name: c for c in checks}
    assert by["Sign-in"].ok and by["Calendar access"].ok
    assert by["Email sending"].ok is None  # needs an explicit test email


def test_microsoft_bad_secret_is_explained(monkeypatch):
    checks = check_microsoft(_ms_settings(monkeypatch), transport=_graph_transport(token_status=401))
    assert checks[-1].name == "Sign-in" and checks[-1].ok is False
    assert "Invalid client secret" in checks[-1].detail and "MS_CLIENT_SECRET" in checks[-1].detail


def test_microsoft_missing_scope_is_explained(monkeypatch):
    checks = check_microsoft(_ms_settings(monkeypatch), transport=_graph_transport(schedule_status=403))
    cal = next(c for c in checks if c.name == "Calendar access")
    assert cal.ok is False and "TalentFlow Mailboxes" in cal.detail


def test_microsoft_missing_settings(monkeypatch):
    checks = check_microsoft(_ms_settings(monkeypatch, ms_client_secret=None), transport=_graph_transport())
    assert checks == [checks[0]] and checks[0].ok is False and "MS_CLIENT_SECRET" in checks[0].detail


class FakeTwilio:
    def __init__(self, status="active", kind="Full", numbers=("voice",)):
        account = SimpleNamespace(status=status, type=kind)
        self.api = SimpleNamespace(v2010=SimpleNamespace(accounts=lambda sid: SimpleNamespace(fetch=lambda: account)))
        caps = [SimpleNamespace(capabilities={"voice": cap == "voice"}) for cap in numbers]
        self.incoming_phone_numbers = SimpleNamespace(list=lambda **kw: caps)


def _twilio_settings(monkeypatch, **extra):
    s = get_settings()
    values = {"voice_provider": "twilio", "twilio_account_sid": "AC1", "twilio_auth_token": "t",
              "twilio_from_number": "+15005550006", "public_base_url": "https://talent.example.com", **extra}
    for k, v in values.items():
        monkeypatch.setattr(s, k, v)
    return s


def _http(status=200):
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json={"status": "ok"})))


def test_twilio_checks_pass(monkeypatch):
    checks = check_twilio(_twilio_settings(monkeypatch), client=FakeTwilio(), http=_http())
    assert all(c.ok for c in checks), checks


def test_twilio_problems_are_explained(monkeypatch):
    by = {c.name: c for c in check_twilio(_twilio_settings(monkeypatch, public_base_url="http://1.2.3.4"),
                                          client=FakeTwilio(kind="Trial", numbers=()), http=_http())}
    assert by["Public URL"].ok is False and "https://" in by["Public URL"].detail
    assert "trial" in by["Account"].detail
    assert by["Phone number"].ok is False and "isn't a number on this account" in by["Phone number"].detail


def test_disabled_integrations_are_skipped():
    checks = check_microsoft(get_settings()) + check_twilio(get_settings())
    assert all(c.ok is None for c in checks)


def test_check_endpoints_are_admin_only(client):
    assert client.get("/api/system/integrations/check").status_code == 200
    assert client.post("/api/system/integrations/test-email").status_code == 409  # email not connected
    client.post("/api/users", json={"email": "rita@example.com", "name": "Rita", "password": "recruiter-pass-1"})
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "rita@example.com", "password": "recruiter-pass-1"})
    assert client.get("/api/system/integrations/check").status_code == 403


def test_test_email_goes_to_the_admin(client, monkeypatch):
    sent = {}

    class FakeGraph:
        name = "graph"

        def send(self, **kw):
            sent.update(kw)

    monkeypatch.setattr("app.api.system.get_email_sender", lambda: FakeGraph())
    assert client.post("/api/system/integrations/test-email").json() == {"sent_to": "admin@example.com"}
    assert sent["to"] == "admin@example.com" and "Outlook email is working" in sent["body"]
