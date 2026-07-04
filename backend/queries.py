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


def teacher_submissions(
    database: sqlite3.Connection,
    teacher_id: int,
    group_id: int | None = None,
    student: str = "",
    status: str = "",
) -> list[dict]:
    filters = ["assignments.teacher_id = ?"]
    parameters: list[object] = [teacher_id]
    if group_id:
        filters.append("study_groups.id = ?")
        parameters.append(group_id)
    if student:
        filters.append("(users.display_name LIKE ? OR users.email LIKE ?)")
        pattern = f"%{student[:100]}%"
        parameters.extend([pattern, pattern])
    if status in {"submitted", "graded"}:
        filters.append("submissions.status = ?")
        parameters.append(status)
    rows = database.execute(
        f"""
        SELECT submissions.id, submissions.attempt_number, submissions.status, submissions.submitted_at,
               assignments.title, assignments.variant_id, assignments.tasks_json,
               assignments.id AS assignment_id, users.id AS student_id, study_groups.id AS group_id,
               users.display_name AS student_name, users.email AS student_email,
               study_groups.name AS group_name, reviews.scores_json, reviews.total_score,
               reviews.max_score, reviews.comment, reviews.reviewed_at
        FROM submissions
        JOIN assignments ON assignments.id = submissions.assignment_id
        JOIN users ON users.id = submissions.student_id
        JOIN study_groups ON study_groups.id = assignments.group_id
        LEFT JOIN reviews ON reviews.submission_id = submissions.id
        WHERE {' AND '.join(filters)}
        ORDER BY CASE submissions.status WHEN 'submitted' THEN 0 ELSE 1 END, submissions.submitted_at DESC
        """,
        parameters,
    ).fetchall()
    result = []
    for row in rows:
        recordings = database.execute(
            "SELECT id, task_number, question_number, label, mime_type, size_bytes FROM recordings WHERE submission_id = ? ORDER BY task_number, question_number, id",
            (row["id"],),
        ).fetchall()
        result.append({
            "id": row["id"], "attempt": row["attempt_number"], "status": row["status"],
            "assignmentId": row["assignment_id"], "studentId": row["student_id"], "groupId": row["group_id"],
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


def teacher_assignments(database: sqlite3.Connection, teacher_id: int) -> list[dict]:
    rows = database.execute(
        """
        SELECT assignments.id, assignments.title, assignments.variant_id, assignments.tasks_json,
               assignments.due_at, assignments.created_at, assignments.updated_at,
               assignments.source_assignment_id, study_groups.id AS group_id, study_groups.name AS group_name,
               COUNT(submissions.id) AS submission_count
        FROM assignments JOIN study_groups ON study_groups.id = assignments.group_id
        LEFT JOIN submissions ON submissions.assignment_id = assignments.id
        WHERE assignments.teacher_id = ?
        GROUP BY assignments.id ORDER BY assignments.created_at DESC
        """,
        (teacher_id,),
    ).fetchall()
    return [{
        "id": row["id"], "title": row["title"], "variantId": row["variant_id"],
        "tasks": json.loads(row["tasks_json"]), "dueAt": row["due_at"], "createdAt": row["created_at"],
        "updatedAt": row["updated_at"], "sourceAssignmentId": row["source_assignment_id"],
        "groupId": row["group_id"], "groupName": row["group_name"], "submissionCount": row["submission_count"],
    } for row in rows]


def submission_history(database: sqlite3.Connection, teacher_id: int, submission_id: int) -> dict | None:
    target = database.execute(
        """
        SELECT submissions.assignment_id, submissions.student_id FROM submissions
        JOIN assignments ON assignments.id = submissions.assignment_id
        WHERE submissions.id = ? AND assignments.teacher_id = ?
        """, (submission_id, teacher_id),
    ).fetchone()
    if not target:
        return None
    attempts = teacher_submissions(database, teacher_id)
    return {
        "attempts": [item for item in attempts if item["assignmentId"] == target["assignment_id"]
                     and item["studentId"] == target["student_id"]]
    }
