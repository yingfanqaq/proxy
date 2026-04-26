from __future__ import annotations

import html
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from . import APP_NAME
from . import autostart, manager
from .config import ProxyConfig, env_snippets, load_config, save_config


def _field(name: str, value: object, label: str, input_type: str = "text") -> str:
    safe_name = html.escape(name)
    safe_value = html.escape(str(value))
    safe_label = html.escape(label)
    return f'<label><span>{safe_label}</span><input name="{safe_name}" type="{input_type}" value="{safe_value}"></label>'


def _checkbox(name: str, checked: bool, label: str) -> str:
    attr = " checked" if checked else ""
    return f'<label class="check"><input name="{html.escape(name)}" type="checkbox" value="1"{attr}> {html.escape(label)}</label>'


def render_page(message: str = "") -> bytes:
    cfg = load_config()
    statuses = manager.status(cfg)
    snippets = env_snippets(cfg)
    rows = []
    for name, item in statuses.items():
        state = "healthy" if item["healthy"] else "down"
        rows.append(
            f"<tr><td>{html.escape(name)}</td><td>{state}</td><td>{item['port']}</td><td><code>{html.escape(str(item['log']))}</code></td></tr>"
        )
    message_html = f'<p class="message">{html.escape(message)}</p>' if message else ""
    autostart_checked = autostart.is_installed()
    page = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{APP_NAME}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f6f7f8; color: #1f2328; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 28px; }}
    h1 {{ font-size: 24px; margin: 0 0 18px; }}
    h2 {{ font-size: 16px; margin: 24px 0 10px; }}
    section {{ background: white; border: 1px solid #d8dee4; border-radius: 8px; padding: 18px; margin: 14px 0; }}
    form.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px 16px; }}
    label span {{ display: block; font-size: 12px; color: #57606a; margin-bottom: 5px; }}
    input {{ width: 100%; box-sizing: border-box; border: 1px solid #d0d7de; border-radius: 6px; padding: 8px 10px; font-size: 14px; }}
    label.check {{ display: block; margin-top: 12px; color: #24292f; }}
    label.check input {{ width: auto; margin-right: 8px; }}
    button {{ border: 1px solid #1f6feb; background: #1f6feb; color: white; border-radius: 6px; padding: 8px 12px; margin: 10px 8px 0 0; cursor: pointer; }}
    button.secondary {{ background: #f6f8fa; color: #24292f; border-color: #d0d7de; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td, th {{ border-bottom: 1px solid #d8dee4; text-align: left; padding: 8px; font-size: 14px; }}
    code, pre {{ background: #f6f8fa; border-radius: 6px; }}
    pre {{ padding: 12px; overflow: auto; }}
    .message {{ background: #fff8c5; border: 1px solid #eac54f; border-radius: 6px; padding: 10px; }}
  </style>
</head>
<body>
<main>
  <h1>{APP_NAME}</h1>
  {message_html}
  <section>
    <h2>Services</h2>
    <table><tr><th>Name</th><th>Status</th><th>Port</th><th>Log</th></tr>{''.join(rows)}</table>
    <form method="post" action="/action">
      <button name="action" value="start">Start</button>
      <button name="action" value="restart">Restart</button>
      <button class="secondary" name="action" value="stop">Stop</button>
    </form>
  </section>

  <section>
    <h2>Settings</h2>
    <form class="grid" method="post" action="/save">
      {_field("host", cfg.host, "Host")}
      {_field("codex_port", cfg.codex_port, "Codex proxy port", "number")}
      {_field("gemini_port", cfg.gemini_port, "Gemini proxy port", "number")}
      {_field("litellm_port", cfg.litellm_port, "LiteLLM / Anthropic port", "number")}
      {_field("settings_port", cfg.settings_port, "Settings page port", "number")}
      {_field("codex_proxy_api_key", cfg.codex_proxy_api_key, "Codex proxy API key")}
      {_field("gemini_proxy_api_key", cfg.gemini_proxy_api_key, "Gemini proxy API key")}
      {_field("litellm_master_key", cfg.litellm_master_key, "LiteLLM master key")}
      {_field("python_bin", cfg.python_bin, "Python executable")}
      {_field("litellm_bin", cfg.litellm_bin, "LiteLLM executable")}
      {_field("project_root", cfg.project_root, "Project root")}
      <div>
        {_checkbox("start_services_on_app_launch", cfg.start_services_on_app_launch, "Start services when app opens")}
        {_checkbox("open_settings_on_start", cfg.open_settings_on_start, "Open settings page when app opens")}
        {_checkbox("autostart", autostart_checked, "Start app at login")}
      </div>
      <div>
        <button name="save_action" value="save">Save</button>
        <button name="save_action" value="save_restart">Save & Restart Services</button>
      </div>
    </form>
  </section>

  <section>
    <h2>Client Environment Snippets</h2>
    <p>These are optional per-shell snippets. The app stores proxy settings outside <code>.zshrc</code>.</p>
    <h2>OpenAI from Codex proxy</h2><pre>{html.escape(snippets["openai"])}</pre>
    <h2>Gemini from Gemini proxy</h2><pre>{html.escape(snippets["gemini"])}</pre>
    <h2>Claude Code via Codex models</h2><pre>{html.escape(snippets["anthropic_codex"])}</pre>
    <h2>Claude Code via Gemini models</h2><pre>{html.escape(snippets["anthropic_gemini"])}</pre>
  </section>
</main>
</body>
</html>"""
    return page.encode("utf-8")


def _form_value(form: dict[str, list[str]], name: str, default: object) -> object:
    if name not in form:
        return default
    return form[name][0]


def update_from_form(form: dict[str, list[str]]) -> ProxyConfig:
    cfg = load_config()
    cfg.host = str(_form_value(form, "host", cfg.host))
    cfg.codex_port = int(_form_value(form, "codex_port", cfg.codex_port))
    cfg.gemini_port = int(_form_value(form, "gemini_port", cfg.gemini_port))
    cfg.litellm_port = int(_form_value(form, "litellm_port", cfg.litellm_port))
    cfg.settings_port = int(_form_value(form, "settings_port", cfg.settings_port))
    cfg.codex_proxy_api_key = str(_form_value(form, "codex_proxy_api_key", cfg.codex_proxy_api_key))
    cfg.gemini_proxy_api_key = str(_form_value(form, "gemini_proxy_api_key", cfg.gemini_proxy_api_key))
    cfg.litellm_master_key = str(_form_value(form, "litellm_master_key", cfg.litellm_master_key))
    cfg.python_bin = str(_form_value(form, "python_bin", cfg.python_bin))
    cfg.litellm_bin = str(_form_value(form, "litellm_bin", cfg.litellm_bin))
    cfg.project_root = str(_form_value(form, "project_root", cfg.project_root))
    cfg.start_services_on_app_launch = "start_services_on_app_launch" in form
    cfg.open_settings_on_start = "open_settings_on_start" in form
    save_config(cfg)
    if "autostart" in form and not autostart.is_installed():
        autostart.install()
    if "autostart" not in form and autostart.is_installed():
        autostart.uninstall()
    return cfg


class SettingsHandler(BaseHTTPRequestHandler):
    server_version = "LocalAIProxyStack/1.0"

    def _send(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send(render_page())

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        message = ""
        try:
            if self.path == "/save":
                cfg = update_from_form(form)
                message = "Settings saved."
                if form.get("save_action", ["save"])[0] == "save_restart":
                    manager.restart_all(cfg)
                    message = "Settings saved and services restarted."
            elif self.path == "/action":
                action = form.get("action", [""])[0]
                if action == "start":
                    manager.start_all()
                    message = "Services started."
                elif action == "stop":
                    manager.stop_all()
                    message = "Services stopped."
                elif action == "restart":
                    manager.restart_all()
                    message = "Services restarted."
                else:
                    message = "Unknown action."
            self._send(render_page(message))
        except Exception as exc:
            self._send(render_page(f"Error: {exc}"), status=500)

    def log_message(self, format: str, *args: object) -> None:
        return


def start_settings_server() -> tuple[ThreadingHTTPServer, str]:
    cfg = load_config()
    server = ThreadingHTTPServer((cfg.host, cfg.settings_port), SettingsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, cfg.settings_url
