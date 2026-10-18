from __future__ import annotations

import sys


def main() -> None:
    if sys.argv[1:2] == ["doctor"]:
        from .doctor import main as doctor_main

        doctor_main(sys.argv[2:])
        return
    from .server import main as server_main

    server_main()


if __name__ == "__main__":
    main()
