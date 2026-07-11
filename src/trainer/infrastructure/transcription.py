from __future__ import annotations

import os
from pathlib import Path


class OpenAITranscriber:
    def __init__(self):
        from openai import OpenAI

        self.client = OpenAI()
        self.model = os.environ.get("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")

    def transcribe(self, path: Path) -> str:
        with path.open("rb") as audio:
            result = self.client.audio.transcriptions.create(
                model=self.model,
                file=audio,
                language=os.environ.get("OPENAI_TRANSCRIPTION_LANGUAGE", "zh"),
                response_format="json",
            )
        return result.text
