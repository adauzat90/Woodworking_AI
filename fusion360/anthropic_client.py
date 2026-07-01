"""A pure-stdlib Anthropic (Claude) Messages client for use inside Fusion 360.

Fusion's embedded Python can't install the ``anthropic`` SDK (it ships native
deps), so this implements -- with nothing but the standard library
(``urllib``) -- the exact slice the project's designer agent depends on:

    client.messages.create(model=, max_tokens=, system=, messages=)
        -> response with ``.content`` text blocks (each ``.type`` / ``.text``)

Inject it with ``woodworking_ai.agents.llm.set_client(AnthropicHTTPClient(key))``
and the whole natural-language -> validated-DSL repair loop
(``design_from_prompt``) runs unchanged, with no SDK and no native wheels.

The transport respects the standard ``HTTPS_PROXY`` / ``NO_PROXY`` environment
(urllib's default opener), so it works behind a corporate proxy.
"""

import os
import json
import urllib.request
import urllib.error

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class _Block:
    """One content block of a response (mirrors the SDK's ``.type`` / ``.text``)."""

    def __init__(self, block_type, text):
        self.type = block_type
        self.text = text


class _Response:
    def __init__(self, content):
        self.content = content


class _Messages:
    """The ``client.messages`` namespace, exposing ``.create(...)``."""

    def __init__(self, client):
        self._client = client

    def create(self, *, model, max_tokens, messages, system=None, **_ignored):
        return self._client._create(model, max_tokens, system, messages)


class AnthropicHTTPClient:
    """Minimal Anthropic Messages client over ``urllib`` (no SDK, no native deps).

    Satisfies :class:`woodworking_ai.agents.llm.LLMClient`, so it can be passed
    straight to ``llm.set_client(...)``.
    """

    def __init__(self, api_key=None, *, base_url=API_URL, timeout=180):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "No Anthropic API key. Set ANTHROPIC_API_KEY or pass api_key."
            )
        self.base_url = base_url
        self.timeout = timeout
        self.messages = _Messages(self)

    def _create(self, model, max_tokens, system, messages):
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(self.base_url, data=data, method="POST")
        request.add_header("content-type", "application/json")
        request.add_header("x-api-key", self.api_key)
        request.add_header("anthropic-version", ANTHROPIC_VERSION)

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError(
                f"Anthropic API HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Anthropic API request failed: {exc.reason}") from exc

        blocks = [
            _Block(b.get("type"), b.get("text", ""))
            for b in body.get("content", [])
        ]
        return _Response(blocks)
