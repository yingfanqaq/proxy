from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--service":
        from proxy_stack.service_entry import main as service_main

        service_main(sys.argv[2:])
        return
    from proxy_stack.tray_app import main as tray_main

    tray_main(sys.argv[1:])


if __name__ == "__main__":
    main()
