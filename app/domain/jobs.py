from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    OPENING_BROWSER = "opening_browser"
    CHECKING_LOGIN = "checking_login"
    UPLOADING = "uploading"
    PUBLISHING = "publishing"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    DRY_RUN_READY = "dry_run_ready"
    TEMPORARY_FAILURE = "temporary_failure"
    PERMANENT_FAILURE = "permanent_failure"
    LOGIN_REQUIRED = "login_required"
    CHECKPOINT = "checkpoint"
    UNKNOWN_RESULT = "unknown_result"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.DRY_RUN_READY,
    JobStatus.PERMANENT_FAILURE,
    JobStatus.CANCELLED,
}

EXECUTION_STATUSES = {
    JobStatus.OPENING_BROWSER,
    JobStatus.CHECKING_LOGIN,
    JobStatus.UPLOADING,
    JobStatus.PUBLISHING,
    JobStatus.VERIFYING,
}

ACCOUNT_BUSY_STATUSES = EXECUTION_STATUSES | {
    JobStatus.LOGIN_REQUIRED,
    JobStatus.CHECKPOINT,
    JobStatus.UNKNOWN_RESULT,
}


ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.DRAFT: {JobStatus.PENDING_APPROVAL, JobStatus.CANCELLED},
    JobStatus.PENDING_APPROVAL: {JobStatus.APPROVED, JobStatus.DRAFT, JobStatus.CANCELLED},
    JobStatus.APPROVED: {JobStatus.SCHEDULED, JobStatus.QUEUED, JobStatus.CANCELLED},
    JobStatus.SCHEDULED: {JobStatus.QUEUED, JobStatus.PENDING_APPROVAL, JobStatus.CANCELLED},
    JobStatus.QUEUED: {JobStatus.OPENING_BROWSER, JobStatus.PUBLISHING, JobStatus.CANCELLED},
    JobStatus.OPENING_BROWSER: {
        JobStatus.CHECKING_LOGIN, JobStatus.TEMPORARY_FAILURE, JobStatus.PERMANENT_FAILURE,
        JobStatus.LOGIN_REQUIRED, JobStatus.CHECKPOINT, JobStatus.CANCELLED,
    },
    JobStatus.CHECKING_LOGIN: {
        JobStatus.UPLOADING, JobStatus.PUBLISHING, JobStatus.TEMPORARY_FAILURE,
        JobStatus.PERMANENT_FAILURE, JobStatus.LOGIN_REQUIRED, JobStatus.CHECKPOINT,
        JobStatus.UNKNOWN_RESULT, JobStatus.CANCELLED,
    },
    JobStatus.UPLOADING: {
        JobStatus.PUBLISHING, JobStatus.TEMPORARY_FAILURE, JobStatus.PERMANENT_FAILURE,
        JobStatus.LOGIN_REQUIRED, JobStatus.CHECKPOINT, JobStatus.UNKNOWN_RESULT,
        JobStatus.CANCELLED,
    },
    JobStatus.PUBLISHING: {
        JobStatus.VERIFYING, JobStatus.SUCCEEDED, JobStatus.DRY_RUN_READY,
        JobStatus.TEMPORARY_FAILURE, JobStatus.PERMANENT_FAILURE,
        JobStatus.LOGIN_REQUIRED, JobStatus.CHECKPOINT,
        JobStatus.UNKNOWN_RESULT, JobStatus.CANCELLED,
    },
    JobStatus.VERIFYING: {
        JobStatus.SUCCEEDED, JobStatus.TEMPORARY_FAILURE,
        JobStatus.PERMANENT_FAILURE, JobStatus.UNKNOWN_RESULT,
    },
    JobStatus.TEMPORARY_FAILURE: {JobStatus.QUEUED, JobStatus.PERMANENT_FAILURE, JobStatus.CANCELLED},
    JobStatus.LOGIN_REQUIRED: {JobStatus.QUEUED, JobStatus.CANCELLED},
    JobStatus.CHECKPOINT: {JobStatus.QUEUED, JobStatus.CANCELLED},
    JobStatus.UNKNOWN_RESULT: {
        JobStatus.VERIFYING, JobStatus.SUCCEEDED, JobStatus.PERMANENT_FAILURE, JobStatus.CANCELLED,
    },
    JobStatus.SUCCEEDED: set(),
    JobStatus.DRY_RUN_READY: set(),
    JobStatus.PERMANENT_FAILURE: set(),
    JobStatus.CANCELLED: set(),
}


class InvalidJobTransition(ValueError):
    pass


def validate_transition(current: str | JobStatus, target: str | JobStatus) -> tuple[JobStatus, JobStatus]:
    try:
        current_status = JobStatus(current)
        target_status = JobStatus(target)
    except ValueError as exc:
        raise InvalidJobTransition(f"Trạng thái job không hợp lệ: {exc}") from exc
    if target_status not in ALLOWED_TRANSITIONS[current_status]:
        raise InvalidJobTransition(f"Không thể chuyển job từ {current_status.value} sang {target_status.value}.")
    return current_status, target_status
