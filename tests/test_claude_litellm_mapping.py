from __future__ import annotations

import asyncio
import base64
import importlib.util
import io
import json
from pathlib import Path

from proxy_stack.config import ProxyConfig
from proxy_stack.flows import generate_litellm_config_for_port
from proxy_stack.claude_code_api_adapter import model_catalog, normalize_model_request

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "claude-code-proxy" / "app.py"
spec = importlib.util.spec_from_file_location("claude_code_proxy_app", APP_PATH)
app = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(app)


def test_resolve_model_request_from_alias_suffix():
    payload = {"model": "claude-code-opus-4-7-xhigh"}
    assert app.resolve_model_request(payload["model"], payload) == ("claude-opus-4-7", "xhigh")


def test_payload_effort_overrides_alias_suffix():
    payload = {"model": "claude-code-sonnet-4-6-high", "output_config": {"effort": "max"}}
    assert app.resolve_model_request(payload["model"], payload) == ("claude-sonnet-4-6", "max")


def test_accepts_litellm_reasoning_effort_alias():
    payload = {"model": "claude-code-opus", "reasoning_effort": "minimal"}
    assert app.resolve_model_request(payload["model"], payload) == ("opus", "low")


def test_claude_code_api_adapter_catalog_includes_max_effort_aliases():
    models = set(model_catalog())
    assert "claude-code-sonnet-max" in models
    assert "claude-code-sonnet-4-6-max" in models
    assert "claude-code-opus-max" in models
    assert "claude-code-opus-4-7-max" in models


def test_claude_code_api_adapter_normalizes_max_effort_aliases():
    payload = normalize_model_request({"model": "claude-code-sonnet-4-6-max", "max_tokens": 10})
    assert payload["model"] == "claude-sonnet-4-6"
    assert payload["output_config"]["effort"] == "max"


def test_claude_command_allows_web_tools():
    command = app.claude_command("hi", "sonnet", "json")
    assert "--permission-mode" in command
    assert command[command.index("--permission-mode") + 1] == "bypassPermissions"
    assert "--tools=default" in command
    allowed = next(item for item in command if item.startswith("--allowed-tools="))
    assert "WebSearch" in allowed
    assert "WebFetch" in allowed
    assert "Bash" in allowed
    assert "--no-session-persistence" in command
    assert command[command.index("--max-turns") + 1] == "8"


def test_claude_stream_command_includes_partial_messages():
    command = app.claude_command("", "sonnet", "stream-json", verbose=True)
    assert "--include-partial-messages" in command


def test_streaming_skips_thinking_and_remaps_tool_index(monkeypatch):
    events = [
        {"type": "stream_event", "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "plan"}}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig"}}},
        {"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}},
        {"type": "stream_event", "event": {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "WebSearch", "input": {}}}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"query\":\"x\"}"}}},
        {"type": "stream_event", "event": {"type": "content_block_stop", "index": 1}},
        {"type": "stream_event", "event": {"type": "message_delta", "delta": {"stop_reason": "tool_use"}}},
    ]

    class FakeProcess:
        def __init__(self):
            self.stdout = io.StringIO("".join(json.dumps(event) + "\n" for event in events))
            self.stderr = io.StringIO("")
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(app, "run_claude_streaming", lambda *args, **kwargs: FakeProcess())

    async def collect_stream():
        response = await app._stream_messages(
            {"messages": [{"role": "user", "content": "search"}], "stream": True},
            "sonnet",
            "claude-code-sonnet",
            None,
            None,
            "test-stream",
            app.now_ms(),
        )
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return "".join(chunks)

    body = asyncio.run(collect_stream())
    assert '"thinking"' not in body
    assert '"signature_delta"' not in body
    assert '"type": "tool_use"' in body
    assert '"index": 0, "content_block": {"type": "tool_use"' in body
    assert '"index": 0, "delta": {"type": "input_json_delta"' in body
    assert '"stop_reason": "tool_use"' in body


def test_api_config_prompt_preserves_anthropic_controls():
    prompt = app.api_config_to_prompt({
        "max_tokens": 50,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "tool_choice": {"type": "auto"},
        "thinking": {"type": "enabled", "budget_tokens": 1024},
        "stop_sequences": ["END"],
        "mcp_servers": [{"type": "url", "url": "https://example.com/mcp"}],
        "output_config": {"effort": "high"},
        "cache_control": {"type": "ephemeral"},
        "inference_geo": "us",
    })
    assert "Anthropic Messages API request configuration" in prompt
    assert '"tools"' in prompt
    assert '"tool_choice"' in prompt
    assert '"thinking"' in prompt
    assert '"mcp_servers"' in prompt
    assert '"output_config"' in prompt
    assert '"cache_control"' in prompt
    assert '"inference_geo"' in prompt
    assert "WebSearch/WebFetch" in prompt


def test_messages_to_prompt_writes_images_to_files(tmp_path):
    image_data = base64.b64encode(b"fake-png").decode()
    prompt = app.messages_to_prompt({
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "describe"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_data,
                    },
                },
            ],
        }],
    }, str(tmp_path))
    image_path = tmp_path / "image_1.png"
    assert "describe" in prompt
    assert str(image_path) in prompt
    assert image_path.read_bytes() == b"fake-png"
    assert image_data not in prompt


def test_messages_to_prompt_preserves_image_url_without_source_dump():
    prompt = app.messages_to_prompt({
        "messages": [{
            "role": "user",
            "content": [{
                "type": "image",
                "source": {"type": "url", "url": "https://example.com/image.png"},
            }],
        }],
    })
    assert "https://example.com/image.png" in prompt
    assert '"source"' not in prompt


def test_claude_json_uses_stdin_instead_of_prompt_argument(monkeypatch):
    captured = {}

    class Completed:
        returncode = 0
        stdout = '{"result":"ok"}'
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["input"] = kwargs.get("input")
        return Completed()

    monkeypatch.setattr(app.subprocess, "run", fake_run)
    assert app.run_claude_json("x" * 2_000_000, "sonnet")["result"] == "ok"
    assert captured["input"] == "x" * 2_000_000
    assert "x" * 1000 not in captured["command"]


def test_litellm_config_keeps_alias_for_claude_proxy(tmp_path, monkeypatch):
    monkeypatch.setattr("proxy_stack.flows.runtime_dir", lambda: tmp_path)
    cfg = ProxyConfig(flows=[{
        "id": "claude_test",
        "enabled": True,
        "source": {"kind": "local", "provider": "claude"},
        "middle": {"kind": "litellm"},
        "outputs": [{"format": "anthropic", "port": 4000, "api_key": "litellm-local-test-key"}],
        "models": [{"name": "claude-code-opus-4-7-xhigh", "upstream": "claude-code-opus-4-7-xhigh"}],
    }]).normalized()
    path = generate_litellm_config_for_port(cfg, 4000)
    text = path.read_text(encoding="utf-8")
    assert "model_name: claude-code-opus-4-7-xhigh" in text
    assert "model: anthropic/claude-code-opus-4-7-xhigh" in text
    assert "api_base: http://127.0.0.1:39123" in text
    assert "timeout: 900" in text
    assert "stream_timeout: 900" in text
    assert "request_timeout: 900" in text


def test_litellm_config_keeps_each_local_provider_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr("proxy_stack.flows.runtime_dir", lambda: tmp_path)
    cfg = ProxyConfig(flows=[
        {
            "id": "codex_test",
            "enabled": True,
            "source": {"kind": "local", "provider": "codex"},
            "middle": {"kind": "litellm"},
            "outputs": [{"format": "anthropic", "port": 4000, "api_key": "litellm-local-test-key"}],
            "models": [{"name": "gpt-5.5", "upstream": "gpt-5.5"}],
        },
        {
            "id": "gemini_test",
            "enabled": True,
            "source": {"kind": "local", "provider": "gemini"},
            "middle": {"kind": "litellm"},
            "outputs": [{"format": "anthropic", "port": 4000, "api_key": "litellm-local-test-key"}],
            "models": [{"name": "gemini-2.5-pro", "upstream": "gemini-2.5-pro"}],
        },
        {
            "id": "claude_test",
            "enabled": True,
            "source": {"kind": "local", "provider": "claude"},
            "middle": {"kind": "litellm"},
            "outputs": [{"format": "anthropic", "port": 4000, "api_key": "litellm-local-test-key"}],
            "models": [{"name": "claude-code-opus-4-7-xhigh", "upstream": "claude-code-opus-4-7-xhigh"}],
        },
    ]).normalized()
    text = generate_litellm_config_for_port(cfg, 4000).read_text(encoding="utf-8")
    assert "model: openai/gpt-5.5" in text
    assert "api_base: http://127.0.0.1:39121/v1" in text
    assert "model: gemini/gemini-2.5-pro" in text
    assert "api_base: http://127.0.0.1:39122/v1beta" in text
    assert "model: anthropic/claude-code-opus-4-7-xhigh" in text
    assert "api_base: http://127.0.0.1:39123" in text


def test_litellm_config_uses_full_model_names_for_external_claude_api(tmp_path, monkeypatch):
    monkeypatch.setattr("proxy_stack.flows.runtime_dir", lambda: tmp_path)
    cfg = ProxyConfig(flows=[{
        "id": "external_claude_api",
        "enabled": True,
        "source": {
            "kind": "external",
            "format": "anthropic",
            "base_url": "https://example.com/api/claudecode",
            "api_key": "test-key",
        },
        "middle": {"kind": "litellm"},
        "outputs": [{"format": "anthropic", "port": 4000, "api_key": "litellm-local-test-key"}],
        "models": [{"name": "sonnet", "upstream": "claude-sonnet-4-6"}],
    }]).normalized()

    text = generate_litellm_config_for_port(cfg, 4000).read_text(encoding="utf-8")
    assert "model_name: sonnet" in text
    assert "model: anthropic/claude-sonnet-4-6" in text
    assert "api_base: https://example.com/api/claudecode" in text
    assert "api_key: os.environ/PE_EXTERNAL_CLAUDE_API_API_KEY" in text


def test_litellm_config_passes_reasoning_effort_for_external_claude_api(tmp_path, monkeypatch):
    monkeypatch.setattr("proxy_stack.flows.runtime_dir", lambda: tmp_path)
    cfg = ProxyConfig(flows=[{
        "id": "external_claude_api",
        "enabled": True,
        "source": {
            "kind": "external",
            "format": "anthropic",
            "base_url": "https://example.com/api/claudecode",
            "api_key": "test-key",
        },
        "middle": {"kind": "litellm"},
        "outputs": [{"format": "anthropic", "port": 4000, "api_key": "litellm-local-test-key"}],
        "models": [{"name": "claude-code-opus-4-7-xhigh", "upstream": "claude-opus-4-7", "effort": "xhigh"}],
    }]).normalized()

    text = generate_litellm_config_for_port(cfg, 4000).read_text(encoding="utf-8")
    assert "model_name: claude-code-opus-4-7-xhigh" in text
    assert "model: anthropic/claude-opus-4-7" in text
    assert "reasoning_effort: xhigh" in text


def test_litellm_config_migrates_stale_external_claude_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr("proxy_stack.flows.runtime_dir", lambda: tmp_path)
    cfg = ProxyConfig(flows=[{
        "id": "external_claude_api",
        "enabled": True,
        "source": {
            "kind": "external",
            "format": "anthropic",
            "base_url": "https://example.com/api/claudecode",
            "api_key": "test-key",
        },
        "middle": {"kind": "litellm"},
        "outputs": [{"format": "anthropic", "port": 4000, "api_key": "litellm-local-test-key"}],
        "models": [{"name": "opus", "upstream": "opus"}, {"name": "claude-code-opus-4-7-xhigh", "upstream": "claude-code-opus-4-7-xhigh"}],
    }]).normalized()

    text = generate_litellm_config_for_port(cfg, 4000).read_text(encoding="utf-8")
    assert "model_name: opus" in text
    assert "model: anthropic/claude-opus-4-7" in text
    assert "model_name: claude-code-opus-4-7-xhigh" in text
    assert "reasoning_effort: xhigh" in text
    assert "model: anthropic/opus" not in text
    assert "model: anthropic/claude-code-opus-4-7-xhigh" not in text


def test_litellm_config_uses_explicit_claude_code_api_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr("proxy_stack.flows.runtime_dir", lambda: tmp_path)
    cfg = ProxyConfig(flows=[{
        "id": "external_claude_api",
        "enabled": True,
        "source": {
            "kind": "external",
            "format": "anthropic",
            "adapter": "claude-code-api-to-anthropic",
            "base_url": "https://example.com/api/claudecode",
            "api_key": "test-key",
            "local_port": 39124,
            "local_api_key": "local-key",
        },
        "middle": {"kind": "litellm"},
        "outputs": [{"format": "anthropic", "port": 4000, "api_key": "litellm-local-test-key"}],
        "models": [{"name": "claude-code-sonnet-high", "upstream": "claude-code-sonnet-high"}],
    }]).normalized()

    text = generate_litellm_config_for_port(cfg, 4000).read_text(encoding="utf-8")
    assert "model_name: claude-code-sonnet-high" in text
    assert "model: anthropic/claude-sonnet-4-6" in text
    assert "api_base: http://127.0.0.1:39124" in text
    assert "api_key: os.environ/PE_EXTERNAL_CLAUDE_API_LOCAL_API_KEY" in text
    assert "reasoning_effort: high" in text


def test_litellm_config_keeps_legacy_claude_api_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr("proxy_stack.flows.runtime_dir", lambda: tmp_path)
    cfg = ProxyConfig(flows=[{
        "id": "external_claude_api",
        "enabled": True,
        "source": {
            "kind": "external",
            "format": "anthropic",
            "adapter": "claude-api-to-anthropic",
            "base_url": "https://example.com/api/claudecode",
            "api_key": "test-key",
        },
        "middle": {"kind": "litellm"},
        "outputs": [{"format": "anthropic", "port": 4000, "api_key": "litellm-local-test-key"}],
        "models": [{"name": "claude-code-opus-high", "upstream": "claude-code-opus-high"}],
    }]).normalized()

    text = generate_litellm_config_for_port(cfg, 4000).read_text(encoding="utf-8")
    assert "model: anthropic/claude-opus-4-7" in text
    assert "reasoning_effort: high" in text
