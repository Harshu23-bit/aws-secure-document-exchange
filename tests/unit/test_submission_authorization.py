import pytest
from httpx import ASGITransport, AsyncClient

from app.core.authorization import (
    TenantMembership,
    TenantRole,
    get_membership_repository,
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
    def __init__(self, submission=None):
        self.submission = submission
        self.calls = []

    def get_submission(self, tenant_id, submission_id):
        self.calls.append((tenant_id, submission_id))
        return self.submission


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def fake_submission():
    return {
        "tenant_id": "tenant-a",
        "submission_id": "submission-123",
        "owner_id": "user-123",
        "status": "DRAFT",
        "created_at": "2026-11-12T10:00:00Z",
        "updated_at": "2026-11-12T10:00:00Z",
        "version": 1,
    }


@pytest.fixture
def fake_repository(fake_submission):
    return FakeSubmissionRepository(fake_submission.copy())


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
async def test_submitter_can_access_own_submission(
    override_dependencies,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/tenants/tenant-a/submissions/submission-123"
        )

    assert response.status_code == 200
    assert response.json()["submission_id"] == "submission-123"
    assert "owner_id" not in response.json()


@pytest.mark.anyio
async def test_submitter_cannot_access_another_users_submission(
    override_dependencies,
):
    override_dependencies.submission["owner_id"] = "another-user"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/tenants/tenant-a/submissions/submission-123"
        )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_missing_submission_returns_404(
    override_dependencies,
):
    override_dependencies.submission = None

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/tenants/tenant-a/submissions/missing")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_submitter_cannot_access_another_tenant(
    override_dependencies,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/tenants/tenant-b/submissions/submission-123"
        )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_repository_receives_tenant_scoped_lookup(
    override_dependencies,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await client.get("/api/v1/tenants/tenant-a/submissions/submission-123")

    assert override_dependencies.calls == [("tenant-a", "submission-123")]


@pytest.mark.anyio
async def test_reviewer_can_access_tenant_submission(
    override_dependencies,
):
    from app.core.authorization import get_tenant_membership

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
        response = await client.get(
            "/api/v1/tenants/tenant-a/submissions/submission-123"
        )

    assert response.status_code == 200
    assert response.json()["submission_id"] == "submission-123"
