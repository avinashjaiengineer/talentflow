"""Read job applications from an Outlook mailbox through Microsoft Graph.

Needs the Mail.Read application permission, scoped to the intake mailbox. Read-only:
TalentFlow never marks, moves, or deletes the recruiter's email; it remembers which
messages it has processed instead (IntakeItem).
"""

import base64
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from ..config import Settings
from . import IntegrationError
from .graph import GraphClient

RESUME_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


@dataclass
class Attachment:
    filename: str
    data: bytes


@dataclass
class InboundEmail:
    external_id: str  # the RFC 822 Message-ID: stable even if the email is moved to another folder
    graph_id: str
    subject: str
    sender: str | None
    body: str
    received_at: datetime | None
    attachment_names: list[str] = field(default_factory=list)


class GraphMailbox:
    def __init__(self, client: GraphClient, settings: Settings):
        self.client = client
        self.mailbox = settings.intake_mailbox_address
        self.folder = settings.intake_folder
        self.lookback = timedelta(days=settings.intake_lookback_days)

    def recent(self, *, limit: int = 50) -> Iterator[InboundEmail]:
        """Messages with attachments received in the lookback window, newest first."""
        since = (datetime.now(UTC) - self.lookback).strftime("%Y-%m-%dT%H:%M:%SZ")
        path = (
            f"/users/{quote(self.mailbox)}/mailFolders/{quote(self.folder)}/messages"
            f"?$filter=receivedDateTime ge {since} and hasAttachments eq true"
            f"&$orderby=receivedDateTime desc&$top={limit}"
            "&$select=id,internetMessageId,subject,from,receivedDateTime,body"
        )
        r = self.client.request("GET", path, headers={"Prefer": 'outlook.body-content-type="text"'})
        for m in r.json().get("value", []):
            received = m.get("receivedDateTime")
            yield InboundEmail(
                external_id=m.get("internetMessageId") or m["id"],
                graph_id=m["id"],
                subject=m.get("subject") or "",
                sender=((m.get("from") or {}).get("emailAddress") or {}).get("address"),
                body=(m.get("body") or {}).get("content") or "",
                received_at=datetime.fromisoformat(received.replace("Z", "+00:00")) if received else None,
            )

    def attachments(self, email: InboundEmail) -> list[Attachment]:
        """The email's file attachments. Only resume-like files are downloaded."""
        r = self.client.request("GET", f"/users/{quote(self.mailbox)}/messages/{email.graph_id}/attachments?$select=id,name,size")
        files = []
        for a in r.json().get("value", []):
            name = a.get("name") or ""
            email.attachment_names.append(name)
            if a.get("@odata.type") not in (None, "#microsoft.graph.fileAttachment"):
                continue  # attached emails and calendar items
            if not name.lower().endswith(RESUME_EXTENSIONS) or (a.get("size") or 0) > MAX_ATTACHMENT_BYTES:
                continue
            full = self.client.request("GET", f"/users/{quote(self.mailbox)}/messages/{email.graph_id}/attachments/{a['id']}").json()
            try:
                files.append(Attachment(filename=name, data=base64.b64decode(full.get("contentBytes") or "")))
            except ValueError as e:
                raise IntegrationError(f"Could not decode attachment {name!r}: {e}") from e
        return files


def get_mailbox(settings: Settings) -> GraphMailbox:
    if settings.intake_provider != "graph":
        raise IntegrationError("Mailbox intake is off: set INTAKE_PROVIDER=graph (see docs/INTEGRATIONS.md)")
    client = GraphClient(settings)
    if not settings.intake_mailbox_address:
        raise IntegrationError("Set INTAKE_MAILBOX (or MS_SENDER) to the mailbox job portals send applications to")
    return GraphMailbox(client, settings)


def pick_resume(files: Iterable[Attachment]) -> Attachment | None:
    """Prefer a file that looks like a resume; portals sometimes attach a cover letter too."""
    files = list(files)
    for f in files:
        if any(k in f.filename.lower() for k in ("resume", "cv", "biodata")):
            return f
    return files[0] if files else None
