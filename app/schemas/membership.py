from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

MemberRole = Literal["SUBMITTER", "REVIEWER"]


class ChangeMemberRoleRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    expected_role: MemberRole
    new_role: MemberRole

    @model_validator(mode="after")
    def validate_role_change(self):
        if self.expected_role == self.new_role:
            raise ValueError("The new role must differ from the expected role")

        return self


class DeactivateMemberRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    expected_role: MemberRole


class MembershipMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    tenant_id: str
    role: MemberRole
    status: Literal["ACTIVE", "INACTIVE"]
    updated_at: str
