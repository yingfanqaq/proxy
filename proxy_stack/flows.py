from __future__ import annotations

import os
import re
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

from .config import ProxyConfig, runtime_dir


LOCAL_SOURCE_PROVIDERS = {"codex", "gemini", "claude"}
SOURCE_FORMATS = {"codex": "openai", "gemini": "gemini", "claude": "anthropic"}
REASONING_EFFORT_ALIASES = {
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
}
EXTERNAL_ANTHROPIC_MODEL_ALIASES = {
    "claude-code": "claude-sonnet-4-6",
    "claude-api": "claude-sonnet-4-6",
    "claude-code-sonnet": "claude-sonnet-4-6",
    "sonnet": "claude-sonnet-4-6",
    "claude-code-opus": "claude-opus-4-7",
    "opus": "claude-opus-4-7",
    "claude-code-haiku": "claude-haiku-4-5",
    "haiku": "claude-haiku-4-5",
    "claude-code-sonnet-4-6": "claude-sonnet-4-6",
    "claude-code-opus-4-7": "claude-opus-4-7",
    "claude-code-opus-4-6": "claude-opus-4-6",
    "claude-code-haiku-4-5": "claude-haiku-4-5",
}


def default_flows() -> list[dict[str, Any]]:
    return [
        {
            "id": "codex_to_anthropic",
            "name": "Codex to Anthropic",
            "enabled": True,
            "source": {"kind": "local", "provider": "codex"},
            "middle": {"kind": "litellm"},
            "outputs": [{"format": "anthropic", "port": 4000, "api_key": "litellm-local-test-key"}],
            "models": [
                {"name": "codex", "upstream": "gpt-5.5"},
                {"name": "gpt-5.5", "upstream": "gpt-5.5"},
                {"name": "gpt-5.4", "upstream": "gpt-5.4"},
                {"name": "gpt-5.4-mini", "upstream": "gpt-5.4-mini"},
                {"name": "gpt-5.3-codex", "upstream": "gpt-5.3-codex"},
                {"name": "gpt-5.2", "upstream": "gpt-5.2"},
            ],
            "layout": {
                "source": {"x": 60, "y": 90},
                "middle": {"x": 330, "y": 90},
                "output": {"x": 600, "y": 90},
            },
        },
        {
            "id": "gemini_to_anthropic",
            "name": "Gemini to Anthropic",
            "enabled": True,
            "source": {"kind": "local", "provider": "gemini"},
            "middle": {"kind": "litellm"},
            "outputs": [{"format": "anthropic", "port": 4000, "api_key": "litellm-local-test-key"}],
            "models": [
                {"name": "gemini", "upstream": "gemini-3.1-pro-preview"},
                {"name": "gemini-3.1-pro-preview", "upstream": "gemini-3.1-pro-preview"},
                {"name": "gemini-3-flash", "upstream": "gemini-3-flash-preview"},
                {"name": "gemini-3-flash-preview", "upstream": "gemini-3-flash-preview"},
                {"name": "gemini-3.1-flash-lite-preview", "upstream": "gemini-3.1-flash-lite-preview"},
                {"name": "gemini-2.5-pro", "upstream": "gemini-2.5-pro"},
                {"name": "gemini-2.5-flash", "upstream": "gemini-2.5-flash"},
                {"name": "gemini-2.5-flash-lite", "upstream": "gemini-2.5-flash-lite"},
            ],
            "layout": {
                "source": {"x": 60, "y": 230},
                "middle": {"x": 330, "y": 230},
                "output": {"x": 600, "y": 230},
            },
        },
        {
            "id": "claude_code_to_anthropic",
            "name": "Claude Code to Anthropic",
            "enabled": True,
            "source": {"kind": "local", "provider": "claude"},
            "middle": {"kind": "litellm"},
            "outputs": [{"format": "anthropic", "port": 4000, "api_key": "litellm-local-test-key"}],
            "models": [
                {"name": "claude-code", "upstream": "claude-code"},
                {"name": "claude-code-sonnet", "upstream": "sonnet"},
                {"name": "claude-code-opus", "upstream": "opus"},
                {"name": "claude-code-haiku", "upstream": "haiku"},
                {"name": "claude-code-opus-4-7", "upstream": "claude-code-opus-4-7"},
                {"name": "claude-code-opus-4-7-high", "upstream": "claude-code-opus-4-7-high"},
                {"name": "claude-code-opus-4-7-xhigh", "upstream": "claude-code-opus-4-7-xhigh"},
                {"name": "claude-code-opus-4-6", "upstream": "claude-code-opus-4-6"},
                {"name": "claude-code-opus-4-6-high", "upstream": "claude-code-opus-4-6-high"},
                {"name": "claude-code-sonnet-4-6", "upstream": "claude-code-sonnet-4-6"},
                {"name": "claude-code-sonnet-4-6-high", "upstream": "claude-code-sonnet-4-6-high"},
            ],
            "layout": {
                "source": {"x": 60, "y": 370},
                "middle": {"x": 330, "y": 370},
                "output": {"x": 600, "y": 370},
            },
        },
        {
            "id": "claude_code_to_openai",
            "name": "Claude Code to OpenAI",
            "enabled": False,
            "source": {"kind": "local", "provider": "claude"},
            "middle": {"kind": "litellm"},
            "outputs": [{"format": "openai", "port": 4001, "api_key": "litellm-local-test-key"}],
            "models": [
                {"name": "claude-code", "upstream": "claude-code"},
                {"name": "claude-code-sonnet", "upstream": "sonnet"},
                {"name": "claude-code-opus-4-7", "upstream": "claude-code-opus-4-7"},
                {"name": "claude-code-opus-4-7-high", "upstream": "claude-code-opus-4-7-high"},
                {"name": "claude-code-sonnet-4-6", "upstream": "claude-code-sonnet-4-6"},
                {"name": "claude-code-sonnet-4-6-high", "upstream": "claude-code-sonnet-4-6-high"},
            ],
            "layout": {
                "source": {"x": 60, "y": 510},
                "middle": {"x": 330, "y": 510},
                "output": {"x": 600, "y": 510},
            },
        },
    ]


def normalized_flows(flows: Any) -> list[dict[str, Any]]:
    source = deepcopy(flows) if isinstance(flows, list) else default_flows()
    defaults = {flow["id"]: flow for flow in default_flows()}
    merged: list[dict[str, Any]] = []
    for flow in source:
        if not isinstance(flow, dict):
            continue
        base = deepcopy(defaults.get(str(flow.get("id")), {}))
        base.update(flow)
        base.setdefault("enabled", True)
        base.setdefault("middle", {"kind": "litellm"})
        base.setdefault("outputs", [])
        base.setdefault("models", [])
        default_models = defaults.get(str(flow.get("id")), {}).get("models", [])
        existing_model_names = {str(model.get("name")) for model in base["models"] if isinstance(model, dict)}
        for model in default_models:
            if isinstance(model, dict) and str(model.get("name")) not in existing_model_names:
                base["models"].append(deepcopy(model))
                existing_model_names.add(str(model.get("name")))
        base.setdefault("layout", {})
        merged.append(base)
    return merged or default_flows()


def slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").upper() or "FLOW"


def local_source_base(config: ProxyConfig, provider: str) -> tuple[str, str, str]:
    if provider == "codex":
        return f"http://{config.host}:{config.codex_port}/v1", "CODEX_PROXY_API_KEY", "openai"
    if provider == "gemini":
        return f"http://{config.host}:{config.gemini_port}/v1beta", "GEMINI_PROXY_API_KEY", "gemini"
    if provider == "claude":
        return f"http://{config.host}:{config.claude_port}", "CLAUDE_PROXY_API_KEY", "anthropic"
    raise ValueError(f"Unsupported local source provider: {provider}")


def source_details(config: ProxyConfig, flow: dict[str, Any]) -> dict[str, str]:
    source = flow.get("source", {})
    if source.get("kind") == "external":
        fmt = source.get("format", "openai")
        env_key = f"PE_{slug(flow.get('id', 'flow'))}_API_KEY"
        return {"api_base": source.get("base_url", ""), "api_key_ref": f"os.environ/{env_key}", "format": fmt, "env_key": env_key, "env_value": source.get("api_key", "")}
    provider = source.get("provider", "codex")
    api_base, key_name, fmt = local_source_base(config, provider)
    return {"api_base": api_base, "api_key_ref": f"os.environ/{key_name}", "format": fmt, "env_key": key_name, "env_value": getattr(config, key_name.lower())}


def litellm_model_prefix(source_format: str) -> str:
    if source_format == "gemini":
        return "gemini"
    if source_format == "anthropic":
        return "anthropic"
    return "openai"


def enabled_flows_for_port(config: ProxyConfig, port: int) -> list[dict[str, Any]]:
    return [
        flow
        for flow in normalized_flows(config.flows)
        if flow.get("enabled", True) and any(int(output.get("port", config.litellm_port)) == port for output in flow.get("outputs", []))
    ]


def output_ports(config: ProxyConfig) -> list[int]:
    ports: set[int] = set()
    for flow in normalized_flows(config.flows):
        if not flow.get("enabled", True):
            continue
        for output in flow.get("outputs", []):
            ports.add(int(output.get("port", config.litellm_port)))
    return sorted(ports or {config.litellm_port})


def local_providers_used(config: ProxyConfig) -> set[str]:
    providers: set[str] = set()
    for flow in normalized_flows(config.flows):
        if flow.get("enabled", True) and flow.get("source", {}).get("kind") == "local":
            provider = flow.get("source", {}).get("provider")
            if provider in LOCAL_SOURCE_PROVIDERS:
                providers.add(provider)
    return providers


def litellm_env_for_port(config: ProxyConfig, port: int) -> dict[str, str]:
    env = {
        "CODEX_PROXY_API_KEY": config.codex_proxy_api_key,
        "GEMINI_PROXY_API_KEY": config.gemini_proxy_api_key,
        "CLAUDE_PROXY_API_KEY": config.claude_proxy_api_key,
        "LITELLM_MASTER_KEY": output_api_key(config, port),
        "REQUEST_TIMEOUT": str(litellm_request_timeout()),
    }
    for flow in enabled_flows_for_port(config, port):
        details = source_details(config, flow)
        if details.get("env_key") and details.get("env_value"):
            env[details["env_key"]] = details["env_value"]
    return env


def output_api_key(config: ProxyConfig, port: int) -> str:
    for flow in normalized_flows(config.flows):
        for output in flow.get("outputs", []):
            if int(output.get("port", config.litellm_port)) == port:
                return str(output.get("api_key") or config.litellm_master_key)
    return config.litellm_master_key


def output_formats_for_port(config: ProxyConfig, port: int) -> list[str]:
    formats: set[str] = set()
    for flow in enabled_flows_for_port(config, port):
        for output in flow.get("outputs", []):
            if int(output.get("port", config.litellm_port)) == port:
                formats.add(str(output.get("format", "anthropic")))
    return sorted(formats or {"anthropic"})


def litellm_request_timeout() -> int:
    try:
        return max(600, int(os.environ.get("CLAUDE_TIMEOUT", "900")))
    except ValueError:
        return 900


def model_reasoning_effort(model: dict[str, Any]) -> str | None:
    raw = str(model.get("reasoning_effort") or model.get("effort") or "").strip().lower()
    return REASONING_EFFORT_ALIASES.get(raw)


def split_reasoning_effort(value: Any) -> tuple[str, str | None]:
    text = str(value or "").strip()
    for effort in REASONING_EFFORT_ALIASES:
        suffix = f"-{effort}"
        if text.endswith(suffix):
            return text[: -len(suffix)], REASONING_EFFORT_ALIASES[effort]
    return text, None


def external_anthropic_upstream_and_effort(model: dict[str, Any]) -> tuple[str, str | None]:
    upstream, upstream_effort = split_reasoning_effort(model.get("upstream", model.get("name")))
    normalized = EXTERNAL_ANTHROPIC_MODEL_ALIASES.get(upstream, upstream)
    return normalized, model_reasoning_effort(model) or upstream_effort


def uses_claude_api_adapter(flow: dict[str, Any], source_format: str) -> bool:
    source = flow.get("source", {})
    if source.get("kind") != "external" or source_format != "anthropic":
        return False
    adapter = str(source.get("adapter") or "").strip().lower()
    if adapter:
        return adapter in {"claude-api-to-anthropic", "claude-code-to-anthropic"}
    return True


def generate_litellm_config_for_port(config: ProxyConfig, port: int) -> Path:
    path = runtime_dir() / f"litellm-flow-{port}.generated.yaml"
    request_timeout = litellm_request_timeout()
    lines: list[str] = ["model_list:"]
    for flow in enabled_flows_for_port(config, port):
        details = source_details(config, flow)
        prefix = litellm_model_prefix(details["format"])
        external_anthropic = uses_claude_api_adapter(flow, details["format"])
        for model in flow.get("models", []):
            model_name = model.get("name")
            upstream = model.get("upstream", model_name)
            reasoning_effort = model_reasoning_effort(model) if isinstance(model, dict) else None
            if external_anthropic and isinstance(model, dict):
                upstream, reasoning_effort = external_anthropic_upstream_and_effort(model)
            if not model_name or not upstream:
                continue
            lines.extend(
                [
                    f"  - model_name: {model_name}",
                    "    litellm_params:",
                    f"      model: {prefix}/{upstream}",
                    f"      api_base: {details['api_base']}",
                    f"      api_key: {details['api_key_ref']}",
                    f"      timeout: {request_timeout}",
                    f"      stream_timeout: {request_timeout}",
                ]
            )
            if reasoning_effort:
                lines.append(f"      reasoning_effort: {reasoning_effort}")
            lines.append("")
    if len(lines) == 1:
        lines.extend(
            [
                "  - model_name: empty-flow-placeholder",
                "    litellm_params:",
                "      model: openai/empty-flow-placeholder",
                "      api_base: http://127.0.0.1:1/v1",
                "      api_key: none",
                f"      timeout: {request_timeout}",
                f"      stream_timeout: {request_timeout}",
                "",
            ]
        )
    lines.extend(
        [
            "general_settings:",
            "  master_key: os.environ/LITELLM_MASTER_KEY",
            "",
            "router_settings:",
            f"  timeout: {request_timeout}",
            f"  stream_timeout: {request_timeout}",
            "",
            "litellm_settings:",
            "  drop_params: true",
            f"  request_timeout: {request_timeout}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def flow_summary(config: ProxyConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for flow in normalized_flows(config.flows):
        source = flow.get("source", {})
        rows.append(
            {
                "id": flow.get("id"),
                "name": flow.get("name"),
                "enabled": bool(flow.get("enabled", True)),
                "source": source.get("provider") or source.get("format") or source.get("kind"),
                "outputs": flow.get("outputs", []),
                "models": [model.get("name") for model in flow.get("models", [])],
            }
        )
    return rows
