import pytest
from fastapi import HTTPException

from app.core.authorization import TenantMembership, TenantRole
from app.services.submissions import (
    decode_submission_cursor,
    encode_submission_cursor,
    list_submissions,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def submitter():
    return TenantMembership(
        user_id="user-123",
        tenant_id="tenant-a",
        role=TenantRole.SUBMITTER,
        status="ACTIVE",
    )


@pytest.fixture
def reviewer():
    return TenantMembership(
        user_id="reviewer-123",
        tenant_id="tenant-a",
        role=TenantRole.REVIEWER,
        status="ACTIVE",
    )


@pytest.fixture
def submission():
    return {
        "tenant_id": "tenant-a",
        "submission_id": "submission-123",
        "owner_id": "user-123",
        "title": "Vendor onboarding",
        "status": "DRAFT",
        "created_at": "2026-11-12T10:00:00Z",
        "updated_at": "2026-11-12T10:00:00Z",
        "version": 1,
    }


class FakeSubmissionRepository:
    def __init__(self, items=None, last_key=None):
        self.items = items or []
        self.last_key = last_key
        self.calls = []

    def list_submitter_submissions(
        self,
        tenant_id,
        user_id,
        limit,
        cursor=None,
    ):
        self.calls.append(("submitter", tenant_id, user_id, limit, cursor))

        return {
            "Items": self.items,
            "LastEvaluatedKey": self.last_key,
        }

    def list_reviewer_submissions(
        self,
        tenant_id,
        limit,
        cursor=None,
    ):
        self.calls.append(("reviewer", tenant_id, limit, cursor))

        return {
            "Items": self.items,
            "LastEvaluatedKey": self.last_key,
        }


@pytest.mark.anyio
async def test_submitter_lists_only_own_submissions(
    submitter,
    submission,
):
    repository = FakeSubmissionRepository(items=[submission])

    result = await list_submissions(
        membership=submitter,
        repository=repository,
        limit=20,
    )

    assert len(result.items) == 1
    assert result.items[0].submission_id == "submission-123"

    assert repository.calls == [("submitter", "tenant-a", "user-123", 20, None)]


@pytest.mark.anyio
async def test_reviewer_lists_tenant_submissions(
    reviewer,
    submission,
):
    repository = FakeSubmissionRepository(items=[submission])

    result = await list_submissions(
        membership=reviewer,
        repository=repository,
        limit=20,
    )

    assert len(result.items) == 1

    assert repository.calls == [("reviewer", "tenant-a", 20, None)]


@pytest.mark.anyio
async def test_submitter_listing_rejects_wrong_owner(
    submitter,
    submission,
):
    submission["owner_id"] = "another-user"

    repository = FakeSubmissionRepository(items=[submission])

    with pytest.raises(HTTPException) as exc:
        await list_submissions(
            membership=submitter,
            repository=repository,
            limit=20,
        )

    assert exc.value.status_code == 500


@pytest.mark.anyio
async def test_listing_rejects_wrong_tenant(
    submitter,
    submission,
):
    submission["tenant_id"] = "tenant-b"

    repository = FakeSubmissionRepository(items=[submission])

    with pytest.raises(HTTPException) as exc:
        await list_submissions(
            membership=submitter,
            repository=repository,
            limit=20,
        )

    assert exc.value.status_code == 500


def test_submitter_cursor_round_trip(submitter):
    last_key = {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
        "GSI1PK": "TENANT#tenant-a#USER#user-123",
        "GSI1SK": "CREATED#2026-11-12T10:00:00Z"
        "#TENANT#tenant-a#SUBMISSION#submission-123",
    }

    cursor = encode_submission_cursor(last_key, submitter)

    decoded = decode_submission_cursor(cursor, submitter)

    assert decoded == last_key


def test_reviewer_cursor_round_trip(reviewer):
    last_key = {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
    }

    cursor = encode_submission_cursor(last_key, reviewer)

    decoded = decode_submission_cursor(cursor, reviewer)

    assert decoded == last_key


def test_cursor_cannot_be_reused_by_another_user(submitter):
    last_key = {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
        "GSI1PK": "TENANT#tenant-a#USER#user-123",
        "GSI1SK": "CREATED#2026-11-12T10:00:00Z"
        "#TENANT#tenant-a#SUBMISSION#submission-123",
    }

    cursor = encode_submission_cursor(last_key, submitter)

    another_user = TenantMembership(
        user_id="user-456",
        tenant_id="tenant-a",
        role=TenantRole.SUBMITTER,
        status="ACTIVE",
    )

    with pytest.raises(HTTPException) as exc:
        decode_submission_cursor(cursor, another_user)

    assert exc.value.status_code == 400


def test_cursor_cannot_be_reused_in_another_tenant(submitter):
    last_key = {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
        "GSI1PK": "TENANT#tenant-a#USER#user-123",
        "GSI1SK": "CREATED#2026-11-12T10:00:00Z"
        "#TENANT#tenant-a#SUBMISSION#submission-123",
    }

    cursor = encode_submission_cursor(last_key, submitter)

    another_tenant = TenantMembership(
        user_id="user-123",
        tenant_id="tenant-b",
        role=TenantRole.SUBMITTER,
        status="ACTIVE",
    )

    with pytest.raises(HTTPException) as exc:
        decode_submission_cursor(cursor, another_tenant)

    assert exc.value.status_code == 400


def test_malformed_cursor_is_rejected(submitter):
    with pytest.raises(HTTPException) as exc:
        decode_submission_cursor(
            "this-is-not-a-valid-cursor",
            submitter,
        )

    assert exc.value.status_code == 400


def test_cursor_rejects_wrong_dynamodb_partition(submitter):
    invalid_key = {
        "PK": "TENANT#tenant-b",
        "SK": "SUBMISSION#submission-123",
        "GSI1PK": "TENANT#tenant-a#USER#user-123",
        "GSI1SK": "CREATED#2026-11-12T10:00:00Z",
    }

    cursor = encode_submission_cursor(
        invalid_key,
        submitter,
    )

    with pytest.raises(HTTPException) as exc:
        decode_submission_cursor(cursor, submitter)

    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_listing_returns_next_cursor(
    submitter,
    submission,
):
    last_key = {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
        "GSI1PK": "TENANT#tenant-a#USER#user-123",
        "GSI1SK": "CREATED#2026-11-12T10:00:00Z"
        "#TENANT#tenant-a#SUBMISSION#submission-123",
    }

    repository = FakeSubmissionRepository(
        items=[submission],
        last_key=last_key,
    )

    result = await list_submissions(
        membership=submitter,
        repository=repository,
        limit=1,
    )

    assert result.next_cursor is not None

    decoded = decode_submission_cursor(
        result.next_cursor,
        submitter,
    )

    assert decoded == last_key


@pytest.mark.anyio
async def test_listing_returns_no_cursor_on_last_page(
    submitter,
    submission,
):
    repository = FakeSubmissionRepository(
        items=[submission],
        last_key=None,
    )

    result = await list_submissions(
        membership=submitter,
        repository=repository,
        limit=20,
    )

    assert result.next_cursor is None
