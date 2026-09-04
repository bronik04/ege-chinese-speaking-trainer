class ProgressValidationError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def validate_progress(document: object) -> None:
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ProgressValidationError("invalid_document")
    runs = document.get("runs", [])
    if not isinstance(runs, list) or len(runs) > 200:
        raise ProgressValidationError("history_too_large")
