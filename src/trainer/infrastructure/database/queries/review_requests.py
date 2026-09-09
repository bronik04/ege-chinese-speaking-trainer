from __future__ import annotations

import json
import sqlite3
import time


def _run_id(run_json: str) -> str | None:
    try:
        run = json.loads(run_json)
    except (TypeError, ValueError):
        return None
    value = run.get("id") if isinstance(run, dict) else None
    return value if isinstance(value, str) and 1 <= len(value) <= 120 else None


def _request_items(database: sqlite3.Connection, request_id: int, *, include_material: bool, now: int) -> list[dict]:
    rows = database.execute(
        """SELECT id,task_number,task_snapshot_json,scores_json,total_score,max_score
           FROM review_request_items WHERE request_id=? ORDER BY task_number""",
        (request_id,),
    ).fetchall()
    result = []
    for row in rows:
        recordings = database.execute(
            """SELECT id,question_number,label,mime_type,size_bytes,duration_seconds,created_at
               FROM review_request_recordings
               WHERE item_id=? AND expires_at>? ORDER BY question_number,id""",
            (row["id"], now),
        ).fetchall()
        item = {
            "task": row["task_number"],
            "scores": json.loads(row["scores_json"]) if row["scores_json"] else None,
            "total": row["total_score"],
            "maximum": row["max_score"],
            "recordings": [
                {
                    **dict(recording),
                    "url": f"/api/review-recordings/{recording['id']}",
                }
                for recording in recordings
            ],
        }
        if include_material:
            item["material"] = json.loads(row["task_snapshot_json"])
        result.append(item)
    return result


def _request_assets(database: sqlite3.Connection, request_id: int) -> list[dict]:
    rows = database.execute(
        """SELECT id,mime_type,size_bytes,created_at FROM review_request_assets
           WHERE request_id=? ORDER BY id""",
        (request_id,),
    ).fetchall()
    return [{**dict(row), "url": f"/api/review-assets/{row['id']}"} for row in rows]


def _request_payload(
    database: sqlite3.Connection, row, *, teacher_view: bool, include_material: bool, now: int
) -> dict:
    items = _request_items(database, row["id"], include_material=include_material, now=now)
    payload = {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "variantId": row["variant_id"],
        "submittedAt": row["submitted_at"],
        "reviewedAt": row["reviewed_at"],
        "tasks": [item["task"] for item in items],
        "total": sum(item["total"] or 0 for item in items),
        "maximum": sum(item["maximum"] or 0 for item in items),
        "items": items,
        "assets": _request_assets(database, row["id"]),
    }
    if teacher_view:
        payload.update(
            {
                "studentId": row["student_id"],
                "studentName": row["student_name"] or row["student_email"],
                "studentEmail": row["student_email"],
            }
        )
    if include_material:
        payload["material"] = {str(item["task"]): item.pop("material") for item in items}
    return payload


def student_review_requests(database: sqlite3.Connection, student_id: int) -> list[dict]:
    rows = database.execute(
        """SELECT id,student_id,kind,status,variant_id,run_json,submitted_at,reviewed_at
           FROM review_requests WHERE student_id=? ORDER BY submitted_at DESC,id DESC""",
        (student_id,),
    ).fetchall()
    now = int(time.time())
    result = []
    for row in rows:
        payload = _request_payload(database, row, teacher_view=False, include_material=False, now=now)
        payload["runId"] = _run_id(row["run_json"])
        result.append(payload)
    return result


def teacher_review_requests(
    database: sqlite3.Connection,
    *,
    student: str = "",
    task: int | None = None,
    status: str = "",
    submitted_from: int | None = None,
    submitted_before: int | None = None,
) -> list[dict]:
    filters = ["review_requests.status IN ('queued', 'reviewed')"]
    parameters: list[object] = []
    if student:
        pattern = f"%{student[:100]}%"
        filters.append("(users.display_name LIKE ? OR users.email LIKE ?)")
        parameters.extend((pattern, pattern))
    if task in {1, 2, 3}:
        filters.append(
            "EXISTS(SELECT 1 FROM review_request_items WHERE request_id=review_requests.id AND task_number=?)"
        )
        parameters.append(task)
    if status in {"queued", "reviewed"}:
        filters.append("review_requests.status=?")
        parameters.append(status)
    if submitted_from is not None:
        filters.append("review_requests.submitted_at>=?")
        parameters.append(submitted_from)
    if submitted_before is not None:
        filters.append("review_requests.submitted_at<?")
        parameters.append(submitted_before)
    rows = database.execute(
        f"""
        SELECT review_requests.id,review_requests.student_id,review_requests.kind,review_requests.status,
               review_requests.variant_id,review_requests.submitted_at,review_requests.reviewed_at,
               users.display_name AS student_name,users.email AS student_email
        FROM review_requests JOIN users ON users.id=review_requests.student_id
        WHERE {" AND ".join(filters)}
        ORDER BY CASE review_requests.status WHEN 'queued' THEN 0 ELSE 1 END,
                 CASE WHEN review_requests.status='queued' THEN review_requests.submitted_at END ASC,
                 CASE WHEN review_requests.status='reviewed' THEN review_requests.submitted_at END DESC,
                 CASE WHEN review_requests.status='queued' THEN review_requests.id END ASC,
                 CASE WHEN review_requests.status='reviewed' THEN review_requests.id END DESC
        """,
        parameters,
    ).fetchall()
    now = int(time.time())
    return [_request_payload(database, row, teacher_view=True, include_material=False, now=now) for row in rows]


def review_request_detail(database: sqlite3.Connection, request_id: int) -> dict | None:
    row = database.execute(
        """SELECT review_requests.id,review_requests.student_id,review_requests.kind,review_requests.status,
                  review_requests.variant_id,review_requests.submitted_at,review_requests.reviewed_at,
                  users.display_name AS student_name,users.email AS student_email
           FROM review_requests JOIN users ON users.id=review_requests.student_id
           WHERE review_requests.id=? AND review_requests.status IN ('queued', 'reviewed')""",
        (request_id,),
    ).fetchone()
    return (
        _request_payload(database, row, teacher_view=True, include_material=True, now=int(time.time())) if row else None
    )
