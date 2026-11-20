import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.workflow import (
    TenantAuditEvent,
    TenantMembershipDeactivationAuditEvent,
    TenantMembershipRoleAuditEvent,
    TenantSubmissionAuditEvent,
)

audit_event_adapter = TypeAdapter(TenantAuditEvent)


def submission_event():
    return {
        "event_id": "event-123",
        "event_type": "SUBMISSION_STATUS_CHANGED",
        "tenant_id": "tenant-123",
        "submission_id": "submission-123",
        "actor_id": "user-123",
        "actor_role": "SUBMITTER",
        "previous_status": "DRAFT",
        "new_status": "SUBMITTED",
        "previous_version": 1,
        "new_version": 2,
        "timestamp": "2026-11-20T10:00:00Z",
        "request_id": "request-123",
        "reason": None,
    }


def membership_role_event():
    return {
        "event_id": "event-456",
        "event_type": "MEMBERSHIP_ROLE_CHANGED",
        "tenant_id": "tenant-123",
        "actor_id": "admin-123",
        "actor_role": "TENANT_ADMIN",
        "target_user_id": "user-456",
        "previous_role": "SUBMITTER",
        "new_role": "REVIEWER",
        "timestamp": "2026-11-20T10:00:00Z",
        "request_id": "request-456",
    }


def membership_deactivation_event():
    return {
        "event_id": "event-789",
        "event_type": "MEMBERSHIP_DEACTIVATED",
        "tenant_id": "tenant-123",
        "actor_id": "admin-123",
        "actor_role": "TENANT_ADMIN",
        "target_user_id": "user-789",
        "previous_status": "ACTIVE",
        "new_status": "INACTIVE",
        "timestamp": "2026-11-20T10:00:00Z",
        "request_id": "request-789",
    }


@pytest.mark.parametrize(
    ("payload", "expected_model"),
    [
        (submission_event(), TenantSubmissionAuditEvent),
        (membership_role_event(), TenantMembershipRoleAuditEvent),
        (
            membership_deactivation_event(),
            TenantMembershipDeactivationAuditEvent,
        ),
    ],
)
def test_tenant_audit_union_accepts_valid_events(payload, expected_model):
    result = audit_event_adapter.validate_python(payload)

    assert isinstance(result, expected_model)


@pytest.mark.parametrize(
    ("payload", "field", "invalid_value"),
    [
        (submission_event(), "actor_role", "TENANT_ADMIN"),
        (submission_event(), "new_status", "ARCHIVED"),
        (membership_role_event(), "actor_role", "REVIEWER"),
        (membership_role_event(), "new_role", "TENANT_ADMIN"),
        (membership_deactivation_event(), "actor_role", "SUBMITTER"),
        (membership_deactivation_event(), "new_status", "DELETED"),
    ],
)
def test_tenant_audit_union_rejects_invalid_values(
    payload, field, invalid_value
):
    payload[field] = invalid_value

    with pytest.raises(ValidationError):
        audit_event_adapter.validate_python(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {
            **submission_event(),
            "event_type": "MEMBERSHIP_ROLE_CHANGED",
        },
        {
            **membership_role_event(),
            "event_type": "UNKNOWN_EVENT",
        },
    ],
)
def test_tenant_audit_union_rejects_invalid_discriminators(payload):
    with pytest.raises(ValidationError):
        audit_event_adapter.validate_python(payload)
