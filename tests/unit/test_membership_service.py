import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.core.authorization import TenantMembership, TenantRole
from app.core.logging import request_id_context
from app.repositories.membership import (
    MembershipActorAuthorizationError,
    MembershipStateConflictError,
)
from app.schemas.membership import (
    ChangeMemberRoleRequest,
    DeactivateMemberRequest,
)
from app.services import memberships


@pytest.fixture
def admin():
    return TenantMembership(
        user_id="admin-a",
        tenant_id="tenant-a",
        role=TenantRole.TENANT_ADMIN,
        status="ACTIVE",
    )


@pytest.fixture
def repository():
    return MagicMock()


def run_async(coroutine):
    return asyncio.run(coroutine)


def prepare_deterministic_event(monkeypatch):
    monkeypatch.setattr(
        memberships,
        "get_timestamp",
        lambda: "2026-11-17T12:00:00Z",
    )
    monkeypatch.setattr(
        memberships,
        "uuid4",
        lambda: "event-123",
    )


def test_change_member_role_builds_correct_audit_event(
    admin,
    repository,
    monkeypatch,
):
    prepare_deterministic_event(monkeypatch)

    token = request_id_context.set("request-123")

    try:
        result = run_async(
            memberships.change_member_role(
                tenant_id="tenant-a",
                target_user_id="user-b",
                request=ChangeMemberRoleRequest(
                    expected_role="SUBMITTER",
                    new_role="REVIEWER",
                ),
                membership=admin,
                repository=repository,
            )
        )
    finally:
        request_id_context.reset(token)

    assert result.user_id == "user-b"
    assert result.tenant_id == "tenant-a"
    assert result.role == "REVIEWER"
    assert result.status == "ACTIVE"
    assert result.updated_at == "2026-11-17T12:00:00Z"

    repository.change_member_role.assert_called_once()

    args = repository.change_member_role.call_args.args

    assert args[:6] == (
        "tenant-a",
        "admin-a",
        "user-b",
        "SUBMITTER",
        "REVIEWER",
        "2026-11-17T12:00:00Z",
    )

    event = args[6]

    assert event == {
        "PK": "TENANT#tenant-a#MEMBERSHIP#user-b",
        "SK": "EVENT#2026-11-17T12:00:00Z#event-123",
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": "EVENT#2026-11-17T12:00:00Z#event-123",
        "entity_type": "AUDIT_EVENT",
        "event_id": "event-123",
        "event_type": "MEMBERSHIP_ROLE_CHANGED",
        "tenant_id": "tenant-a",
        "target_user_id": "user-b",
        "actor_id": "admin-a",
        "actor_role": "TENANT_ADMIN",
        "timestamp": "2026-11-17T12:00:00Z",
        "request_id": "request-123",
        "previous_role": "SUBMITTER",
        "new_role": "REVIEWER",
    }


def test_deactivate_member_builds_status_audit_event(
    admin,
    repository,
    monkeypatch,
):
    prepare_deterministic_event(monkeypatch)

    token = request_id_context.set("request-456")

    try:
        result = run_async(
            memberships.deactivate_member(
                tenant_id="tenant-a",
                target_user_id="user-b",
                request=DeactivateMemberRequest(
                    expected_role="REVIEWER",
                ),
                membership=admin,
                repository=repository,
            )
        )
    finally:
        request_id_context.reset(token)

    assert result.user_id == "user-b"
    assert result.tenant_id == "tenant-a"
    assert result.role == "REVIEWER"
    assert result.status == "INACTIVE"
    assert result.updated_at == "2026-11-17T12:00:00Z"

    repository.deactivate_member.assert_called_once()

    args = repository.deactivate_member.call_args.args

    assert args[:5] == (
        "tenant-a",
        "admin-a",
        "user-b",
        "REVIEWER",
        "2026-11-17T12:00:00Z",
    )

    event = args[5]

    assert event["event_type"] == "MEMBERSHIP_DEACTIVATED"
    assert event["previous_status"] == "ACTIVE"
    assert event["new_status"] == "INACTIVE"
    assert event["actor_id"] == "admin-a"
    assert event["actor_role"] == "TENANT_ADMIN"
    assert event["request_id"] == "request-456"

    assert "previous_role" not in event
    assert "new_role" not in event


@pytest.mark.parametrize(
    ("tenant_id", "role", "membership_status"),
    [
        ("tenant-a", TenantRole.SUBMITTER, "ACTIVE"),
        ("tenant-a", TenantRole.REVIEWER, "ACTIVE"),
        ("tenant-a", TenantRole.TENANT_ADMIN, "INACTIVE"),
        ("tenant-b", TenantRole.TENANT_ADMIN, "ACTIVE"),
    ],
)
def test_role_change_rejects_invalid_admin_membership(
    repository,
    tenant_id,
    role,
    membership_status,
):
    membership = TenantMembership(
        user_id="admin-a",
        tenant_id=tenant_id,
        role=role,
        status=membership_status,
    )

    with pytest.raises(HTTPException) as exc_info:
        run_async(
            memberships.change_member_role(
                tenant_id="tenant-a",
                target_user_id="user-b",
                request=ChangeMemberRoleRequest(
                    expected_role="SUBMITTER",
                    new_role="REVIEWER",
                ),
                membership=membership,
                repository=repository,
            )
        )

    assert exc_info.value.status_code == 403
    repository.change_member_role.assert_not_called()


def test_deactivation_rejects_invalid_admin_membership(
    repository,
):
    inactive_admin = TenantMembership(
        user_id="admin-a",
        tenant_id="tenant-a",
        role=TenantRole.TENANT_ADMIN,
        status="INACTIVE",
    )

    with pytest.raises(HTTPException) as exc_info:
        run_async(
            memberships.deactivate_member(
                tenant_id="tenant-a",
                target_user_id="user-b",
                request=DeactivateMemberRequest(
                    expected_role="REVIEWER",
                ),
                membership=inactive_admin,
                repository=repository,
            )
        )

    assert exc_info.value.status_code == 403
    repository.deactivate_member.assert_not_called()


@pytest.mark.parametrize(
    ("repository_error", "expected_status"),
    [
        (MembershipActorAuthorizationError(), 403),
        (MembershipStateConflictError(), 409),
    ],
)
def test_role_change_maps_repository_errors(
    admin,
    repository,
    repository_error,
    expected_status,
):
    repository.change_member_role.side_effect = repository_error

    with pytest.raises(HTTPException) as exc_info:
        run_async(
            memberships.change_member_role(
                tenant_id="tenant-a",
                target_user_id="user-b",
                request=ChangeMemberRoleRequest(
                    expected_role="SUBMITTER",
                    new_role="REVIEWER",
                ),
                membership=admin,
                repository=repository,
            )
        )

    assert exc_info.value.status_code == expected_status


@pytest.mark.parametrize(
    ("repository_error", "expected_status"),
    [
        (MembershipActorAuthorizationError(), 403),
        (MembershipStateConflictError(), 409),
    ],
)
def test_deactivation_maps_repository_errors(
    admin,
    repository,
    repository_error,
    expected_status,
):
    repository.deactivate_member.side_effect = repository_error

    with pytest.raises(HTTPException) as exc_info:
        run_async(
            memberships.deactivate_member(
                tenant_id="tenant-a",
                target_user_id="user-b",
                request=DeactivateMemberRequest(
                    expected_role="REVIEWER",
                ),
                membership=admin,
                repository=repository,
            )
        )

    assert exc_info.value.status_code == expected_status


def test_unexpected_repository_error_propagates(
    admin,
    repository,
):
    repository.change_member_role.side_effect = RuntimeError(
        "Unexpected database failure"
    )

    with pytest.raises(RuntimeError, match="Unexpected database failure"):
        run_async(
            memberships.change_member_role(
                tenant_id="tenant-a",
                target_user_id="user-b",
                request=ChangeMemberRoleRequest(
                    expected_role="SUBMITTER",
                    new_role="REVIEWER",
                ),
                membership=admin,
                repository=repository,
            )
        )
