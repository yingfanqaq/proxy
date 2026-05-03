from __future__ import annotations

import importlib.util
from pathlib import Path

from proxy_stack.config import ProxyConfig
from proxy_stack.flows import generate_litellm_config_for_port

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
