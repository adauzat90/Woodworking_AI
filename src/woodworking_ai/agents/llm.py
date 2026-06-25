"""Thin wrapper around the Anthropic (Claude) API.

Kept tiny and dependency-lazy so the rest of the package never needs the SDK or
an API key unless you actually run the LLM designer agent.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol, runtime_checkable

# Static fallback model; override per-run with WOODAI_MODEL (read at call time by
# get_model(), so a post-import env change takes effect). Opus for the strongest
# design reasoning; set e.g. claude-sonnet-4-6 for cheaper/faster runs.
DEFAULT_MODEL = "claude-opus-4-8"


def get_model() -> str:
    """The model id to use, resolved at call time (env may change post-import)."""
    return os.environ.get("WOODAI_MODEL") or DEFAULT_MODEL


class LLMError(RuntimeError):
    pass


@runtime_checkable
class LLMClient(Protocol):
    """The slice of the Anthropic client this package depends on.

    Anything exposing a ``messages.create(...)`` returning a response with
    ``.content`` text blocks satisfies it — so a test fake or a second provider
    can be injected via :func:`set_client` without importing the SDK.
    """

    @property
    def messages(self) -> Any: ...


# Optional injected client (a fake in tests, or a second provider). When unset,
# get_client() builds the real Anthropic client lazily.
_client: "LLMClient | None" = None


def set_client(client: "LLMClient | None") -> None:
    """Inject (or, with ``None``, reset) the LLM client used by this module."""
    global _client
    _client = client


def get_client() -> "LLMClient":
    if _client is not None:
        return _client
    try:
        import anthropic  # type: ignore
    except ImportError as exc:
        raise LLMError(
            "The 'anthropic' package is required for the LLM agent.\n"
            "    pip install anthropic\n"
            "and set ANTHROPIC_API_KEY in your environment."
        ) from exc
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMError("ANTHROPIC_API_KEY is not set in the environment.")
    return anthropic.Anthropic()


def complete(system: str, messages: list[dict[str, str]],
             model: str | None = None, max_tokens: int = 2000) -> str:
    """Send a chat completion and return the assistant's text."""
    client = get_client()
    resp = client.messages.create(
        model=model or get_model(),
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return _text(resp)


def complete_with_image(system: str, user_text: str, image_bytes: bytes,
                        media_type: str = "image/png", model: str | None = None,
                        max_tokens: int = 1500) -> str:
    """Send a single image plus text to a vision-capable Claude model."""
    import base64

    client = get_client()
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    resp = client.messages.create(
        model=model or get_model(),
        max_tokens=max_tokens,
        system=system,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": user_text},
            ],
        }],
    )
    return _text(resp)


def _text(resp: Any) -> str:
    """Concatenate the text blocks of a messages response."""
    return "".join(
        block.text for block in resp.content if getattr(block, "type", None) == "text"
    ).strip()


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response, tolerating fences.

    Shared by the Designer (spec output) and the Critic (vision verdict).
    Raises ``ValueError`` if no JSON object is present and lets
    ``json.JSONDecodeError`` propagate for malformed JSON.
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in response: {text[:200]!r}")
    return json.loads(candidate[start : end + 1])
