from __future__ import annotations

import json
import sqlite3


def safe_progress(value: str | None) -> dict:
    if not value:
        return {"runs": []}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"runs": []}
    except json.JSONDecodeError:
        return {"runs": []}


def teacher_dashboard(database: sqlite3.Connection, teacher_id: int) -> list[dict]:
    groups = database.execute(
        "SELECT id, name, join_code, created_at FROM study_groups WHERE teacher_id = ? ORDER BY created_at DESC",
        (teacher_id,),
    ).fetchall()
    result = []
    for group in groups:
        members = database.execute(
            """
            SELECT users.id, users.display_name, users.email, user_progress.progress_json,
                   user_progress.updated_at
            FROM group_members
            JOIN users ON users.id = group_members.user_id
            LEFT JOIN user_progress ON user_progress.user_id = users.id
            WHERE group_members.group_id = ? ORDER BY users.display_name, users.email
            """,
            (group["id"],),
        ).fetchall()
        students = []
        for member in members:
            document = safe_progress(member["progress_json"])
            completed = [run for run in document.get("runs", []) if run.get("status") == "completed"]
            students.append({
                "id": member["id"],
                "name": member["display_name"] or member["email"],
                "email": member["email"],
                "completedRuns": len(completed),
                "completedTasks": sum(len(run.get("completedTasks", [])) for run in completed),
                "lastActivity": document.get("updatedAt") if member["progress_json"] else None,
            })
        result.append({
            "id": group["id"], "name": group["name"], "code": group["join_code"],
            "createdAt": group["created_at"], "students": students,
        })
    return result


def student_assignments(database: sqlite3.Connection, student_id: int) -> list[dict]:
    rows = database.execute(
        """
        SELECT assignments.id, assignments.title, assignments.variant_id, assignments.tasks_json,
               assignments.due_at, assignments.created_at, study_groups.name AS group_name
        FROM assignments
        JOIN study_groups ON study_groups.id = assignments.group_id
        JOIN group_members ON group_members.group_id = assignments.group_id
        WHERE group_members.user_id = ? ORDER BY assignments.created_at DESC
        """,
        (student_id,),
    ).fetchall()
    result = []
    for row in rows:
        latest = database.execute(
            """
            SELECT submissions.id, submissions.status, submissions.attempt_number,
                   reviews.total_score, reviews.max_score, reviews.comment
            FROM submissions LEFT JOIN reviews ON reviews.submission_id = submissions.id
            WHERE submissions.assignment_id = ? AND submissions.student_id = ?
            ORDER BY submissions.attempt_number DESC LIMIT 1
            """,
            (row["id"], student_id),
        ).fetchone()
        result.append({
            "id": row["id"], "title": row["title"], "variantId": row["variant_id"],
            "tasks": json.loads(row["tasks_json"]), "dueAt": row["due_at"],
            "groupName": row["group_name"], "latest": dict(latest) if latest else None,
        })
    return result


def teacher_submissions(database: sqlite3.Connection, teacher_id: int) -> list[dict]:
    rows = database.execute(
        """
        SELECT submissions.id, submissions.attempt_number, submissions.status, submissions.submitted_at,
               assignments.title, assignments.variant_id, assignments.tasks_json,
               users.display_name AS student_name, users.email AS student_email,
               study_groups.name AS group_name, reviews.scores_json, reviews.total_score,
               reviews.max_score, reviews.comment, reviews.reviewed_at
        FROM submissions
        JOIN assignments ON assignments.id = submissions.assignment_id
        JOIN users ON users.id = submissions.student_id
        JOIN study_groups ON study_groups.id = assignments.group_id
        LEFT JOIN reviews ON reviews.submission_id = submissions.id
        WHERE assignments.teacher_id = ? ORDER BY submissions.submitted_at DESC
        """,
        (teacher_id,),
    ).fetchall()
    result = []
    for row in rows:
        recordings = database.execute(
            "SELECT id, task_number, question_number, label, mime_type, size_bytes FROM recordings WHERE submission_id = ? ORDER BY task_number, question_number, id",
            (row["id"],),
        ).fetchall()
        result.append({
            "id": row["id"], "attempt": row["attempt_number"], "status": row["status"],
            "submittedAt": row["submitted_at"], "title": row["title"],
            "variantId": row["variant_id"], "tasks": json.loads(row["tasks_json"]),
            "studentName": row["student_name"] or row["student_email"],
            "studentEmail": row["student_email"], "groupName": row["group_name"],
            "recordings": [{**dict(recording), "url": f"/api/recordings/{recording['id']}"} for recording in recordings],
            "review": ({"scores": json.loads(row["scores_json"]), "total": row["total_score"],
                        "maximum": row["max_score"], "comment": row["comment"],
                        "reviewedAt": row["reviewed_at"]} if row["scores_json"] else None),
        })
    return result
