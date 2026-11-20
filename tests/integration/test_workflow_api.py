import pytest

BASE_URL = "/api/v1/tenants/tenant-a/submissions/submission-123/transitions"


@pytest.mark.anyio
async def test_submitter_can_submit_own_draft(
    client,
    api_dependencies,
):
    response = await client.post(
        BASE_URL,
        json={
            "target_status": "SUBMITTED",
            "expected_version": 1,
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["tenant_id"] == "tenant-a"
    assert body["submission_id"] == "submission-123"
    assert body["previous_status"] == "DRAFT"
    assert body["status"] == "SUBMITTED"
    assert body["version"] == 2
    assert "updated_at" in body

    repository = api_dependencies["workflow_repository"]

    repository.transition_submission.assert_called_once()


@pytest.mark.anyio
async def test_reviewer_can_start_review(
    client,
    api_dependencies,
):
    api_dependencies["membership_repository"].get_membership.return_value = {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "role": "REVIEWER",
        "status": "ACTIVE",
    }

    api_dependencies["workflow_repository"].get_submission.return_value["status"] = (
        "SUBMITTED"
    )

    response = await client.post(
        BASE_URL,
        json={
            "target_status": "IN_REVIEW",
            "expected_version": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["previous_status"] == "SUBMITTED"
    assert response.json()["status"] == "IN_REVIEW"


@pytest.mark.anyio
async def test_reviewer_can_approve_submission(
    client,
    api_dependencies,
):
    api_dependencies["membership_repository"].get_membership.return_value = {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "role": "REVIEWER",
        "status": "ACTIVE",
    }

    api_dependencies["workflow_repository"].get_submission.return_value["status"] = (
        "IN_REVIEW"
    )

    response = await client.post(
        BASE_URL,
        json={
            "target_status": "APPROVED",
            "expected_version": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"


@pytest.mark.anyio
async def test_submitter_cannot_approve_submission(
    client,
    api_dependencies,
):
    api_dependencies["workflow_repository"].get_submission.return_value["status"] = (
        "IN_REVIEW"
    )

    response = await client.post(
        BASE_URL,
        json={
            "target_status": "APPROVED",
            "expected_version": 1,
        },
    )

    assert response.status_code == 409

    assert (
        response.json()["error"]["message"]
        == "This workflow transition is not permitted"
    )

    api_dependencies["workflow_repository"].transition_submission.assert_not_called()


@pytest.mark.anyio
async def test_inactive_membership_is_denied(
    client,
    api_dependencies,
):
    api_dependencies["membership_repository"].get_membership.return_value["status"] = (
        "INACTIVE"
    )

    response = await client.post(
        BASE_URL,
        json={
            "target_status": "SUBMITTED",
            "expected_version": 1,
        },
    )

    assert response.status_code == 403

    api_dependencies["workflow_repository"].get_submission.assert_not_called()


@pytest.mark.anyio
async def test_missing_membership_is_denied(
    client,
    api_dependencies,
):
    api_dependencies["membership_repository"].get_membership.return_value = None

    response = await client.post(
        BASE_URL,
        json={
            "target_status": "SUBMITTED",
            "expected_version": 1,
        },
    )

    assert response.status_code == 403

    api_dependencies["workflow_repository"].get_submission.assert_not_called()


@pytest.mark.anyio
async def test_membership_identity_mismatch_is_denied(
    client,
    api_dependencies,
):
    api_dependencies["membership_repository"].get_membership.return_value = {
        "user_id": "another-user",
        "tenant_id": "tenant-a",
        "role": "SUBMITTER",
        "status": "ACTIVE",
    }

    response = await client.post(
        BASE_URL,
        json={
            "target_status": "SUBMITTED",
            "expected_version": 1,
        },
    )

    assert response.status_code == 403

    api_dependencies["workflow_repository"].get_submission.assert_not_called()


@pytest.mark.anyio
async def test_unknown_membership_role_is_denied(
    client,
    api_dependencies,
):
    api_dependencies["membership_repository"].get_membership.return_value = {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "role": "ADMIN",
        "status": "ACTIVE",
    }

    response = await client.post(
        BASE_URL,
        json={
            "target_status": "SUBMITTED",
            "expected_version": 1,
        },
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_submission_owner_mismatch_is_denied(
    client,
    api_dependencies,
):
    api_dependencies["workflow_repository"].get_submission.return_value["owner_id"] = (
        "another-user"
    )

    response = await client.post(
        BASE_URL,
        json={
            "target_status": "SUBMITTED",
            "expected_version": 1,
        },
    )

    assert response.status_code == 404

    api_dependencies["workflow_repository"].transition_submission.assert_not_called()


@pytest.mark.anyio
async def test_invalid_target_status_returns_422(client, api_dependencies):
    response = await client.post(
        BASE_URL,
        json={
            "target_status": "ARCHIVED",
            "expected_version": 1,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.anyio
async def test_missing_expected_version_returns_422(client, api_dependencies):
    response = await client.post(
        BASE_URL,
        json={
            "target_status": "SUBMITTED",
        },
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_invalid_expected_version_returns_422(client, api_dependencies):
    response = await client.post(
        BASE_URL,
        json={
            "target_status": "SUBMITTED",
            "expected_version": 0,
        },
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_extra_request_fields_are_rejected(client, api_dependencies):
    response = await client.post(
        BASE_URL,
        json={
            "target_status": "SUBMITTED",
            "expected_version": 1,
            "owner_id": "attacker-controlled-user",
        },
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_blank_rejection_reason_is_rejected(client, api_dependencies):
    response = await client.post(
        BASE_URL,
        json={
            "target_status": "REJECTED",
            "expected_version": 1,
            "reason": "   ",
        },
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_reviewer_rejection_requires_reason(
    client,
    api_dependencies,
):
    api_dependencies["membership_repository"].get_membership.return_value = {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "role": "REVIEWER",
        "status": "ACTIVE",
    }

    api_dependencies["workflow_repository"].get_submission.return_value["status"] = (
        "IN_REVIEW"
    )

    response = await client.post(
        BASE_URL,
        json={
            "target_status": "REJECTED",
            "expected_version": 1,
        },
    )

    assert response.status_code == 422

    api_dependencies["workflow_repository"].transition_submission.assert_not_called()


@pytest.mark.anyio
async def test_invalid_transition_returns_conflict(
    client,
    api_dependencies,
):
    response = await client.post(
        BASE_URL,
        json={
            "target_status": "APPROVED",
            "expected_version": 1,
        },
    )

    assert response.status_code == 409


@pytest.mark.anyio
async def test_stale_version_returns_conflict(
    client,
    api_dependencies,
):
    api_dependencies["workflow_repository"].get_submission.return_value["version"] = 3

    response = await client.post(
        BASE_URL,
        json={
            "target_status": "SUBMITTED",
            "expected_version": 1,
        },
    )

    assert response.status_code == 409

    api_dependencies["workflow_repository"].transition_submission.assert_not_called()


@pytest.mark.anyio
async def test_repository_conflict_returns_409(
    client,
    api_dependencies,
):
    from app.repositories.submission import SubmissionStateConflictError

    api_dependencies[
        "workflow_repository"
    ].transition_submission.side_effect = SubmissionStateConflictError

    response = await client.post(
        BASE_URL,
        json={
            "target_status": "SUBMITTED",
            "expected_version": 1,
        },
    )

    assert response.status_code == 409
