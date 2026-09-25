from functools import lru_cache
from typing import Protocol

from ..config import get_settings
from . import IntegrationError


class Voice(Protocol):
    name: str

    def place_call(self, *, call_id: str, to_number: str, relay_token: str, greeting: str) -> str | None:
        """Start the call; returns the provider's call id (None when simulated)."""
        ...


class SimulatedVoice:
    """Default: no phone. A recruiter plays the candidate in a chat window in the UI,
    and the same conversation engine answers. Lets you rehearse every call type."""

    name = "simulated"

    def place_call(self, *, call_id, to_number, relay_token, greeting):
        return None


class TwilioVoice:
    """Real calls. Twilio does speech-to-text and text-to-speech (ConversationRelay) and
    streams the conversation to /api/voice/relay/{call_id}, where Claude decides what to say."""

    name = "twilio"

    def __init__(self):
        s = get_settings()
        missing = [
            k for k in ("twilio_account_sid", "twilio_auth_token", "twilio_from_number", "public_base_url") if not getattr(s, k)
        ]
        if missing:
            raise IntegrationError(f"Twilio is not configured: set {', '.join(m.upper() for m in missing)}")
        if not s.public_base_url.startswith("https://"):
            raise IntegrationError("PUBLIC_BASE_URL must be https:// for Twilio voice (ConversationRelay needs wss://)")
        from twilio.rest import Client

        self.settings = s
        self.client = Client(s.twilio_account_sid, s.twilio_auth_token)

    def twiml(self, *, call_id: str, relay_token: str, greeting: str) -> str:
        from twilio.twiml.voice_response import Connect, VoiceResponse

        base = self.settings.public_base_url.rstrip("/")
        wss = "wss://" + base.removeprefix("https://")
        response = VoiceResponse()
        connect = Connect(action=f"{base}/api/voice/session-end/{call_id}")
        relay = connect.conversation_relay(
            url=f"{wss}/api/voice/relay/{call_id}?token={relay_token}",
            welcome_greeting=greeting,
            language=self.settings.voice_language,
            interruptible="speech",
        )
        relay.parameter(name="call_id", value=call_id)
        response.append(connect)
        return str(response)

    def place_call(self, *, call_id, to_number, relay_token, greeting):
        from twilio.base.exceptions import TwilioRestException

        base = self.settings.public_base_url.rstrip("/")
        try:
            call = self.client.calls.create(
                to=to_number,
                from_=self.settings.twilio_from_number,
                twiml=self.twiml(call_id=call_id, relay_token=relay_token, greeting=greeting),
                status_callback=f"{base}/api/voice/status/{call_id}",
                status_callback_event=["initiated", "ringing", "answered", "completed"],
                timeout=30,
            )
        except TwilioRestException as e:
            raise IntegrationError(f"Twilio refused the call: {e.msg}", retryable=(e.status or 0) >= 500) from e
        except Exception as e:  # network errors from the Twilio HTTP client
            raise IntegrationError(f"Could not reach Twilio: {e}", retryable=True) from e
        return call.sid


def validate_twilio_signature(url: str, params: dict, signature: str) -> bool:
    from twilio.request_validator import RequestValidator

    token = get_settings().twilio_auth_token
    return bool(token and signature) and RequestValidator(token).validate(url, params, signature)


@lru_cache
def get_voice() -> Voice:
    return TwilioVoice() if get_settings().voice_provider == "twilio" else SimulatedVoice()
