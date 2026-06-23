from __future__ import annotations


def main() -> None:
    try:
        from .app import main as fastapi_main
    except ModuleNotFoundError as exc:
        if exc.name != "fastapi":
            raise
        from .stdlib_server import main as stdlib_main

        stdlib_main()
        return
    fastapi_main()


if __name__ == "__main__":
    main()

