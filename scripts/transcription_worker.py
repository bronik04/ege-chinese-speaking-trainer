"""Compatibility CLI wrapper for the packaged transcription worker."""

from trainer.workers.transcription import main, process_one

__all__ = ["main", "process_one"]


if __name__ == "__main__":
    main()
