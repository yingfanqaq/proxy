from __future__ import annotations

import argparse
import platform
import threading
import time
import webbrowser

from . import APP_NAME
from .config import load_config
from .manager import restart_all, start_all, status, stop_all
from .settings_server import start_settings_server


def _status_title() -> str:
    items = status()
    if all(item["healthy"] for item in items.values()):
        return "Status: running"
    if any(item["healthy"] for item in items.values()):
        return "Status: partial"
    return "Status: stopped"


def _make_icon_image():
    from PIL import Image, ImageDraw

    size = 22
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Left node
    draw.ellipse((1, 3, 7, 9), fill=(0, 0, 0, 255))
    draw.ellipse((1, 12, 7, 18), fill=(0, 0, 0, 255))
    # Center node
    draw.ellipse((8, 7, 14, 13), fill=(0, 0, 0, 255))
    # Right node
    draw.ellipse((15, 3, 21, 9), fill=(0, 0, 0, 255))
    draw.ellipse((15, 12, 21, 18), fill=(0, 0, 0, 255))
    # Lines: left nodes -> center
    draw.line((7, 6, 9, 10), fill=(0, 0, 0, 255), width=1)
    draw.line((7, 15, 9, 10), fill=(0, 0, 0, 255), width=1)
    # Lines: center -> right nodes
    draw.line((14, 10, 16, 6), fill=(0, 0, 0, 255), width=1)
    draw.line((14, 10, 16, 15), fill=(0, 0, 0, 255), width=1)
    return image


def _make_icon_bytes() -> bytes:
    import io
    image = _make_icon_image()
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def run_tray_rumps(settings_url: str) -> None:
    import rumps

    icon_path = None
    try:
        import tempfile
        icon_data = _make_icon_bytes()
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(icon_data)
        tmp.close()
        icon_path = tmp.name
    except Exception:
        pass

    class ProxyApp(rumps.App):
        def __init__(self):
            super().__init__(
                APP_NAME,
                icon=icon_path,
                template=True,
                menu=[
                    rumps.MenuItem("Flow Editor...", callback=self.open_flow_editor),
                    rumps.MenuItem("Settings...", callback=self.open_settings),
                    None,
                    rumps.MenuItem("Start Services", callback=self.do_start),
                    rumps.MenuItem("Restart Services", callback=self.do_restart),
                    rumps.MenuItem("Stop Services", callback=self.do_stop),
                    None,
                    rumps.MenuItem("Status: checking...", callback=None),
                ],
            )
            self._settings_url = settings_url
            self._update_timer = rumps.Timer(self.update_status, 10)
            self._update_timer.start()

        def open_flow_editor(self, _sender):
            threading.Thread(target=self._launch_ui, daemon=True).start()

        def _launch_ui(self):
            import subprocess, sys
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable, "ui"])
            else:
                subprocess.Popen([sys.executable, "-m", "proxy_stack", "ui"])

        def open_settings(self, _sender):
            webbrowser.open(self._settings_url)

        def do_start(self, _sender):
            threading.Thread(target=start_all, daemon=True).start()

        def do_restart(self, _sender):
            threading.Thread(target=restart_all, daemon=True).start()

        def do_stop(self, _sender):
            threading.Thread(target=stop_all, daemon=True).start()

        def update_status(self, _sender):
            try:
                title = _status_title()
                for key, item in self.menu.items():
                    if isinstance(item, rumps.MenuItem) and item.title.startswith("Status:"):
                        item.title = title
                        break
            except Exception:
                pass

    ProxyApp().run()


def run_tray_pystray(settings_url: str) -> None:
    import pystray

    def open_settings(_icon=None, _item=None):
        webbrowser.open(settings_url)

    def start_services(_icon=None, _item=None):
        start_all()

    def stop_services(_icon=None, _item=None):
        stop_all()

    def restart_services(_icon=None, _item=None):
        restart_all()

    def quit_app(icon, _item=None):
        stop_all()
        icon.stop()

    icon = pystray.Icon(
        "proxyeverywhere",
        _make_icon_image(),
        APP_NAME,
        menu=pystray.Menu(
            pystray.MenuItem(lambda _item: _status_title(), None, enabled=False),
            pystray.MenuItem("Settings...", open_settings, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start Services", start_services),
            pystray.MenuItem("Restart Services", restart_services),
            pystray.MenuItem("Stop Services", stop_services),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Quit {APP_NAME}", quit_app),
        ),
    )
    icon.run()


def run_tray(settings_url: str) -> None:
    if platform.system() == "Darwin":
        try:
            run_tray_rumps(settings_url)
            return
        except ImportError:
            pass
    run_tray_pystray(settings_url)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--start-services", action="store_true")
    parser.add_argument("--open-settings", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_config()
    if args.start_services or cfg.start_services_on_app_launch:
        threading.Thread(target=start_all, args=(cfg,), daemon=True).start()
    server, settings_url = start_settings_server()
    if args.open_settings or cfg.open_settings_on_start:
        webbrowser.open(settings_url)
    try:
        run_tray(settings_url)
    except Exception as exc:
        print(f"{APP_NAME}: tray icon unavailable ({exc}); settings page is running at {settings_url}", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
