"""Connection checks for Microsoft 365 and Twilio.   python -m app.integrations.check

Read-only: nothing is emailed, booked, or dialed. Each check says what's wrong and how to fix it.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

import httpx

from ..config import Settings, get_settings
from . import IntegrationError


@dataclass
class Check:
    area: str  # "Microsoft 365" | "Twilio"
    name: str
    ok: bool | None  # None = skipped (not enabled)
    detail: str


def check_microsoft(settings: Settings, transport: httpx.BaseTransport | None = None) -> list[Check]:
    area = "Microsoft 365"
    uses = [x for x, v in (("email", settings.email_provider), ("calendar", settings.calendar_provider),
                           ("resume intake", settings.intake_provider)) if v == "graph"]
    if not uses:
        return [Check(area, "Enabled", None, "Not enabled (EMAIL_PROVIDER / CALENDAR_PROVIDER / INTAKE_PROVIDER aren't 'graph')")]
    from .graph import GraphClient

    try:
        client = GraphClient(settings, transport=transport)
    except IntegrationError as e:
        return [Check(area, "Settings", False, str(e))]
    checks = [Check(area, "Settings", True, f"Used for {' and '.join(uses)}; sender mailbox {settings.ms_sender}")]
    try:
        client._access_token()
        checks.append(Check(area, "Sign-in", True, "Got an access token from Microsoft Entra ID"))
    except IntegrationError as e:
        hint = " Check MS_TENANT_ID, MS_CLIENT_ID, and that MS_CLIENT_SECRET hasn't expired."
        return [*checks, Check(area, "Sign-in", False, str(e) + hint)]

    if {"email", "calendar"} & set(uses):
        # Free/busy for the sender mailbox proves Calendars permission and mailbox scope, without writing anything.
        start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
        try:
            client.request(
                "POST", f"/users/{settings.ms_sender}/calendar/getSchedule",
                json={"schedules": [settings.ms_sender],
                      "startTime": {"dateTime": start.replace(tzinfo=None).isoformat(), "timeZone": "UTC"},
                      "endTime": {"dateTime": (start + timedelta(hours=1)).replace(tzinfo=None).isoformat(), "timeZone": "UTC"}},
            )
            checks.append(Check(area, "Calendar access", True, f"Can read {settings.ms_sender}'s free/busy"))
        except IntegrationError as e:
            hint = (" The app needs Calendars.ReadWrite, and with RBAC for Applications the mailbox must be in the"
                    " 'TalentFlow Mailboxes' scope (changes can take up to 2 hours).")
            checks.append(Check(area, "Calendar access", False, str(e) + hint))
    if "resume intake" in uses:
        mailbox = settings.intake_mailbox_address
        try:
            client.request("GET", f"/users/{mailbox}/mailFolders/{settings.intake_folder}/messages?$top=1&$select=id")
            checks.append(Check(area, "Resume intake mailbox", True, f"Can read {mailbox}/{settings.intake_folder}"))
        except IntegrationError as e:
            hint = (" The app needs Mail.Read on this mailbox (add it to the 'TalentFlow Mailboxes' scope), and"
                    " INTAKE_FOLDER must be a well-known folder name like 'inbox' or a folder id.")
            checks.append(Check(area, "Resume intake mailbox", False, str(e) + hint))
    if "email" in uses:
        checks.append(Check(area, "Email sending", None,
                            "Can't be checked without sending. Use 'Send test email to me' to confirm Mail.Send."))
    return checks


def check_twilio(settings: Settings, client=None, http: httpx.Client | None = None) -> list[Check]:
    area = "Twilio"
    if settings.voice_provider != "twilio":
        return [Check(area, "Enabled", None, "Not enabled (VOICE_PROVIDER isn't 'twilio'); calls are simulated")]
    missing = [k.upper() for k in ("twilio_account_sid", "twilio_auth_token", "twilio_from_number", "public_base_url")
               if not getattr(settings, k)]
    if missing:
        return [Check(area, "Settings", False, f"Missing: {', '.join(missing)}")]
    checks = [Check(area, "Settings", True, f"Calling from {settings.twilio_from_number}")]

    base = settings.public_base_url.rstrip("/")
    if not base.startswith("https://"):
        checks.append(Check(area, "Public URL", False, "PUBLIC_BASE_URL must start with https:// (Twilio connects back over wss://)"))
    else:
        try:
            r = (http or httpx.Client(timeout=10)).get(f"{base}/api/health")
            ok = r.status_code == 200 and r.json().get("status") == "ok"
            checks.append(Check(area, "Public URL", ok, f"{base} is reachable over HTTPS" if ok
                                else f"{base}/api/health returned {r.status_code}"))
        except (httpx.HTTPError, ValueError) as e:
            checks.append(Check(area, "Public URL", False, f"Couldn't reach {base}: {e}. Twilio must be able to reach it."))

    from twilio.base.exceptions import TwilioRestException

    try:
        if client is None:
            from twilio.rest import Client

            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        account = client.api.v2010.accounts(settings.twilio_account_sid).fetch()
        trial = getattr(account, "type", "") == "Trial"
        checks.append(Check(area, "Account", account.status == "active",
                            f"Account is {account.status}" + (" (trial: can only call verified numbers)" if trial else "")))
    except TwilioRestException as e:
        return [*checks, Check(area, "Account", False, f"Twilio rejected the credentials: {e.msg}. Check TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN.")]
    except Exception as e:  # network
        return [*checks, Check(area, "Account", False, f"Couldn't reach Twilio: {e}")]

    try:
        numbers = client.incoming_phone_numbers.list(phone_number=settings.twilio_from_number, limit=1)
        if not numbers:
            checks.append(Check(area, "Phone number", False,
                                f"{settings.twilio_from_number} isn't a number on this account (use E.164, e.g. +14155550100)"))
        else:
            voice = (numbers[0].capabilities or {}).get("voice", False)
            checks.append(Check(area, "Phone number", bool(voice),
                                f"{settings.twilio_from_number} " + ("can place voice calls" if voice else "has no voice capability")))
    except TwilioRestException as e:
        checks.append(Check(area, "Phone number", False, f"Couldn't look up the number: {e.msg}"))
    return checks


def run_checks(settings: Settings | None = None) -> list[dict]:
    settings = settings or get_settings()
    return [asdict(c) for c in (*check_microsoft(settings), *check_twilio(settings))]


if __name__ == "__main__":
    for c in run_checks():
        mark = {True: "OK  ", False: "FAIL", None: "--  "}[c["ok"]]
        print(f"[{mark}] {c['area']:<14} {c['name']:<16} {c['detail']}")
