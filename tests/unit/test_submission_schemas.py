import pytest
from pydantic import ValidationError

from app.schemas.submission import SubmissionListItem, SubmissionResponse
from app.schemas.workflow import SubmissionStatus

VALID_STATUSES = list(SubmissionStatus)


@pytest.fixture
def submission_response_data():
    return {
        "tenant_id": "tenant-123",
        "submission_id": "submission-123",
        "title": "Security review",
        "description": "Review uploaded documents",
        "status": "DRAFT",
        "created_at": "2026-11-20T10:00:00Z",
        "updated_at": "2026-11-20T10:00:00Z",
        "version": 1,
    }


@pytest.fixture
def submission_list_item_data():
    return {
        "tenant_id": "tenant-123",
        "submission_id": "submission-123",
        "title": "Security review",
        "status": "DRAFT",
        "created_at": "2026-11-20T10:00:00Z",
        "updated_at": "2026-11-20T10:00:00Z",
        "version": 1,
    }


@pytest.mark.parametrize("status", VALID_STATUSES)
def test_submission_response_accepts_valid_statuses(submission_response_data, status):
    submission_response_data["status"] = status.value

    result = SubmissionResponse.model_validate(submission_response_data)

    assert result.status is status


@pytest.mark.parametrize("status", VALID_STATUSES)
def test_submission_list_item_accepts_valid_statuses(submission_list_item_data, status):
    submission_list_item_data["status"] = status.value

    result = SubmissionListItem.model_validate(submission_list_item_data)

    assert result.status is status


@pytest.mark.parametrize(
    "model,data_fixture",
    [
        (SubmissionResponse, "response"),
        (SubmissionListItem, "list_item"),
    ],
)
def test_submission_schemas_reject_unknown_status(
    model,
    data_fixture,
    submission_response_data,
    submission_list_item_data,
):
    data = (
        submission_response_data
        if data_fixture == "response"
        else submission_list_item_data
    )
    data["status"] = "ARCHIVED"

    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_submission_response_preserves_optional_defaults(
    submission_response_data,
):
    submission_response_data["title"] = None
    submission_response_data["description"] = None

    result = SubmissionResponse.model_validate(submission_response_data)

    assert result.title is None
    assert result.description is None
    assert result.pending_document_count == 0
    assert result.uploaded_document_count == 0
