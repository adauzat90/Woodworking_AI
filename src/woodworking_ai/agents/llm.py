"""Thin wrapper around the Anthropic (Claude) API.

Kept tiny and dependency-lazy so the rest of the package never needs the SDK or
an API key unless you actually run the LLM designer agent.
"""

from __future__ import annotations

import os
from typing import Any

# Sensible default; override with WOODAI_MODEL. Opus for the strongest design
# reasoning; set e.g. claude-sonnet-4-6 for cheaper/faster runs.
DEFAULT_MODEL = os.environ.get("WOODAI_MODEL", "claude-opus-4-8")


class LLMError(RuntimeError):
    pass


def get_client() -> Any:
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
        model=model or DEFAULT_MODEL,
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
        model=model or DEFAULT_MODEL,
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
