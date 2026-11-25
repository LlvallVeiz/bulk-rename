"""Entry point so ``python -m bulk_rename`` works."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
