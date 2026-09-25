"""Adapters to the outside world: email, calendar, and phone.

Each has a safe local default (nothing leaves TalentFlow) and a real provider:
- email:    outbox (store only)       | graph (Microsoft 365 / Outlook)
- calendar: local (working-hours slots) | graph (Outlook free/busy + Teams meetings)
- voice:    simulated (chat in the UI)  | twilio (real phone calls)
"""


class IntegrationError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable
