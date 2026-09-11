# S3/R2 Audio Range Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let authenticated users seek private audio recordings stored in S3/R2 without downloading an entire object.

**Architecture:** The API parses and validates one HTTP byte range using `FileResult.size_bytes`. Local files continue through Starlette `FileResponse`; remote storage receives the exact validated range and returns a `StreamingResponse` with explicit range headers. The storage protocol owns byte acquisition, while HTTP status codes and headers stay in the API layer.

**Tech Stack:** Python 3.12, FastAPI/Starlette, boto3-compatible S3/R2 API, unittest.

**Spec:** `docs/superpowers/specs/2026-08-19-s3-audio-range-design.md`

## Global Constraints

- Change only `GET /api/recordings/{recording_id}`; material images and presigned URLs are out of scope.
- Keep `require_authenticated` authorization before any object read.
- Support exactly one `bytes` range; return `416` for malformed, unsatisfiable, or comma-separated ranges.
- Preserve `200` streaming behavior when `Range` is absent.
- Preserve local-file serving with `FileResponse`; S3/R2 reads the requested segment through `get_object(Range=...)`.
- Run `make check`; no UI behavior changes, so E2E is not required.

---

## File Structure

- Create `src/trainer/api/ranges.py` — pure parsing and validation of a single byte range against a known object size.
- Create `tests/unit/test_http_ranges.py` — table-free unit coverage for valid, invalid, suffix, and open-ended ranges.
- Modify `src/trainer/infrastructure/storage/protocols.py` — add optional byte bounds to the storage stream contract.
- Modify `src/trainer/infrastructure/storage/local.py` — seek and stream a bounded portion of a local file for direct adapter coverage.
- Modify `src/trainer/infrastructure/storage/s3.py` — pass the validated S3 `Range` parameter and stream the remote response body.
- Modify `src/trainer/services/recordings.py` — pass optional bounds to the selected audio storage adapter.
- Modify `src/trainer/api/routes/__init__.py` — select local `FileResponse` or remote ranged `StreamingResponse` and set HTTP headers.
- Modify `src/trainer/api/routes/recordings.py` — pass the request's `Range` header into `file_response`.
- Modify `tests/integration/test_storage.py` — verify S3/R2 receives `Range` and local bounded streaming returns only the requested bytes.
- Modify `tests/integration/test_api_flows.py` — verify local API `206`/`416` behavior and headers.

## Task 1: Parse a Single HTTP Byte Range

**Files:**
- Create: `src/trainer/api/ranges.py`
- Create: `tests/unit/test_http_ranges.py`

**Interfaces:**
- Produces: `ByteRange(start: int, end: int)` where both values are inclusive.
- Produces: `parse_single_byte_range(value: str | None, size: int) -> ByteRange | None`.
- Raises: `RangeNotSatisfiable` for a header that is malformed, comma-separated, outside the object, or evaluated against `size <= 0`.

- [ ] **Step 1: Write failing parser tests**

```python
import unittest

from trainer.api.ranges import ByteRange, RangeNotSatisfiable, parse_single_byte_range


class ByteRangeTest(unittest.TestCase):
    def test_parses_closed_open_and_suffix_byte_ranges(self):
        self.assertEqual(parse_single_byte_range("bytes=2-5", 10), ByteRange(2, 5))
        self.assertEqual(parse_single_byte_range("bytes=7-", 10), ByteRange(7, 9))
        self.assertEqual(parse_single_byte_range("bytes=-3", 10), ByteRange(7, 9))


    def test_rejects_multiple_malformed_and_unsatisfiable_ranges(self):
        for value in ("bytes=0-1,4-5", "items=0-1", "bytes=8-3", "bytes=10-", "bytes=-0"):
            with self.assertRaises(RangeNotSatisfiable):
                parse_single_byte_range(value, 10)
```

- [ ] **Step 2: Run the parser tests to verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_http_ranges -v`

Expected: FAIL because `trainer.api.ranges` does not exist.

- [ ] **Step 3: Implement the pure parser**

```python
@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class RangeNotSatisfiable(ValueError):
    pass


def parse_single_byte_range(value: str | None, size: int) -> ByteRange | None:
    if value is None:
        return None
    # Accept only one bytes unit and one `start-end` expression; normalize suffix and open end.
```

Reject whitespace-only, extra units, a comma, non-decimal values, negative starts, end-before-start, and starts at or after `size`. Clamp a suffix length larger than `size` to `0-size-1`.

- [ ] **Step 4: Run the parser tests to verify GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_http_ranges -v`

Expected: PASS.

- [ ] **Step 5: Commit the parser deliverable**

```bash
git add src/trainer/api/ranges.py tests/unit/test_http_ranges.py
git commit -m "feat: parse single audio byte ranges"
```

## Task 2: Stream Exact Byte Bounds from Each Storage Adapter

**Files:**
- Modify: `src/trainer/infrastructure/storage/protocols.py`
- Modify: `src/trainer/infrastructure/storage/local.py`
- Modify: `src/trainer/infrastructure/storage/s3.py`
- Modify: `src/trainer/services/recordings.py`
- Modify: `tests/integration/test_storage.py`

**Interfaces:**
- Consumes: inclusive `start` and `end` bounds created by `ByteRange`.
- Produces: `AudioStorage.stream(key: str, *, start: int | None = None, end: int | None = None) -> Iterator[bytes]`.
- Produces: `stream_recording(root, key, *, start: int | None = None, end: int | None = None) -> Iterator[bytes]`.

- [ ] **Step 1: Write failing adapter tests**

```python
def test_local_stream_reads_only_the_requested_byte_range(self):
    storage = LocalAudioStorage(root)
    source.write_bytes(b"0123456789")
    storage.put("1/answer.webm", source, "audio/webm")
    assert b"".join(storage.stream("1/answer.webm", start=2, end=5)) == b"2345"


@patch("boto3.client")
def test_s3_stream_passes_the_inclusive_range_to_get_object(self, client_factory):
    client.get_object.return_value = {"Body": Mock(iter_chunks=Mock(return_value=iter([b"2345"]))) }
    storage = S3AudioStorage(bucket="answers", endpoint_url=None, region="auto")
    assert b"".join(storage.stream("1/answer.webm", start=2, end=5)) == b"2345"
    client.get_object.assert_called_once_with(Bucket="answers", Key="1/answer.webm", Range="bytes=2-5")
```

- [ ] **Step 2: Run the storage tests to verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.integration.test_storage -v`

Expected: FAIL because `stream()` does not accept `start` and `end`.

- [ ] **Step 3: Extend the protocol and adapters**

```python
class AudioStorage(Protocol):
    def stream(self, key: str, *, start: int | None = None, end: int | None = None) -> Iterator[bytes]: ...
```

For `LocalAudioStorage`, seek to `start` (default `0`) and yield until the inclusive `end` is consumed; preserve existing whole-file behavior when both bounds are `None`.

For `S3AudioStorage`, construct only these arguments:

```python
params = {"Bucket": self.bucket, "Key": key}
if start is not None:
    params["Range"] = f"bytes={start}-{end}"
body = self.client.get_object(**params)["Body"]
yield from body.iter_chunks(64 * 1024)
```

Keep existing `FileNotFoundError` translation around `get_object`. Forward the optional bounds through `stream_recording` without adding HTTP logic to the service.

- [ ] **Step 4: Run the storage tests to verify GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.integration.test_storage -v`

Expected: PASS.

- [ ] **Step 5: Commit the storage deliverable**

```bash
git add src/trainer/infrastructure/storage/protocols.py src/trainer/infrastructure/storage/local.py src/trainer/infrastructure/storage/s3.py src/trainer/services/recordings.py tests/integration/test_storage.py
git commit -m "feat: stream audio byte ranges from storage"
```

## Task 3: Return Correct Ranged Audio HTTP Responses

**Files:**
- Modify: `src/trainer/api/routes/__init__.py`
- Modify: `src/trainer/api/routes/recordings.py`
- Modify: `tests/integration/test_api_flows.py`

**Interfaces:**
- Consumes: `parse_single_byte_range(range_header, stored.size_bytes)` and `RangeNotSatisfiable` from Task 1.
- Consumes: bounded `stream_recording(..., start=..., end=...)` from Task 2.
- Produces: `file_response(stored: FileResult, range_header: str | None = None) -> Response`.

- [ ] **Step 1: Write failing API tests**

```python
def test_recording_returns_suffix_range_with_precise_headers(self):
    recording_id, cookie = self.create_recording()
    status, headers, body = self.request_raw(f"/api/recordings/{recording_id}", cookie, headers={"Range": "bytes=-4"})
    self.assertEqual(status, 206)
    self.assertEqual(headers["accept-ranges"], "bytes")
    self.assertTrue(headers["content-range"].endswith("/10"))
    self.assertEqual(headers["content-length"], "4")
    self.assertEqual(body, b"6789")


def test_recording_rejects_multiple_ranges_without_reading_audio(self):
    recording_id, cookie = self.create_recording()
    status, headers, body = self.request_raw(f"/api/recordings/{recording_id}", cookie, headers={"Range": "bytes=0-1,4-5"})
    self.assertEqual(status, 416)
    self.assertEqual(headers["content-range"], "bytes */10")
    self.assertEqual(body, b"")
```

- [ ] **Step 2: Run the targeted API tests to verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.integration.test_api_flows.ApiFlowTest.test_recording_returns_suffix_range_with_precise_headers tests.integration.test_api_flows.ApiFlowTest.test_recording_rejects_multiple_ranges_without_reading_audio -v`

Expected: FAIL because the current helper neither parses suffix ranges nor returns `416` for a comma-separated Range.

- [ ] **Step 3: Wire validated ranges into `file_response`**

```python
def file_response(stored: FileResult, range_header: str | None = None) -> Response:
    headers = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Accept-Ranges": "bytes"}
    try:
        byte_range = parse_single_byte_range(range_header, stored.size_bytes)
    except RangeNotSatisfiable:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{stored.size_bytes}"})
```

If `storage_local_path()` returns a path, continue returning `FileResponse` after validation so Starlette serves the local range efficiently. For remote storage and `byte_range is None`, return a `200 StreamingResponse` with `Content-Length` equal to `stored.size_bytes`. For remote storage and a valid `byte_range`, return `206 StreamingResponse` over `stream_recording(..., start=byte_range.start, end=byte_range.end)` with exact `Content-Range` and `Content-Length`.

Pass `request.headers.get("Range")` from `get_recording` to `file_response`.

- [ ] **Step 4: Run the targeted API tests to verify GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.integration.test_api_flows.ApiFlowTest.test_recording_supports_range_requests tests.integration.test_api_flows.ApiFlowTest.test_recording_returns_suffix_range_with_precise_headers tests.integration.test_api_flows.ApiFlowTest.test_recording_rejects_multiple_ranges_without_reading_audio -v`

Expected: PASS.

- [ ] **Step 5: Commit the API deliverable**

```bash
git add src/trainer/api/routes/__init__.py src/trainer/api/routes/recordings.py tests/integration/test_api_flows.py
git commit -m "feat: serve ranged remote audio responses"
```

## Task 4: Verify the Complete Contract

**Files:**
- Modify only if verification exposes a requirement mismatch: files named in Tasks 1–3.

**Interfaces:**
- Verifies all parser, adapter, and route contracts from Tasks 1–3 together.

- [ ] **Step 1: Run the focused complete range suite**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_http_ranges tests.integration.test_storage tests.integration.test_api_flows -v`

Expected: PASS with valid local and mocked-S3 range behavior plus `416` handling.

- [ ] **Step 2: Run required repository verification**

Run: `PYTHONPATH=src make check PYTHON=.venv/bin/python NPM=npm`

Expected: PASS.

- [ ] **Step 3: Inspect the final diff and commit any verification-only correction**

Run: `git diff --check && git status --short`

Expected: no whitespace errors and no uncommitted changes unless a tested correction is necessary.
