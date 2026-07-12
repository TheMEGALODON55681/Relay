"""Every agent goes through this: LLM call, JSON-schema-constrained output, Pydantic
validation, one retry on invalid output, then a deterministic fallback with a logged
warning. No agent calls litellm directly.
"""

import json
import logging
import time

from litellm import completion
from pydantic import BaseModel

from config import settings

logger = logging.getLogger("relay.agents")


class AgentCallResult:
    def __init__(self, output: BaseModel, confidence: float, duration_ms: int, used_fallback: bool):
        self.output = output
        self.confidence = confidence
        self.duration_ms = duration_ms
        self.used_fallback = used_fallback


def call_agent(
    agent_name: str,
    system_prompt: str,
    user_payload: dict,
    output_model: type[BaseModel],
    fallback: BaseModel,
) -> AgentCallResult:
    """Never raises: network errors, malformed JSON, and schema mismatches are all
    "invalid output" per the PRD's agent contract, so they're caught the same way and
    resolved by retry-then-fallback rather than propagating to the caller.
    """
    start = time.monotonic()
    output = None
    for attempt in range(settings.AGENT_MAX_RETRIES + 1):
        try:
            raw = _call_llm(system_prompt, user_payload, output_model)
            output = output_model.model_validate_json(raw)
            break
        except Exception as exc:
            logger.warning("%s: attempt %d failed: %s", agent_name, attempt + 1, exc)

    duration_ms = int((time.monotonic() - start) * 1000)
    if output is None:
        logger.warning("%s: falling back to deterministic default after %d attempts", agent_name, settings.AGENT_MAX_RETRIES + 1)
        return AgentCallResult(fallback, confidence=0.0, duration_ms=duration_ms, used_fallback=True)
    return AgentCallResult(output, confidence=float(getattr(output, "confidence", 1.0)), duration_ms=duration_ms, used_fallback=False)


def _call_llm(system_prompt: str, user_payload: dict, output_model: type[BaseModel]) -> str:
    messages = [
        {"role": "system", "content": system_prompt + "\nRespond with ONLY valid JSON matching the schema. No prose, no markdown fences."},
        {"role": "user", "content": json.dumps(user_payload, default=str)},
    ]
    response = completion(model=settings.LLM_MODEL, messages=messages, response_format=output_model)
    return response.choices[0].message.content
