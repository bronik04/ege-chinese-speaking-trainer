from trainer.infrastructure.database.queries.assignments import student_assignments, teacher_assignments
from trainer.infrastructure.database.queries.groups import teacher_dashboard
from trainer.infrastructure.database.queries.review_requests import (
    review_request_detail,
    student_review_requests,
    teacher_review_requests,
)
from trainer.infrastructure.database.queries.submissions import submission_history, teacher_submissions

__all__ = [
    "student_assignments",
    "student_review_requests",
    "submission_history",
    "teacher_assignments",
    "teacher_dashboard",
    "teacher_review_requests",
    "teacher_submissions",
    "review_request_detail",
]
