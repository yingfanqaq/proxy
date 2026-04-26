from __future__ import annotations

import argparse
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

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((6, 6, 58, 58), radius=14, fill=(31, 111, 235, 255))
    draw.ellipse((20, 20, 44, 44), fill=(255, 255, 255, 255))
    draw.rectangle((30, 14, 36, 50), fill=(255, 255, 255, 255))
    return image


def run_tray(settings_url: str) -> None:
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
        icon.stop()

    icon = pystray.Icon(
        "local-ai-proxy-stack",
        _make_icon_image(),
        APP_NAME,
        menu=pystray.Menu(
            pystray.MenuItem(lambda _item: _status_title(), None, enabled=False),
            pystray.MenuItem("Settings...", open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start Services", start_services),
            pystray.MenuItem("Restart Services", restart_services),
            pystray.MenuItem("Stop Services", stop_services),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Quit {APP_NAME}", quit_app),
        ),
    )
    icon.run()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--start-services", action="store_true")
    parser.add_argument("--open-settings", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_config()
    if args.start_services or cfg.start_services_on_app_launch:
        start_all(cfg)
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
