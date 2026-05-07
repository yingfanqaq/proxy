from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from proxy_stack import api_server, manager
from proxy_stack.config import ProxyConfig
from proxy_stack.flows import generate_litellm_config_for_port


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()

    def log_message(self, _format, *_args):
        return


def test_status_detects_pid_from_listening_port_when_pid_file_is_stale(tmp_path, monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(manager, "runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(manager, "log_dir", lambda: tmp_path)
    monkeypatch.setattr(manager, "service_names", lambda _cfg: ("codex",))
    cfg = ProxyConfig(codex_port=port).normalized()

    try:
        result = manager.status(cfg)["codex"]
    finally:
        server.shutdown()
        server.server_close()

    assert result["healthy"] is True
    assert result["alive"] is True
    assert result["pid"] == os.getpid()
    assert result["pid_source"] == "port"


def test_start_service_falls_back_when_launchd_did_not_open_port(tmp_path, monkeypatch):
    calls: list[tuple[object, ...]] = []
    spec = manager.ServiceSpec(
        name="litellm_4000",
        port=4000,
        health_url="http://127.0.0.1:4000/health/readiness",
        log_path=tmp_path / "litellm.log",
        pid_path=tmp_path / "litellm.pid",
        cwd=tmp_path,
        command=["python", "app.py"],
        env={},
    )

    monkeypatch.setattr(manager, "status", lambda _cfg: {"litellm_4000": {"healthy": False}})
    monkeypatch.setattr(manager, "service_spec", lambda _name, _cfg: spec)
    monkeypatch.setattr(manager, "_mac_launchd_service_path", lambda _name: ("label", tmp_path / "service.plist"))
    (tmp_path / "service.plist").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(manager.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(manager, "_wait_for_health", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(manager, "port_open", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(manager, "_start_process", lambda _spec, _attempts, extra=None: {"started": True, **(extra or {})})

    result = manager.start_service("litellm_4000", ProxyConfig())
    assert result["started"] is True
    assert result["via"] == "subprocess"
    assert result["launchd_unhealthy"] is True
    assert calls



def test_start_service_boots_out_launchd_when_existing_port_is_healthy(tmp_path, monkeypatch):
    calls: list[tuple[object, ...]] = []
    spec = manager.ServiceSpec(
        name="claude",
        port=39123,
        health_url="http://127.0.0.1:39123/health",
        log_path=tmp_path / "claude.log",
        pid_path=tmp_path / "claude.pid",
        cwd=tmp_path,
        command=["python", "app.py"],
        env={},
    )

    monkeypatch.setattr(manager, "status", lambda _cfg: {"claude": {"healthy": False}})
    monkeypatch.setattr(manager, "service_spec", lambda _name, _cfg: spec)
    monkeypatch.setattr(manager, "_mac_launchd_service_path", lambda _name: ("label", tmp_path / "service.plist"))
    (tmp_path / "service.plist").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(manager.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(manager, "_wait_for_health", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(manager, "port_open", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(manager, "listen_pid", lambda _port: 12345)
    monkeypatch.setattr(manager, "health_ok", lambda *_args, **_kwargs: True)

    result = manager.start_service("claude", ProxyConfig())
    assert result["healthy"] is True
    assert result["via"] == "existing-port"
    assert result["launchd_booted_out"] is True
    assert spec.pid_path.read_text(encoding="utf-8") == "12345"
    assert any(call[0][0] == "launchctl" and call[0][1] == "bootout" for call in calls)


def test_litellm_config_uses_custom_local_proxy_port(tmp_path, monkeypatch):
    monkeypatch.setattr("proxy_stack.flows.runtime_dir", lambda: tmp_path)
    cfg = ProxyConfig(
        codex_port=39125,
        flows=[
            {
                "id": "custom_codex_port",
                "enabled": True,
                "source": {"kind": "local", "provider": "codex"},
                "middle": {"kind": "litellm"},
                "outputs": [{"format": "anthropic", "port": 4000, "api_key": "litellm-local-test-key"}],
                "models": [{"name": "gpt-5.5", "upstream": "gpt-5.5"}],
            }
        ],
    ).normalized()

    text = generate_litellm_config_for_port(cfg, 4000).read_text(encoding="utf-8")
    assert "api_base: http://127.0.0.1:39125/v1" in text
    assert "api_base: http://127.0.0.1:39121/v1" not in text


class ClaudeCompatHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'{"error":"models not supported"}')

    def do_POST(self):
        if self.path == "/v1/messages" and self.headers.get("x-api-key") == "test-key":
            length = int(self.headers.get("content-length", "0"))
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"id": "msg_test", "content": [{"type": "text", "text": "ok"}]}).encode())
            return
        self.send_response(401)
        self.end_headers()

    def log_message(self, _format, *_args):
        return


def test_external_claude_api_accepts_messages_when_models_missing():
    server = ThreadingHTTPServer(("127.0.0.1", 0), ClaudeCompatHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = api_server.test_external_api_source({
            "provider": "anthropic",
            "baseUrl": f"http://127.0.0.1:{port}",
            "apiKey": "test-key",
        })
    finally:
        server.shutdown()
        server.server_close()

    assert result["ok"] is True
    assert "Anthropic messages" in result["detail"]
    assert result["attempts"][0]["label"] == "list_models"
    assert result["attempts"][0]["ok"] is False
    assert result["attempts"][1]["label"].startswith("messages:")
    assert result["attempts"][1]["ok"] is True
