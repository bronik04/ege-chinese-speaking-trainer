"""Compatibility ASGI entrypoint; the canonical app lives in trainer.main."""

from trainer.main import app, main

__all__ = ["app", "main"]


if __name__ == "__main__":
    main()
