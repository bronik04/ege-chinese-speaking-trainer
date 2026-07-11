from trainer.infrastructure.database.queries.assignments import student_assignments, teacher_assignments
from trainer.infrastructure.database.queries.groups import teacher_dashboard
from trainer.infrastructure.database.queries.submissions import submission_history, teacher_submissions

__all__ = [
    "student_assignments",
    "submission_history",
    "teacher_assignments",
    "teacher_dashboard",
    "teacher_submissions",
]
