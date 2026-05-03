from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


codex_app = load_module("codex_chat_proxy_app", ROOT / "codex-chat-proxy" / "app.py")
gemini_app = load_module("gemini_genai_proxy_app", ROOT / "gemini-genai-proxy" / "app.py")


def test_codex_chat_maps_openai_controls_to_responses_payload():
    payload = {
        "model": "gpt-5.5",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 12,
        "temperature": 0.2,
        "top_p": 0.8,
        "tool_choice": {"type": "function", "function": {"name": "lookup"}},
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Lookup a value",
                    "parameters": {"type": "object", "properties": {}},
                    "strict": True,
                },
            }
        ],
        "parallel_tool_calls": False,
        "background": True,
        "store": True,
        "stream_options": {"include_usage": True, "include_obfuscation": False},
        "prompt_cache_retention": "24h",
        "reasoning_effort": "max",
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": {"type": "object"}, "strict": True},
        },
        "user": "user-123",
    }
    converted = codex_app.chat_to_responses(payload)
    assert converted["max_output_tokens"] == 12
    assert converted["temperature"] == 0.2
    assert converted["top_p"] == 0.8
    assert converted["tool_choice"] == {"type": "function", "name": "lookup"}
    assert converted["tools"][0]["strict"] is True
    assert converted["parallel_tool_calls"] is False
    assert converted["background"] is True
    assert converted["store"] is True
    assert converted["stream_options"] == {"include_obfuscation": False}
    assert converted["prompt_cache_retention"] == "24h"
    assert converted["reasoning"] == {"effort": "xhigh"}
    assert converted["text"]["format"]["type"] == "json_schema"
    assert converted["safety_identifier"] == "user-123"


def test_codex_responses_sanitizer_keeps_native_response_fields():
    sanitized = codex_app.sanitize_responses_payload({
        "model": "gpt-5.5",
        "input": "hi",
        "max_tokens": 9,
        "tool_choice": "auto",
        "metadata": {"flow": "codex"},
        "background": True,
        "store": True,
        "stream_options": {"include_usage": True, "include_obfuscation": False},
        "prompt_cache_retention": "24h",
        "reasoning_effort": "minimal",
        "response_format": {"type": "json_object"},
        "user": "user-456",
    })
    assert sanitized["max_output_tokens"] == 9
    assert sanitized["tool_choice"] == "auto"
    assert sanitized["metadata"] == {"flow": "codex"}
    assert sanitized["background"] is True
    assert sanitized["store"] is True
    assert sanitized["stream_options"] == {"include_obfuscation": False}
    assert sanitized["prompt_cache_retention"] == "24h"
    assert sanitized["reasoning"] == {"effort": "minimal"}
    assert sanitized["text"] == {"format": {"type": "json_object"}}
    assert sanitized["safety_identifier"] == "user-456"
    assert "max_tokens" not in sanitized
    assert "response_format" not in sanitized
    assert "reasoning_effort" not in sanitized
    assert "user" not in sanitized


def test_codex_auth_supports_openai_api_key_fallback():
    info = codex_app.auth_info_from_payload({"OPENAI_API_KEY": "sk-test"})
    assert info == {"mode": "openai_api_key", "api_key": "sk-test"}


def test_gemini_generate_content_preserves_native_request_fields():
    body = {
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
        "systemInstruction": {"parts": [{"text": "system"}]},
        "tools": [{"functionDeclarations": [{"name": "lookup"}]}],
        "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
        "generationConfig": {"temperature": 0.1},
        "safetySettings": [{"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}],
        "cachedContent": "cachedContents/test",
    }
    wrapped = gemini_app.make_code_assist_request("models/gemini-2.5-pro", body, "project-id")
    assert wrapped["model"] == "gemini-2.5-pro"
    assert wrapped["project"] == "project-id"
    assert wrapped["request"] == body


def test_gemini_count_tokens_preserves_native_count_request_fields():
    body = {
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
        "systemInstruction": {"parts": [{"text": "system"}]},
        "tools": [{"functionDeclarations": [{"name": "lookup"}]}],
        "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
        "generationConfig": {"temperature": 0},
        "safetySettings": [{"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"}],
        "cachedContent": "cachedContents/test",
    }
    wrapped = gemini_app.count_tokens_request("gemini-2.5-pro", body)
    request = wrapped["request"]
    assert request["model"] == "models/gemini-2.5-pro"
    for key, value in body.items():
        assert request[key] == value
