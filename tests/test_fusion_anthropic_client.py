"""The pure-stdlib Anthropic client builds the right request and parses replies.

It must satisfy the slice ``woodworking_ai.agents.llm`` depends on
(``messages.create(...) -> .content`` text blocks) using only urllib, so the
designer loop runs inside Fusion with no SDK. We stub ``urlopen`` to assert on
the request it sends and to feed canned responses (including HTTP errors).
"""

import os
import io
import sys
import json
import urllib.error

import pytest


@pytest.fixture
def client_module():
    fusion_dir = os.path.realpath(
        os.path.join(os.path.dirname(__file__), "..", "fusion360")
    )
    if fusion_dir not in sys.path:
        sys.path.insert(0, fusion_dir)
    sys.modules.pop("anthropic_client", None)
    import anthropic_client

    yield anthropic_client
    sys.modules.pop("anthropic_client", None)


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_urlopen(client_module, monkeypatch, handler):
    monkeypatch.setattr(client_module.urllib.request, "urlopen", handler)


def test_requires_a_key(client_module, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError):
        client_module.AnthropicHTTPClient()


def test_key_from_env(client_module, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    assert client_module.AnthropicHTTPClient().api_key == "sk-env"


def test_create_builds_request_and_parses_blocks(client_module, monkeypatch):
    captured = {}

    def handler(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        body = {"content": [
            {"type": "text", "text": "hello "},
            {"type": "text", "text": "world"},
        ]}
        return _FakeResp(json.dumps(body).encode("utf-8"))

    _patch_urlopen(client_module, monkeypatch, handler)

    client = client_module.AnthropicHTTPClient(api_key="sk-test", timeout=42)
    resp = client.messages.create(
        model="claude-opus-4-8", max_tokens=1234,
        system="be terse", messages=[{"role": "user", "content": "hi"}],
    )

    assert captured["url"] == client_module.API_URL
    assert captured["method"] == "POST"
    assert captured["headers"]["x-api-key"] == "sk-test"
    assert captured["headers"]["anthropic-version"] == client_module.ANTHROPIC_VERSION
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["timeout"] == 42
    assert captured["payload"] == {
        "model": "claude-opus-4-8", "max_tokens": 1234,
        "system": "be terse", "messages": [{"role": "user", "content": "hi"}],
    }
    # response: text blocks exposed as .type / .text, like the SDK
    assert [(b.type, b.text) for b in resp.content] == [
        ("text", "hello "), ("text", "world")
    ]


def test_system_omitted_when_absent(client_module, monkeypatch):
    captured = {}

    def handler(request, timeout=None):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp(json.dumps({"content": []}).encode("utf-8"))

    _patch_urlopen(client_module, monkeypatch, handler)
    client = client_module.AnthropicHTTPClient(api_key="sk-test")
    client.messages.create(model="m", max_tokens=10,
                           messages=[{"role": "user", "content": "x"}])
    assert "system" not in captured["payload"]


def test_http_error_is_wrapped(client_module, monkeypatch):
    def handler(request, timeout=None):
        raise urllib.error.HTTPError(
            client_module.API_URL, 401, "Unauthorized", {},
            io.BytesIO(b'{"error":{"message":"bad key"}}'),
        )

    _patch_urlopen(client_module, monkeypatch, handler)
    client = client_module.AnthropicHTTPClient(api_key="sk-bad")
    with pytest.raises(RuntimeError) as excinfo:
        client.messages.create(model="m", max_tokens=10,
                               messages=[{"role": "user", "content": "x"}])
    assert "401" in str(excinfo.value)
    assert "bad key" in str(excinfo.value)


def test_satisfies_llm_client_protocol(client_module, monkeypatch):
    """Drop-in for llm.set_client: the designer can inject it unchanged."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    from woodworking_ai.agents import llm

    client = client_module.AnthropicHTTPClient()
    assert isinstance(client, llm.LLMClient)   # runtime_checkable Protocol


def test_drives_the_real_designer_loop(client_module, monkeypatch):
    """End-to-end: injected client -> design_from_prompt -> validated spec.

    No SDK, no network, no build123d (the analytical critic is CAD-free) — the
    whole Phase-3 path the Fusion add-in runs.
    """
    from woodworking_ai.agents import llm
    from woodworking_ai.agents.designer import design_from_prompt

    spec_json = {"cabinet_type": "base", "name": "Sink Base", "width": 900,
                 "height": 720, "depth": 560, "doors": 2, "shelves": 1,
                 "joinery": "dado"}

    def handler(request, timeout=None):
        body = {"content": [{"type": "text", "text": json.dumps(spec_json)}]}
        return _FakeResp(json.dumps(body).encode("utf-8"))

    _patch_urlopen(client_module, monkeypatch, handler)

    llm.set_client(client_module.AnthropicHTTPClient(api_key="sk-test"))
    try:
        result = design_from_prompt("36 inch sink base, two doors",
                                    run_critic=True, max_attempts=2)
    finally:
        llm.set_client(None)

    assert result.validation.ok
    assert result.spec.name == "Sink Base"
    assert result.spec.width == 900
    assert result.attempts == 1
