import logging

import anthropic

from ..config import Settings
from . import LLMError, T

log = logging.getLogger(__name__)

# Models that accept the server-side refusal fallback in its "default" form.
_FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1"}


class ClaudeLLM:
    name = "anthropic"

    def __init__(self, settings: Settings):
        self.settings = settings
        # With no explicit key the SDK resolves ANTHROPIC_API_KEY / `ant auth login` profiles itself.
        self.client = (
            anthropic.Anthropic(api_key=settings.anthropic_api_key)
            if settings.anthropic_api_key
            else anthropic.Anthropic()
        )

    def _model_params(self, model: str) -> dict:
        if model.startswith("claude-haiku"):
            # Haiku 4.5 predates adaptive thinking and effort.
            return {}
        params: dict = {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.settings.llm_effort},
        }
        if model in _FALLBACK_MODELS:
            params["betas"] = ["server-side-fallback-2026-07-01"]
            params["fallbacks"] = "default"
        return params

    def structured(self, *, agent: str, system: str, prompt: str, schema: type[T]) -> T:
        model = self.settings.model_for(agent)
        try:
            response = self.client.beta.messages.parse(
                model=model,
                max_tokens=16000,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                **self._model_params(model),
            )
        except anthropic.AuthenticationError as e:
            raise LLMError("Anthropic API key is invalid or missing") from e
        except anthropic.NotFoundError as e:
            raise LLMError(f"Model '{model}' was not found") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Rate limited by the Anthropic API", retryable=True) from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Anthropic API error {e.status_code}: {e.message}", retryable=e.status_code >= 500) from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Could not reach the Anthropic API", retryable=True) from e

        log.info("%s agent: model=%s request_id=%s", agent, response.model, response._request_id)
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise LLMError(f"Claude declined this request (category: {category})")
        if response.stop_reason == "max_tokens":
            raise LLMError("Response was cut off by max_tokens")
        if response.parsed_output is None:
            raise LLMError("Claude returned no structured output")
        return response.parsed_output
