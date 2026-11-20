from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_CHANGES = "NEEDS_CHANGES"
    CLOSED = "CLOSED"


SubmissionActorRole = Literal["SUBMITTER", "REVIEWER"]
TenantAdminActorRole = Literal["TENANT_ADMIN"]
MembershipRole = Literal["SUBMITTER", "REVIEWER"]
MembershipStatus = Literal["ACTIVE", "INACTIVE"]


class SubmissionTransitionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    target_status: SubmissionStatus
    expected_version: int = Field(strict=True, ge=1)
    reason: str | None = Field(default=None, min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Reason cannot be blank")

        return value


class SubmissionTransitionResponse(BaseModel):
    tenant_id: str
    submission_id: str
    previous_status: SubmissionStatus
    status: SubmissionStatus
    version: int
    updated_at: str


class AuditEventResponse(BaseModel):
    event_id: str
    event_type: str
    tenant_id: str
    submission_id: str
    actor_id: str
    actor_role: str
    previous_status: str
    new_status: str
    previous_version: int
    new_version: int
    timestamp: str
    request_id: str
    reason: str | None = None


class AuditEventListResponse(BaseModel):
    items: list[AuditEventResponse]
    next_cursor: str | None = None


class TenantAuditEventBase(BaseModel):
    event_id: str
    tenant_id: str
    actor_id: str
    actor_role: str
    timestamp: str
    request_id: str


class TenantSubmissionAuditEvent(TenantAuditEventBase):
    actor_role: SubmissionActorRole
    event_type: Literal["SUBMISSION_STATUS_CHANGED"]
    submission_id: str
    previous_status: SubmissionStatus
    new_status: SubmissionStatus
    previous_version: int
    new_version: int
    reason: str | None = None


class TenantMembershipRoleAuditEvent(TenantAuditEventBase):
    actor_role: TenantAdminActorRole
    event_type: Literal["MEMBERSHIP_ROLE_CHANGED"]
    target_user_id: str
    previous_role: MembershipRole
    new_role: MembershipRole


class TenantMembershipDeactivationAuditEvent(TenantAuditEventBase):
    actor_role: TenantAdminActorRole
    event_type: Literal["MEMBERSHIP_DEACTIVATED"]
    target_user_id: str
    previous_status: MembershipStatus
    new_status: MembershipStatus


TenantAuditEvent = Annotated[
    TenantSubmissionAuditEvent
    | TenantMembershipRoleAuditEvent
    | TenantMembershipDeactivationAuditEvent,
    Field(discriminator="event_type"),
]


class TenantAuditEventListResponse(BaseModel):
    items: list[TenantAuditEvent]
    next_cursor: str | None = None
