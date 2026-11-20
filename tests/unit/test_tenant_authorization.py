import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.authorization import (
    TenantMembership,
    TenantRole,
    get_membership_repository,
    require_tenant_admin,
)
from app.core.security import AuthenticatedUser, get_current_user
from app.main import app
from app.repositories.membership import (
    MembershipActorAuthorizationError,
    MembershipStateConflictError,
)


class FakeMembershipRepository:
    def __init__(self, membership=None):
        self.membership = membership
        self.calls = []

    def get_membership(self, user_id, tenant_id):
        self.calls.append((user_id, tenant_id))
        return self.membership

    def list_memberships(self, user_id):
        self.list_calls = getattr(self, "list_calls", [])
        self.list_calls.append(user_id)

        if self.membership is None:
            return []

        return [self.membership]

    def list_tenant_members(self, tenant_id):
        self.tenant_member_calls = getattr(
            self,
            "tenant_member_calls",
            [],
        )
        self.tenant_member_calls.append(tenant_id)

        return getattr(self, "tenant_members", [])

    def change_member_role(
        self,
        tenant_id,
        actor_id,
        target_user_id,
        expected_role,
        new_role,
        updated_at,
        audit_event,
    ):
        self.mutation_calls = getattr(self, "mutation_calls", [])
        self.mutation_calls.append(
            {
                "operation": "change_role",
                "tenant_id": tenant_id,
                "actor_id": actor_id,
                "target_user_id": target_user_id,
                "expected_role": expected_role,
                "new_role": new_role,
                "updated_at": updated_at,
                "audit_event": audit_event,
            }
        )

        if actor_id == target_user_id:
            raise MembershipActorAuthorizationError

        if getattr(self, "mutation_error", None):
            raise self.mutation_error

    def deactivate_member(
        self,
        tenant_id,
        actor_id,
        target_user_id,
        expected_role,
        updated_at,
        audit_event,
    ):
        self.mutation_calls = getattr(self, "mutation_calls", [])
        self.mutation_calls.append(
            {
                "operation": "deactivate",
                "tenant_id": tenant_id,
                "actor_id": actor_id,
                "target_user_id": target_user_id,
                "expected_role": expected_role,
                "updated_at": updated_at,
                "audit_event": audit_event,
            }
        )

        if actor_id == target_user_id:
            raise MembershipActorAuthorizationError

        if getattr(self, "mutation_error", None):
            raise self.mutation_error


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def authenticated_user():
    return AuthenticatedUser(
        sub="user-123",
        client_id="test-client",
        token_use="access",
        scope="openid email cloudsec-api/access",
    )


@pytest.fixture
def fake_repository():
    return FakeMembershipRepository(
        {
            "user_id": "user-123",
            "tenant_id": "tenant-a",
            "role": "SUBMITTER",
            "status": "ACTIVE",
        }
    )


@pytest.fixture
def override_dependencies(authenticated_user, fake_repository):
    app.dependency_overrides[get_current_user] = lambda: authenticated_user
    app.dependency_overrides[get_membership_repository] = lambda: fake_repository
    yield fake_repository
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_active_submitter_can_access_tenant(override_dependencies):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-a/context")
        assert response.status_code == 200
        assert response.json()["tenant_id"] == "tenant-a"
        assert response.json()["user_id"] == "user-123"
        assert response.json()["role"] == "SUBMITTER"


@pytest.mark.anyio
async def test_active_reviewer_can_access_tenant(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["role"] = "REVIEWER"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-a/context")

    assert response.status_code == 200
    assert response.json()["role"] == "REVIEWER"


@pytest.mark.anyio
async def test_missing_membership_is_denied(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership = None
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-a/context")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_inactive_membership_is_denied(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["status"] = "INACTIVE"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-a/context")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_membership_for_another_user_is_denied(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["user_id"] = "another-user"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-a/context")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_membership_for_another_tenant_is_denied(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["tenant_id"] = "tenant-b"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-a/context")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_unknown_role_is_denied(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["role"] = "SUPERUSER"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-a/context")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_missing_role_is_denied(
    override_dependencies,
    fake_repository,
):
    del fake_repository.membership["role"]
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-a/context")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_membership_lookup_uses_authenticated_identity(
    override_dependencies,
    fake_repository,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await client.get("/api/v1/tenants/tenant-a/context")
    assert fake_repository.calls == [("user-123", "tenant-a")]


@pytest.mark.anyio
async def test_user_cannot_access_another_tenant(
    override_dependencies,
    fake_repository,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-b/context")
    assert response.status_code == 403
    assert fake_repository.calls == [("user-123", "tenant-b")]


@pytest.mark.anyio
async def test_user_can_discover_active_tenants(
    override_dependencies,
    fake_repository,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants")

    assert response.status_code == 200
    assert response.json() == [
        {
            "tenant_id": "tenant-a",
            "role": "SUBMITTER",
        }
    ]


@pytest.mark.anyio
async def test_tenant_discovery_uses_authenticated_identity(
    override_dependencies,
    fake_repository,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants")

    assert response.status_code == 200
    assert fake_repository.list_calls == ["user-123"]


@pytest.mark.anyio
async def test_tenant_discovery_excludes_inactive_memberships(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["status"] = "INACTIVE"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_tenant_discovery_does_not_expose_internal_fields(
    override_dependencies,
    fake_repository,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants")

    assert set(response.json()[0].keys()) == {
        "tenant_id",
        "role",
    }


@pytest.mark.anyio
async def test_tenant_admin_dependency_accepts_tenant_admin():
    membership = TenantMembership(
        user_id="user-123",
        tenant_id="tenant-a",
        role=TenantRole.TENANT_ADMIN,
        status="ACTIVE",
    )

    result = await require_tenant_admin(membership)

    assert result == membership


@pytest.mark.anyio
@pytest.mark.parametrize(
    "role",
    [
        TenantRole.SUBMITTER,
        TenantRole.REVIEWER,
    ],
)
async def test_non_admin_roles_are_denied_tenant_admin_access(role):
    membership = TenantMembership(
        user_id="user-123",
        tenant_id="tenant-a",
        role=role,
        status="ACTIVE",
    )

    with pytest.raises(HTTPException) as exc_info:
        await require_tenant_admin(membership)

    assert exc_info.value.status_code == 403


@pytest.mark.anyio
async def test_tenant_admin_can_discover_tenant(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["role"] = "TENANT_ADMIN"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants")

    assert response.status_code == 200
    assert response.json() == [
        {
            "tenant_id": "tenant-a",
            "role": "TENANT_ADMIN",
        }
    ]


@pytest.mark.anyio
async def test_tenant_admin_can_list_tenant_members(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["role"] = "TENANT_ADMIN"

    fake_repository.tenant_members = [
        {
            "user_id": "user-123",
            "tenant_id": "tenant-a",
            "role": "TENANT_ADMIN",
            "status": "ACTIVE",
            "created_at": "2026-11-17T10:00:00Z",
            "PK": "USER#user-123",
            "SK": "TENANT#tenant-a",
            "GSI1PK": "TENANT#tenant-a",
        },
        {
            "user_id": "user-456",
            "tenant_id": "tenant-a",
            "role": "REVIEWER",
            "status": "INACTIVE",
            "created_at": "2026-11-17T10:05:00Z",
            "PK": "USER#user-456",
            "SK": "TENANT#tenant-a",
            "GSI1PK": "TENANT#tenant-a",
        },
    ]

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-a/members")

    assert response.status_code == 200

    assert response.json() == [
        {
            "user_id": "user-123",
            "tenant_id": "tenant-a",
            "role": "TENANT_ADMIN",
            "status": "ACTIVE",
            "created_at": "2026-11-17T10:00:00Z",
        },
        {
            "user_id": "user-456",
            "tenant_id": "tenant-a",
            "role": "REVIEWER",
            "status": "INACTIVE",
            "created_at": "2026-11-17T10:05:00Z",
        },
    ]

    assert fake_repository.tenant_member_calls == ["tenant-a"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "role",
    ["SUBMITTER", "REVIEWER"],
)
async def test_non_admin_cannot_list_tenant_members(
    override_dependencies,
    fake_repository,
    role,
):
    fake_repository.membership["role"] = role

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-a/members")

    assert response.status_code == 403

    assert (
        getattr(
            fake_repository,
            "tenant_member_calls",
            [],
        )
        == []
    )


@pytest.mark.anyio
async def test_tenant_admin_cannot_list_another_tenants_members(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["role"] = "TENANT_ADMIN"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-b/members")

    assert response.status_code == 403

    assert (
        getattr(
            fake_repository,
            "tenant_member_calls",
            [],
        )
        == []
    )


@pytest.mark.anyio
async def test_tenant_member_listing_filters_invalid_records(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["role"] = "TENANT_ADMIN"

    fake_repository.tenant_members = [
        {
            "user_id": "valid-user",
            "tenant_id": "tenant-a",
            "role": "SUBMITTER",
            "status": "ACTIVE",
            "PK": "internal-key",
        },
        {
            "user_id": "other-tenant-user",
            "tenant_id": "tenant-b",
            "role": "REVIEWER",
            "status": "ACTIVE",
        },
        {
            "user_id": "invalid-role-user",
            "tenant_id": "tenant-a",
            "role": "SUPERUSER",
            "status": "ACTIVE",
        },
        {
            "user_id": "invalid-status-user",
            "tenant_id": "tenant-a",
            "role": "REVIEWER",
            "status": "DELETED",
        },
        {
            "user_id": "invalid-type-user",
            "tenant_id": "tenant-a",
            "role": [],
            "status": "ACTIVE",
        },
        {
            "tenant_id": "tenant-a",
            "role": "SUBMITTER",
            "status": "ACTIVE",
        },
    ]

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-a/members")

    assert response.status_code == 200

    result = response.json()

    assert len(result) == 1
    assert result[0]["user_id"] == "valid-user"

    assert set(result[0]) == {
        "user_id",
        "tenant_id",
        "role",
        "status",
        "created_at",
    }

    assert result[0]["created_at"] is None


@pytest.mark.anyio
async def test_tenant_admin_can_change_member_role(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["role"] = "TENANT_ADMIN"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.patch(
            "/api/v1/tenants/tenant-a/members/user-456/role",
            json={
                "expected_role": "SUBMITTER",
                "new_role": "REVIEWER",
            },
        )

    assert response.status_code == 200

    result = response.json()

    assert result["user_id"] == "user-456"
    assert result["tenant_id"] == "tenant-a"
    assert result["role"] == "REVIEWER"
    assert result["status"] == "ACTIVE"
    assert result["updated_at"]

    call = fake_repository.mutation_calls[0]

    assert call["operation"] == "change_role"
    assert call["actor_id"] == "user-123"
    assert call["target_user_id"] == "user-456"
    assert call["expected_role"] == "SUBMITTER"
    assert call["new_role"] == "REVIEWER"

    event = call["audit_event"]

    assert event["event_type"] == "MEMBERSHIP_ROLE_CHANGED"
    assert event["GSI1PK"] == "TENANT#tenant-a"
    assert event["GSI1SK"].startswith("EVENT#")
    assert event["actor_id"] == "user-123"
    assert event["actor_role"] == "TENANT_ADMIN"
    assert event["target_user_id"] == "user-456"
    assert event["previous_role"] == "SUBMITTER"
    assert event["new_role"] == "REVIEWER"
    assert event["tenant_id"] == "tenant-a"


@pytest.mark.anyio
async def test_tenant_admin_can_deactivate_member(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["role"] = "TENANT_ADMIN"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/tenants/tenant-a/members/user-456/deactivate",
            json={
                "expected_role": "REVIEWER",
            },
        )

    assert response.status_code == 200

    result = response.json()

    assert result["user_id"] == "user-456"
    assert result["tenant_id"] == "tenant-a"
    assert result["role"] == "REVIEWER"
    assert result["status"] == "INACTIVE"
    assert result["updated_at"]

    call = fake_repository.mutation_calls[0]

    assert call["operation"] == "deactivate"
    assert call["actor_id"] == "user-123"
    assert call["target_user_id"] == "user-456"
    assert call["expected_role"] == "REVIEWER"

    event = call["audit_event"]

    assert event["event_type"] == "MEMBERSHIP_DEACTIVATED"
    assert event["GSI1PK"] == "TENANT#tenant-a"
    assert event["GSI1SK"].startswith("EVENT#")
    assert event["previous_status"] == "ACTIVE"
    assert event["new_status"] == "INACTIVE"
    assert "previous_role" not in event
    assert "new_role" not in event


@pytest.mark.anyio
@pytest.mark.parametrize(
    "role",
    ["SUBMITTER", "REVIEWER"],
)
async def test_non_admin_cannot_change_member_role(
    override_dependencies,
    fake_repository,
    role,
):
    fake_repository.membership["role"] = role

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.patch(
            "/api/v1/tenants/tenant-a/members/user-456/role",
            json={
                "expected_role": "SUBMITTER",
                "new_role": "REVIEWER",
            },
        )

    assert response.status_code == 403
    assert getattr(fake_repository, "mutation_calls", []) == []


@pytest.mark.anyio
async def test_tenant_admin_cannot_modify_another_tenants_member(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["role"] = "TENANT_ADMIN"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.patch(
            "/api/v1/tenants/tenant-b/members/user-456/role",
            json={
                "expected_role": "SUBMITTER",
                "new_role": "REVIEWER",
            },
        )

    assert response.status_code == 403
    assert getattr(fake_repository, "mutation_calls", []) == []


@pytest.mark.anyio
async def test_tenant_admin_cannot_change_own_role(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["role"] = "TENANT_ADMIN"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.patch(
            "/api/v1/tenants/tenant-a/members/user-123/role",
            json={
                "expected_role": "SUBMITTER",
                "new_role": "REVIEWER",
            },
        )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_tenant_admin_cannot_deactivate_self(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["role"] = "TENANT_ADMIN"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/tenants/tenant-a/members/user-123/deactivate",
            json={
                "expected_role": "REVIEWER",
            },
        )

    assert response.status_code == 403


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {
            "expected_role": "TENANT_ADMIN",
            "new_role": "REVIEWER",
        },
        {
            "expected_role": "SUBMITTER",
            "new_role": "TENANT_ADMIN",
        },
        {
            "expected_role": "SUBMITTER",
            "new_role": "SUBMITTER",
        },
        {
            "expected_role": "INVALID",
            "new_role": "REVIEWER",
        },
        {
            "expected_role": "SUBMITTER",
            "new_role": "REVIEWER",
            "actor_id": "attacker",
        },
    ],
)
async def test_invalid_role_change_request_is_rejected(
    override_dependencies,
    fake_repository,
    payload,
):
    fake_repository.membership["role"] = "TENANT_ADMIN"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.patch(
            "/api/v1/tenants/tenant-a/members/user-456/role",
            json=payload,
        )

    assert response.status_code == 422
    assert getattr(fake_repository, "mutation_calls", []) == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {"expected_role": "TENANT_ADMIN"},
        {"expected_role": "INVALID"},
        {
            "expected_role": "REVIEWER",
            "actor_id": "attacker",
        },
    ],
)
async def test_invalid_deactivation_request_is_rejected(
    override_dependencies,
    fake_repository,
    payload,
):
    fake_repository.membership["role"] = "TENANT_ADMIN"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/tenants/tenant-a/members/user-456/deactivate",
            json=payload,
        )

    assert response.status_code == 422
    assert getattr(fake_repository, "mutation_calls", []) == []


@pytest.mark.anyio
async def test_stale_membership_role_returns_conflict(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["role"] = "TENANT_ADMIN"
    fake_repository.mutation_error = MembershipStateConflictError()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.patch(
            "/api/v1/tenants/tenant-a/members/user-456/role",
            json={
                "expected_role": "SUBMITTER",
                "new_role": "REVIEWER",
            },
        )

    assert response.status_code == 409
    assert len(fake_repository.mutation_calls) == 1


@pytest.mark.anyio
async def test_actor_losing_admin_privileges_returns_forbidden(
    override_dependencies,
    fake_repository,
):
    fake_repository.membership["role"] = "TENANT_ADMIN"
    fake_repository.mutation_error = MembershipActorAuthorizationError()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.patch(
            "/api/v1/tenants/tenant-a/members/user-456/role",
            json={
                "expected_role": "SUBMITTER",
                "new_role": "REVIEWER",
            },
        )

    assert response.status_code == 403
