import pytest
from httpx import ASGITransport, AsyncClient

from app.core.authorization import (
    TenantMembership,
    TenantRole,
    get_membership_repository,
    get_tenant_membership,
)
from app.core.security import AuthenticatedUser, get_current_user
from app.main import app
from app.services.submissions import get_submission_repository


class FakeMembershipRepository:
    def get_membership(self, user_id, tenant_id):
        if user_id == "user-123" and tenant_id == "tenant-a":
            return {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "role": "SUBMITTER",
                "status": "ACTIVE",
            }

        return None


class FakeSubmissionRepository:
    def __init__(self):
        self.created_submissions = []

    def create_submission(self, submission):
        self.created_submissions.append(submission.copy())

    def get_submission(self, tenant_id, submission_id):
        return None


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def fake_repository():
    return FakeSubmissionRepository()


@pytest.fixture
def override_dependencies(fake_repository):
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        sub="user-123",
        client_id="test-client",
        token_use="access",
        scope="openid email cloudsec-api/access",
    )

    app.dependency_overrides[get_membership_repository] = FakeMembershipRepository

    app.dependency_overrides[get_submission_repository] = lambda: fake_repository

    yield fake_repository

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_submitter_can_create_submission(override_dependencies):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/tenants/tenant-a/submissions",
            json={
                "title": "Vendor Onboarding - ABC Ltd",
                "description": "Initial onboarding documents",
            },
        )

    assert response.status_code == 201

    body = response.json()

    assert body["tenant_id"] == "tenant-a"
    assert body["title"] == "Vendor Onboarding - ABC Ltd"
    assert body["status"] == "DRAFT"
    assert body["version"] == 1
    assert "submission_id" in body

    assert len(override_dependencies.created_submissions) == 1


@pytest.mark.anyio
async def test_creation_uses_authenticated_identity(override_dependencies):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/tenants/tenant-a/submissions",
            json={
                "title": "Vendor Onboarding",
                "owner_id": "attacker-controlled-user",
                "status": "APPROVED",
                "version": 99,
            },
        )

    assert response.status_code == 422
    assert override_dependencies.created_submissions == []


@pytest.mark.anyio
async def test_reviewer_cannot_create_submission(override_dependencies):
    reviewer = TenantMembership(
        user_id="reviewer-123",
        tenant_id="tenant-a",
        role=TenantRole.REVIEWER,
        status="ACTIVE",
    )

    app.dependency_overrides[get_tenant_membership] = lambda: reviewer

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/tenants/tenant-a/submissions",
            json={
                "title": "Unauthorized submission",
            },
        )

    assert response.status_code == 403
    assert override_dependencies.created_submissions == []


@pytest.mark.anyio
async def test_user_cannot_create_submission_in_another_tenant(
    override_dependencies,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/tenants/tenant-b/submissions",
            json={
                "title": "Cross-tenant submission",
            },
        )

    assert response.status_code == 403
    assert override_dependencies.created_submissions == []


@pytest.mark.anyio
async def test_submission_creation_generates_secure_server_fields(
    override_dependencies,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await client.post(
            "/api/v1/tenants/tenant-a/submissions",
            json={
                "title": "Secure submission",
            },
        )

    submission = override_dependencies.created_submissions[0]

    assert submission["owner_id"] == "user-123"
    assert submission["tenant_id"] == "tenant-a"
    assert submission["status"] == "DRAFT"
    assert submission["version"] == 1

    assert submission["PK"] == "TENANT#tenant-a"
    assert submission["SK"].startswith("SUBMISSION#")

    assert submission["GSI1PK"] == "TENANT#tenant-a#USER#user-123"
    assert submission["GSI1SK"].startswith("CREATED#")

    assert submission["GSI2PK"] == "TENANT#tenant-a#STATUS#DRAFT"
    assert submission["GSI2SK"].startswith("CREATED#")

    assert submission["created_at"] == submission["updated_at"]


@pytest.mark.anyio
async def test_submission_title_is_required(override_dependencies):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/tenants/tenant-a/submissions",
            json={},
        )

    assert response.status_code == 422
    assert override_dependencies.created_submissions == []


@pytest.mark.anyio
async def test_submission_title_cannot_be_too_short(override_dependencies):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/tenants/tenant-a/submissions",
            json={
                "title": "AB",
            },
        )

    assert response.status_code == 422
    assert override_dependencies.created_submissions == []
