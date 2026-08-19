"""Parsing helpers for HTTP byte-range requests."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class RangeNotSatisfiable(ValueError):
    """Raised when an HTTP byte-range header cannot be served."""


def _parse_decimal(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise RangeNotSatisfiable("byte range number is invalid") from exc


def parse_single_byte_range(value: str | None, size: int) -> ByteRange | None:
    """Parse one RFC 9110 byte range against an object of ``size`` bytes."""
    if value is None:
        return None
    if size <= 0:
        raise RangeNotSatisfiable("range cannot be evaluated against an empty object")

    try:
        unit, expression = value.split("=", 1)
    except ValueError as exc:
        raise RangeNotSatisfiable("malformed range header") from exc
    if unit != "bytes" or "," in expression:
        raise RangeNotSatisfiable("unsupported or multiple range")
    if re.fullmatch(r"[0-9]*-[0-9]*", expression) is None:
        raise RangeNotSatisfiable("malformed byte range")

    start_text, end_text = expression.split("-")
    if not start_text and not end_text:
        raise RangeNotSatisfiable("empty byte range")
    if not start_text:
        suffix_length = _parse_decimal(end_text)
        if suffix_length <= 0:
            raise RangeNotSatisfiable("suffix length must be positive")
        return ByteRange(max(0, size - suffix_length), size - 1)

    start = _parse_decimal(start_text)
    if start >= size:
        raise RangeNotSatisfiable("range starts outside object")
    end = size - 1 if not end_text else _parse_decimal(end_text)
    if end < start:
        raise RangeNotSatisfiable("range end precedes start")
    return ByteRange(start, min(end, size - 1))
