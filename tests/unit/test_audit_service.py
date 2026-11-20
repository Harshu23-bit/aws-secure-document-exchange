import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.core.authorization import TenantMembership, TenantRole
from app.schemas.workflow import AuditEventListResponse
from app.services import audit


@pytest.fixture
def submitter():
    return TenantMembership(
        user_id="user-a",
        tenant_id="tenant-a",
        role=TenantRole.SUBMITTER,
        status="ACTIVE",
    )


@pytest.fixture
def submission_repository():
    return MagicMock()


@pytest.fixture
def audit_repository():
    repo = MagicMock()
    repo.list_submission_events.return_value = {
        "Items": [
            {
                "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
                "SK": "EVENT#2026-11-12T12:00:00Z#event-123",
                "GSI1PK": "TENANT#tenant-a",
                "GSI1SK": "EVENT#2026-11-12T10:00:00Z#event-123",
                "event_id": "event-123",
                "event_type": "SUBMISSION_STATUS_CHANGED",
                "tenant_id": "tenant-a",
                "submission_id": "submission-123",
                "entity_type": "AUDIT_EVENT",
                "actor_id": "user-a",
                "actor_role": "SUBMITTER",
                "previous_status": "DRAFT",
                "new_status": "SUBMITTED",
                "previous_version": 1,
                "new_version": 2,
                "timestamp": "2026-11-12T12:00:00Z",
                "request_id": "request-123",
            }
        ]
    }
    return repo


def run_async(coroutine):
    return asyncio.run(coroutine)


def test_authorization_occurs_before_audit_query(
    submitter,
    submission_repository,
    audit_repository,
    monkeypatch,
):
    authorization = AsyncMock(return_value=MagicMock())

    monkeypatch.setattr(
        audit,
        "get_authorized_submission",
        authorization,
    )

    result = run_async(
        audit.get_submission_audit_history(
            tenant_id="tenant-a",
            submission_id="submission-123",
            membership=submitter,
            submission_repository=submission_repository,
            audit_repository=audit_repository,
        )
    )

    authorization.assert_awaited_once()

    audit_repository.list_submission_events.assert_called_once_with(
        "tenant-a",
        "submission-123",
        20,
        None,
    )

    assert isinstance(result, AuditEventListResponse)
    assert len(result.items) == 1
    assert result.items[0].event_id == "event-123"


def test_authorization_failure_prevents_audit_query(
    submitter,
    submission_repository,
    audit_repository,
    monkeypatch,
):
    authorization = AsyncMock(
        side_effect=HTTPException(
            status_code=404,
            detail="Submission not found",
        )
    )

    monkeypatch.setattr(
        audit,
        "get_authorized_submission",
        authorization,
    )

    with pytest.raises(HTTPException) as exc:
        run_async(
            audit.get_submission_audit_history(
                tenant_id="tenant-a",
                submission_id="submission-123",
                membership=submitter,
                submission_repository=submission_repository,
                audit_repository=audit_repository,
            )
        )

    assert exc.value.status_code == 404
    audit_repository.list_submission_events.assert_not_called()


def test_tenant_mismatch_prevents_authorization_and_query(
    submitter,
    submission_repository,
    audit_repository,
    monkeypatch,
):
    authorization = AsyncMock()

    monkeypatch.setattr(
        audit,
        "get_authorized_submission",
        authorization,
    )

    with pytest.raises(HTTPException) as exc:
        run_async(
            audit.get_submission_audit_history(
                tenant_id="tenant-b",
                submission_id="submission-123",
                membership=submitter,
                submission_repository=submission_repository,
                audit_repository=audit_repository,
            )
        )

    assert exc.value.status_code == 403
    authorization.assert_not_awaited()
    audit_repository.list_submission_events.assert_not_called()


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "not-valid-base64!",
        "e30",
        "eyJQSyI6ICJ3cm9uZyIsICJTSyI6ICJFVkVOVCN4In0",
    ],
)
def test_invalid_cursor_is_rejected(
    cursor,
):
    with pytest.raises(HTTPException) as exc:
        audit.decode_audit_cursor(
            cursor,
            "tenant-a",
            "submission-123",
        )

    assert exc.value.status_code == 400


def test_cursor_cannot_reference_another_submission():
    cursor = audit.encode_audit_cursor(
        {
            "PK": "TENANT#tenant-b#SUBMISSION#submission-999",
            "SK": "EVENT#2026-11-12T12:00:00Z#event-123",
        }
    )

    with pytest.raises(HTTPException) as exc:
        audit.decode_audit_cursor(
            cursor,
            "tenant-a",
            "submission-123",
        )

    assert exc.value.status_code == 400


def test_cursor_round_trip():
    original = {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": "EVENT#2026-11-12T12:00:00Z#event-123",
    }

    encoded = audit.encode_audit_cursor(original)

    decoded = audit.decode_audit_cursor(
        encoded,
        "tenant-a",
        "submission-123",
    )

    assert decoded == original


def test_next_cursor_is_returned(
    submitter,
    submission_repository,
    audit_repository,
    monkeypatch,
):
    monkeypatch.setattr(
        audit,
        "get_authorized_submission",
        AsyncMock(return_value=MagicMock()),
    )

    last_key = {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": "EVENT#2026-11-12T12:00:00Z#event-123",
    }

    audit_repository.list_submission_events.return_value["LastEvaluatedKey"] = last_key

    result = run_async(
        audit.get_submission_audit_history(
            tenant_id="tenant-a",
            submission_id="submission-123",
            membership=submitter,
            submission_repository=submission_repository,
            audit_repository=audit_repository,
        )
    )

    assert result.next_cursor is not None

    assert (
        audit.decode_audit_cursor(
            result.next_cursor,
            "tenant-a",
            "submission-123",
        )
        == last_key
    )


def test_invalid_audit_event_data_is_rejected(
    submitter,
    submission_repository,
    audit_repository,
    monkeypatch,
):
    monkeypatch.setattr(
        audit,
        "get_authorized_submission",
        AsyncMock(return_value=MagicMock()),
    )

    audit_repository.list_submission_events.return_value = {
        "Items": [
            {
                "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
                "SK": "EVENT#2026-11-12T12:00:00Z#event-123",
                "GSI1PK": "TENANT#tenant-a",
                "GSI1SK": "EVENT#2026-11-12T10:00:00Z#event-123",
                "event_id": "event-123",
                "event_type": "SUBMISSION_STATUS_CHANGED",
                "tenant_id": "tenant-b",
                "submission_id": "submission-123",
                "entity_type": "AUDIT_EVENT",
                "actor_id": "user-a",
                "actor_role": "SUBMITTER",
                "previous_status": "DRAFT",
                "new_status": "SUBMITTED",
                "previous_version": 1,
                "new_version": 2,
                "timestamp": "2026-11-12T12:00:00Z",
                "request_id": "request-123",
            }
        ]
    }

    with pytest.raises(HTTPException) as exc:
        run_async(
            audit.get_submission_audit_history(
                tenant_id="tenant-a",
                submission_id="submission-123",
                membership=submitter,
                submission_repository=submission_repository,
                audit_repository=audit_repository,
            )
        )

    assert exc.value.status_code == 500


def test_audit_cursor_is_passed_to_repository(
    submitter,
    submission_repository,
    audit_repository,
    monkeypatch,
):
    monkeypatch.setattr(
        audit,
        "get_authorized_submission",
        AsyncMock(return_value=MagicMock()),
    )

    cursor_data = {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": "EVENT#2026-11-12T12:00:00Z#event-123",
    }

    cursor = audit.encode_audit_cursor(cursor_data)

    run_async(
        audit.get_submission_audit_history(
            tenant_id="tenant-a",
            submission_id="submission-123",
            membership=submitter,
            submission_repository=submission_repository,
            audit_repository=audit_repository,
            limit=10,
            cursor=cursor,
        )
    )

    audit_repository.list_submission_events.assert_called_once_with(
        "tenant-a",
        "submission-123",
        10,
        cursor_data,
    )


@pytest.mark.parametrize(
    "invalid_result",
    [
        None,
        [],
        "invalid",
        {"Items": {}},
        {"Items": "invalid"},
    ],
)
def test_malformed_repository_response_is_rejected(
    submitter,
    submission_repository,
    audit_repository,
    monkeypatch,
    invalid_result,
):
    monkeypatch.setattr(
        audit,
        "get_authorized_submission",
        AsyncMock(return_value=MagicMock()),
    )
    audit_repository.list_submission_events.return_value = invalid_result

    with pytest.raises(HTTPException) as exc:
        run_async(
            audit.get_submission_audit_history(
                tenant_id="tenant-a",
                submission_id="submission-123",
                membership=submitter,
                submission_repository=submission_repository,
                audit_repository=audit_repository,
            )
        )

    assert exc.value.status_code == 500


@pytest.mark.parametrize(
    "invalid_item",
    [
        None,
        [],
        "invalid",
        {},
    ],
)
def test_malformed_audit_item_is_rejected(
    submitter,
    submission_repository,
    audit_repository,
    monkeypatch,
    invalid_item,
):
    monkeypatch.setattr(
        audit,
        "get_authorized_submission",
        AsyncMock(return_value=MagicMock()),
    )
    audit_repository.list_submission_events.return_value = {
        "Items": [invalid_item],
    }

    with pytest.raises(HTTPException) as exc:
        run_async(
            audit.get_submission_audit_history(
                tenant_id="tenant-a",
                submission_id="submission-123",
                membership=submitter,
                submission_repository=submission_repository,
                audit_repository=audit_repository,
            )
        )

    assert exc.value.status_code == 500


@pytest.mark.parametrize(
    "key_changes",
    [
        {"PK": "TENANT#tenant-b#SUBMISSION#submission-123"},
        {"SK": "EVENT#2026-11-12T12:00:00Z#another-event"},
        {"SK": "OTHER#2026-11-12T12:00:00Z#event-123"},
        {"SK": "EVENT##event-123"},
        {"SK": "EVENT#2026-11-12T12:00:00Z#"},
    ],
)
def test_audit_event_key_must_match_event_identity(
    submitter,
    submission_repository,
    audit_repository,
    monkeypatch,
    key_changes,
):
    monkeypatch.setattr(
        audit,
        "get_authorized_submission",
        AsyncMock(return_value=MagicMock()),
    )

    item = dict(audit_repository.list_submission_events.return_value["Items"][0])
    item.update(key_changes)

    audit_repository.list_submission_events.return_value = {
        "Items": [item],
    }

    with pytest.raises(HTTPException) as exc:
        run_async(
            audit.get_submission_audit_history(
                tenant_id="tenant-a",
                submission_id="submission-123",
                membership=submitter,
                submission_repository=submission_repository,
                audit_repository=audit_repository,
            )
        )

    assert exc.value.status_code == 500


@pytest.mark.parametrize(
    "invalid_key",
    [
        {},
        {
            "PK": "TENANT#tenant-b#SUBMISSION#submission-123",
            "SK": "EVENT#2026-11-12T12:00:00Z#event-123",
        },
        {"PK": "TENANT#tenant-a#SUBMISSION#submission-123", "SK": "OTHER#event-123"},
        {"PK": "TENANT#tenant-a#SUBMISSION#submission-123", "SK": "EVENT##event-123"},
        {
            "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
            "SK": "EVENT#2026-11-12T12:00:00Z#",
        },
    ],
)
def test_invalid_last_evaluated_key_is_rejected(
    submitter,
    submission_repository,
    audit_repository,
    monkeypatch,
    invalid_key,
):
    monkeypatch.setattr(
        audit,
        "get_authorized_submission",
        AsyncMock(return_value=MagicMock()),
    )

    audit_repository.list_submission_events.return_value = {
        "Items": [],
        "LastEvaluatedKey": invalid_key,
    }

    with pytest.raises(HTTPException) as exc:
        run_async(
            audit.get_submission_audit_history(
                tenant_id="tenant-a",
                submission_id="submission-123",
                membership=submitter,
                submission_repository=submission_repository,
                audit_repository=audit_repository,
            )
        )

    assert exc.value.status_code == 500


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5, "20", None])
def test_invalid_audit_limit_is_rejected_before_repository_query(
    submitter,
    submission_repository,
    audit_repository,
    monkeypatch,
    limit,
):
    monkeypatch.setattr(
        audit,
        "get_authorized_submission",
        AsyncMock(return_value=MagicMock()),
    )

    with pytest.raises(HTTPException) as exc:
        run_async(
            audit.get_submission_audit_history(
                tenant_id="tenant-a",
                submission_id="submission-123",
                membership=submitter,
                submission_repository=submission_repository,
                audit_repository=audit_repository,
                limit=limit,
            )
        )

    assert exc.value.status_code == 422
    audit_repository.list_submission_events.assert_not_called()


def test_valid_audit_limit_boundaries_are_accepted(
    submitter,
    submission_repository,
    audit_repository,
    monkeypatch,
):
    monkeypatch.setattr(
        audit,
        "get_authorized_submission",
        AsyncMock(return_value=MagicMock()),
    )

    for limit in (1, 100):
        run_async(
            audit.get_submission_audit_history(
                tenant_id="tenant-a",
                submission_id="submission-123",
                membership=submitter,
                submission_repository=submission_repository,
                audit_repository=audit_repository,
                limit=limit,
            )
        )

    assert audit_repository.list_submission_events.call_count == 2


def test_missing_last_evaluated_key_means_no_next_page(
    submitter,
    submission_repository,
    audit_repository,
    monkeypatch,
):
    monkeypatch.setattr(
        audit,
        "get_authorized_submission",
        AsyncMock(return_value=MagicMock()),
    )

    audit_repository.list_submission_events.return_value = {
        "Items": [],
        "LastEvaluatedKey": None,
    }

    result = run_async(
        audit.get_submission_audit_history(
            tenant_id="tenant-a",
            submission_id="submission-123",
            membership=submitter,
            submission_repository=submission_repository,
            audit_repository=audit_repository,
        )
    )

    assert result.items == []
    assert result.next_cursor is None


@pytest.fixture
def tenant_admin():
    return TenantMembership(
        user_id="admin-a",
        tenant_id="tenant-a",
        role=TenantRole.TENANT_ADMIN,
        status="ACTIVE",
    )


def tenant_submission_event():
    timestamp = "2026-11-12T12:00:00Z"
    event_id = "event-submission-123"

    return {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": f"EVENT#{timestamp}#{event_id}",
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": f"EVENT#{timestamp}#{event_id}",
        "entity_type": "AUDIT_EVENT",
        "event_id": event_id,
        "event_type": "SUBMISSION_STATUS_CHANGED",
        "tenant_id": "tenant-a",
        "submission_id": "submission-123",
        "actor_id": "user-a",
        "actor_role": "SUBMITTER",
        "previous_status": "DRAFT",
        "new_status": "SUBMITTED",
        "previous_version": 1,
        "new_version": 2,
        "timestamp": timestamp,
        "request_id": "request-123",
    }


def tenant_membership_event():
    timestamp = "2026-11-12T13:00:00Z"
    event_id = "event-membership-123"

    return {
        "PK": "TENANT#tenant-a#MEMBERSHIP#user-b",
        "SK": f"EVENT#{timestamp}#{event_id}",
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": f"EVENT#{timestamp}#{event_id}",
        "entity_type": "AUDIT_EVENT",
        "event_id": event_id,
        "event_type": "MEMBERSHIP_ROLE_CHANGED",
        "tenant_id": "tenant-a",
        "target_user_id": "user-b",
        "actor_id": "admin-a",
        "actor_role": "TENANT_ADMIN",
        "previous_role": "SUBMITTER",
        "new_role": "REVIEWER",
        "timestamp": timestamp,
        "request_id": "request-456",
    }


def test_tenant_admin_can_retrieve_mixed_audit_events(
    tenant_admin,
    audit_repository,
):
    audit_repository.list_tenant_events.return_value = {
        "Items": [
            tenant_submission_event(),
            tenant_membership_event(),
        ],
    }

    result = run_async(
        audit.get_tenant_audit_history(
            tenant_id="tenant-a",
            membership=tenant_admin,
            audit_repository=audit_repository,
        )
    )

    assert len(result.items) == 2
    assert result.items[0].event_type == "SUBMISSION_STATUS_CHANGED"
    assert result.items[1].event_type == "MEMBERSHIP_ROLE_CHANGED"

    audit_repository.list_tenant_events.assert_called_once_with(
        "tenant-a",
        20,
        None,
    )


def test_non_admin_cannot_retrieve_tenant_audit_events(
    submitter,
    audit_repository,
):
    with pytest.raises(HTTPException) as exc:
        run_async(
            audit.get_tenant_audit_history(
                tenant_id="tenant-a",
                membership=submitter,
                audit_repository=audit_repository,
            )
        )

    assert exc.value.status_code == 403
    audit_repository.list_tenant_events.assert_not_called()


def test_tenant_mismatch_prevents_tenant_audit_query(
    tenant_admin,
    audit_repository,
):
    with pytest.raises(HTTPException) as exc:
        run_async(
            audit.get_tenant_audit_history(
                tenant_id="tenant-b",
                membership=tenant_admin,
                audit_repository=audit_repository,
            )
        )

    assert exc.value.status_code == 403
    audit_repository.list_tenant_events.assert_not_called()


def test_inactive_tenant_admin_cannot_retrieve_audit_events(
    audit_repository,
):
    inactive_admin = TenantMembership(
        user_id="admin-a",
        tenant_id="tenant-a",
        role=TenantRole.TENANT_ADMIN,
        status="INACTIVE",
    )

    with pytest.raises(HTTPException) as exc:
        run_async(
            audit.get_tenant_audit_history(
                tenant_id="tenant-a",
                membership=inactive_admin,
                audit_repository=audit_repository,
            )
        )

    assert exc.value.status_code == 403
    audit_repository.list_tenant_events.assert_not_called()


def test_tenant_audit_cursor_round_trip():
    original = {
        "PK": "TENANT#tenant-a#MEMBERSHIP#user-b",
        "SK": "EVENT#2026-11-12T13:00:00Z#event-123",
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": "EVENT#2026-11-12T13:00:00Z#event-123",
    }

    encoded = audit.encode_audit_cursor(original)

    decoded = audit.decode_tenant_audit_cursor(
        encoded,
        "tenant-a",
    )

    assert decoded == original


def test_tenant_audit_cursor_cannot_cross_tenant():
    cursor = audit.encode_audit_cursor(
        {
            "PK": "TENANT#tenant-b#SUBMISSION#submission-123",
            "SK": "EVENT#2026-11-12T12:00:00Z#event-123",
            "GSI1PK": "TENANT#tenant-b",
            "GSI1SK": "EVENT#2026-11-12T12:00:00Z#event-123",
        }
    )

    with pytest.raises(HTTPException) as exc:
        audit.decode_tenant_audit_cursor(cursor, "tenant-a")

    assert exc.value.status_code == 400


def test_tenant_audit_pagination_passes_cursor_to_repository(
    tenant_admin,
    audit_repository,
):
    last_key = {
        "PK": "TENANT#tenant-a#MEMBERSHIP#user-b",
        "SK": "EVENT#2026-11-12T13:00:00Z#event-123",
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": "EVENT#2026-11-12T13:00:00Z#event-123",
    }

    audit_repository.list_tenant_events.return_value = {
        "Items": [],
        "LastEvaluatedKey": last_key,
    }

    result = run_async(
        audit.get_tenant_audit_history(
            tenant_id="tenant-a",
            membership=tenant_admin,
            audit_repository=audit_repository,
            limit=10,
        )
    )

    assert result.next_cursor is not None
    assert (
        audit.decode_tenant_audit_cursor(
            result.next_cursor,
            "tenant-a",
        )
        == last_key
    )

    audit_repository.list_tenant_events.assert_called_once_with(
        "tenant-a",
        10,
        None,
    )


@pytest.mark.parametrize(
    "limit",
    [0, -1, 101, True, 1.5, "20"],
)
def test_invalid_tenant_audit_limit_is_rejected(
    tenant_admin,
    audit_repository,
    limit,
):
    with pytest.raises(HTTPException) as exc:
        run_async(
            audit.get_tenant_audit_history(
                tenant_id="tenant-a",
                membership=tenant_admin,
                audit_repository=audit_repository,
                limit=limit,
            )
        )

    assert exc.value.status_code == 422
    audit_repository.list_tenant_events.assert_not_called()


@pytest.mark.parametrize(
    "key_changes",
    [
        {"GSI1PK": "TENANT#tenant-b"},
        {"GSI1SK": "EVENT#2026-11-12T13:00:00Z#different-event"},
        {"PK": "TENANT#tenant-b#MEMBERSHIP#user-b"},
        {"SK": "EVENT#2026-11-12T13:00:00Z#different-event"},
    ],
)
def test_tenant_audit_event_key_must_match_identity(
    tenant_admin,
    audit_repository,
    key_changes,
):
    event = tenant_membership_event()
    event.update(key_changes)

    audit_repository.list_tenant_events.return_value = {
        "Items": [event],
    }

    with pytest.raises(HTTPException) as exc:
        run_async(
            audit.get_tenant_audit_history(
                tenant_id="tenant-a",
                membership=tenant_admin,
                audit_repository=audit_repository,
            )
        )

    assert exc.value.status_code == 500
