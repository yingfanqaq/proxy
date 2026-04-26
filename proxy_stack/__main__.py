from __future__ import annotations

import argparse
import json
import sys

from . import APP_NAME
from . import autostart, manager
from .config import config_path, env_snippets, load_config, save_config


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="proxyEverywhere", description=APP_NAME)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("restart")
    sub.add_parser("status")
    sub.add_parser("config-path")
    sub.add_parser("env")
    sub.add_parser("install-autostart")
    sub.add_parser("uninstall-autostart")
    tray = sub.add_parser("tray")
    tray.add_argument("--start-services", action="store_true")
    tray.add_argument("--open-settings", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "start":
        print(json.dumps(manager.start_all(), indent=2, ensure_ascii=False))
    elif args.command == "stop":
        print(json.dumps(manager.stop_all(), indent=2, ensure_ascii=False))
    elif args.command == "restart":
        print(json.dumps(manager.restart_all(), indent=2, ensure_ascii=False))
    elif args.command == "status":
        print(manager.print_status())
    elif args.command == "config-path":
        cfg = load_config()
        save_config(cfg)
        print(config_path())
    elif args.command == "env":
        for name, snippet in env_snippets().items():
            print(f"# {name}\n{snippet}\n")
    elif args.command == "install-autostart":
        print(autostart.install())
    elif args.command == "uninstall-autostart":
        autostart.uninstall()
        print("Autostart removed.")
    elif args.command == "tray":
        from .tray_app import main as tray_main

        tray_args = []
        if args.start_services:
            tray_args.append("--start-services")
        if args.open_settings:
            tray_args.append("--open-settings")
        tray_main(tray_args)
    else:
        raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main(sys.argv[1:])
