from functools import lru_cache
from typing import Protocol

from ..config import get_settings
from .graph import GraphClient


class EmailSender(Protocol):
    name: str

    def send(self, *, to: str, subject: str, body: str) -> None: ...


class OutboxEmail:
    """Default: messages are recorded in TalentFlow but not delivered anywhere."""

    name = "outbox"

    def send(self, *, to: str, subject: str, body: str) -> None:
        return None


class GraphEmail:
    name = "graph"

    def __init__(self, client: GraphClient):
        self.client = client

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.client.request(
            "POST",
            f"/users/{self.client.sender}/sendMail",
            json={
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to}}],
                },
                "saveToSentItems": True,
            },
        )


@lru_cache
def get_email_sender() -> EmailSender:
    s = get_settings()
    return GraphEmail(GraphClient(s)) if s.email_provider == "graph" else OutboxEmail()
