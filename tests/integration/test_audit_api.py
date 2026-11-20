import pytest

from app.services.audit import encode_audit_cursor

BASE_URL = "/api/v1/tenants/tenant-a/submissions/submission-123/audit-events"


def valid_audit_event():
    return {
        "event_id": "event-123",
        "event_type": "SUBMISSION_STATUS_CHANGED",
        "tenant_id": "tenant-a",
        "submission_id": "submission-123",
        "entity_type": "AUDIT_EVENT",
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": "EVENT#2026-11-12T10:00:00Z#event-123",
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": "EVENT#2026-11-12T10:00:00Z#event-123",
        "actor_id": "user-a",
        "actor_role": "SUBMITTER",
        "previous_status": "DRAFT",
        "new_status": "SUBMITTED",
        "previous_version": 1,
        "new_version": 2,
        "timestamp": "2026-11-12T10:00:00Z",
        "request_id": "request-123",
    }


@pytest.mark.anyio
async def test_authorized_user_can_retrieve_audit_history(
    client,
    api_dependencies,
):
    api_dependencies["audit_repository"].list_submission_events.return_value = {
        "Items": [valid_audit_event()],
    }

    response = await client.get(BASE_URL)

    assert response.status_code == 200

    body = response.json()

    assert len(body["items"]) == 1
    assert body["items"][0]["event_id"] == "event-123"
    assert body["items"][0]["tenant_id"] == "tenant-a"
    assert body["items"][0]["submission_id"] == "submission-123"
    assert body["next_cursor"] is None


@pytest.mark.anyio
async def test_empty_audit_history_returns_empty_list(
    client,
    api_dependencies,
):
    response = await client.get(BASE_URL)

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "next_cursor": None,
    }


@pytest.mark.anyio
async def test_audit_access_requires_active_membership(
    client,
    api_dependencies,
):
    api_dependencies["membership_repository"].get_membership.return_value["status"] = (
        "INACTIVE"
    )

    response = await client.get(BASE_URL)

    assert response.status_code == 403

    api_dependencies["submission_repository"].get_submission.assert_not_called()

    api_dependencies["audit_repository"].list_submission_events.assert_not_called()


@pytest.mark.anyio
async def test_missing_membership_prevents_audit_access(
    client,
    api_dependencies,
):
    api_dependencies["membership_repository"].get_membership.return_value = None

    response = await client.get(BASE_URL)

    assert response.status_code == 403

    api_dependencies["audit_repository"].list_submission_events.assert_not_called()


@pytest.mark.anyio
async def test_submitter_cannot_access_another_users_audit_history(
    client,
    api_dependencies,
):
    api_dependencies["submission_repository"].get_submission.return_value[
        "owner_id"
    ] = "another-user"

    response = await client.get(BASE_URL)

    assert response.status_code == 404

    api_dependencies["audit_repository"].list_submission_events.assert_not_called()


@pytest.mark.anyio
async def test_reviewer_can_access_tenant_audit_history(
    client,
    api_dependencies,
):
    api_dependencies["membership_repository"].get_membership.return_value = {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "role": "REVIEWER",
        "status": "ACTIVE",
    }

    api_dependencies["audit_repository"].list_submission_events.return_value = {
        "Items": [valid_audit_event()],
    }

    response = await client.get(BASE_URL)

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


@pytest.mark.anyio
async def test_audit_history_is_tenant_scoped(
    client,
    api_dependencies,
):
    response = await client.get(
        "/api/v1/tenants/tenant-b/submissions/submission-123/audit-events"
    )

    assert response.status_code == 403

    api_dependencies["audit_repository"].list_submission_events.assert_not_called()


@pytest.mark.anyio
async def test_audit_limit_is_passed_to_repository(
    client,
    api_dependencies,
):
    response = await client.get(
        BASE_URL,
        params={"limit": 5},
    )

    assert response.status_code == 200

    call_args = api_dependencies["audit_repository"].list_submission_events.call_args

    assert call_args.args[2] == 5


@pytest.mark.anyio
async def test_audit_limit_below_minimum_is_rejected(client, api_dependencies):
    response = await client.get(
        BASE_URL,
        params={"limit": 0},
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_audit_limit_above_maximum_is_rejected(client, api_dependencies):
    response = await client.get(
        BASE_URL,
        params={"limit": 101},
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_malformed_audit_cursor_is_rejected(client, api_dependencies):
    response = await client.get(
        BASE_URL,
        params={"cursor": "invalid-cursor"},
    )

    assert response.status_code == 400


@pytest.mark.anyio
async def test_audit_cursor_cannot_cross_submission_boundary(
    client,
    api_dependencies,
):
    cursor = encode_audit_cursor(
        {
            "PK": "TENANT#tenant-a#SUBMISSION#another-submission",
            "SK": "EVENT#2026-11-12T10:00:00Z#event-123",
        }
    )

    response = await client.get(
        BASE_URL,
        params={"cursor": cursor},
    )

    assert response.status_code == 400

    api_dependencies["audit_repository"].list_submission_events.assert_not_called()


@pytest.mark.anyio
async def test_audit_pagination_returns_next_cursor(
    client,
    api_dependencies,
):
    last_evaluated_key = {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": "EVENT#2026-11-12T10:00:00Z#event-123",
    }

    api_dependencies["audit_repository"].list_submission_events.return_value = {
        "Items": [valid_audit_event()],
        "LastEvaluatedKey": last_evaluated_key,
    }

    response = await client.get(BASE_URL)

    assert response.status_code == 200

    next_cursor = response.json()["next_cursor"]

    assert next_cursor == encode_audit_cursor(last_evaluated_key)


@pytest.mark.anyio
async def test_invalid_audit_event_is_rejected(
    client,
    api_dependencies,
):
    invalid_event = valid_audit_event()
    invalid_event["tenant_id"] = "tenant-b"

    api_dependencies["audit_repository"].list_submission_events.return_value = {
        "Items": [invalid_event],
    }

    response = await client.get(BASE_URL)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "http_error"
    assert response.json()["error"]["message"] == "Internal server error"


TENANT_AUDIT_URL = "/api/v1/tenants/tenant-a/audit-events"


def valid_tenant_submission_event():
    timestamp = "2026-11-12T12:00:00Z"
    event_id = "event-submission-123"
    sort_key = f"EVENT#{timestamp}#{event_id}"

    return {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": sort_key,
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": sort_key,
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


def valid_tenant_membership_event():
    timestamp = "2026-11-12T13:00:00Z"
    event_id = "event-membership-123"
    sort_key = f"EVENT#{timestamp}#{event_id}"

    return {
        "PK": "TENANT#tenant-a#MEMBERSHIP#user-b",
        "SK": sort_key,
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": sort_key,
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


def valid_tenant_deactivation_event():
    timestamp = "2026-11-12T14:00:00Z"
    event_id = "event-deactivation-123"
    sort_key = f"EVENT#{timestamp}#{event_id}"

    return {
        "PK": "TENANT#tenant-a#MEMBERSHIP#user-c",
        "SK": sort_key,
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": sort_key,
        "entity_type": "AUDIT_EVENT",
        "event_id": event_id,
        "event_type": "MEMBERSHIP_DEACTIVATED",
        "tenant_id": "tenant-a",
        "target_user_id": "user-c",
        "actor_id": "admin-a",
        "actor_role": "TENANT_ADMIN",
        "previous_status": "ACTIVE",
        "new_status": "INACTIVE",
        "timestamp": timestamp,
        "request_id": "request-789",
    }


def make_tenant_admin(api_dependencies):
    api_dependencies["membership_repository"].get_membership.return_value = {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "role": "TENANT_ADMIN",
        "status": "ACTIVE",
    }


@pytest.mark.anyio
async def test_tenant_admin_can_retrieve_mixed_audit_events(
    client,
    api_dependencies,
):
    make_tenant_admin(api_dependencies)

    api_dependencies["audit_repository"].list_tenant_events.return_value = {
        "Items": [
            valid_tenant_deactivation_event(),
            valid_tenant_membership_event(),
            valid_tenant_submission_event(),
        ],
    }

    response = await client.get(TENANT_AUDIT_URL)

    assert response.status_code == 200

    body = response.json()

    assert len(body["items"]) == 3
    assert {item["event_type"] for item in body["items"]} == {
        "SUBMISSION_STATUS_CHANGED",
        "MEMBERSHIP_ROLE_CHANGED",
        "MEMBERSHIP_DEACTIVATED",
    }
    assert body["next_cursor"] is None

    api_dependencies["audit_repository"].list_tenant_events.assert_called_once_with(
        "tenant-a",
        20,
        None,
    )


@pytest.mark.anyio
async def test_non_admin_cannot_access_tenant_audit_events(
    client,
    api_dependencies,
):
    api_dependencies["membership_repository"].get_membership.return_value = {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "role": "REVIEWER",
        "status": "ACTIVE",
    }

    response = await client.get(TENANT_AUDIT_URL)

    assert response.status_code == 403

    api_dependencies["audit_repository"].list_tenant_events.assert_not_called()


@pytest.mark.anyio
async def test_inactive_tenant_admin_cannot_access_tenant_audit_events(
    client,
    api_dependencies,
):
    api_dependencies["membership_repository"].get_membership.return_value = {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "role": "TENANT_ADMIN",
        "status": "INACTIVE",
    }

    response = await client.get(TENANT_AUDIT_URL)

    assert response.status_code == 403

    api_dependencies["audit_repository"].list_tenant_events.assert_not_called()


@pytest.mark.anyio
async def test_tenant_admin_cannot_access_another_tenants_audit_events(
    client,
    api_dependencies,
):
    make_tenant_admin(api_dependencies)

    response = await client.get("/api/v1/tenants/tenant-b/audit-events")

    assert response.status_code == 403

    api_dependencies["audit_repository"].list_tenant_events.assert_not_called()


@pytest.mark.anyio
async def test_tenant_audit_limit_is_passed_to_repository(
    client,
    api_dependencies,
):
    make_tenant_admin(api_dependencies)

    api_dependencies["audit_repository"].list_tenant_events.return_value = {
        "Items": [],
    }

    response = await client.get(
        TENANT_AUDIT_URL,
        params={"limit": 5},
    )

    assert response.status_code == 200

    api_dependencies["audit_repository"].list_tenant_events.assert_called_once_with(
        "tenant-a",
        5,
        None,
    )


@pytest.mark.anyio
async def test_tenant_audit_limit_below_minimum_is_rejected(
    client,
    api_dependencies,
):
    make_tenant_admin(api_dependencies)

    response = await client.get(
        TENANT_AUDIT_URL,
        params={"limit": 0},
    )

    assert response.status_code == 422

    api_dependencies["audit_repository"].list_tenant_events.assert_not_called()


@pytest.mark.anyio
async def test_tenant_audit_limit_above_maximum_is_rejected(
    client,
    api_dependencies,
):
    make_tenant_admin(api_dependencies)

    response = await client.get(
        TENANT_AUDIT_URL,
        params={"limit": 101},
    )

    assert response.status_code == 422

    api_dependencies["audit_repository"].list_tenant_events.assert_not_called()


@pytest.mark.anyio
async def test_malformed_tenant_audit_cursor_is_rejected(
    client,
    api_dependencies,
):
    make_tenant_admin(api_dependencies)

    response = await client.get(
        TENANT_AUDIT_URL,
        params={"cursor": "invalid-cursor"},
    )

    assert response.status_code == 400

    api_dependencies["audit_repository"].list_tenant_events.assert_not_called()


@pytest.mark.anyio
async def test_tenant_audit_cursor_cannot_cross_tenant_boundary(
    client,
    api_dependencies,
):
    make_tenant_admin(api_dependencies)

    cursor = encode_audit_cursor(
        {
            "PK": "TENANT#tenant-b#MEMBERSHIP#user-b",
            "SK": "EVENT#2026-11-12T13:00:00Z#event-123",
            "GSI1PK": "TENANT#tenant-b",
            "GSI1SK": "EVENT#2026-11-12T13:00:00Z#event-123",
        }
    )

    response = await client.get(
        TENANT_AUDIT_URL,
        params={"cursor": cursor},
    )

    assert response.status_code == 400

    api_dependencies["audit_repository"].list_tenant_events.assert_not_called()


@pytest.mark.anyio
async def test_tenant_audit_pagination_returns_next_cursor(
    client,
    api_dependencies,
):
    make_tenant_admin(api_dependencies)

    last_evaluated_key = {
        "PK": "TENANT#tenant-a#MEMBERSHIP#user-b",
        "SK": "EVENT#2026-11-12T13:00:00Z#event-membership-123",
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": "EVENT#2026-11-12T13:00:00Z#event-membership-123",
    }

    api_dependencies["audit_repository"].list_tenant_events.return_value = {
        "Items": [valid_tenant_membership_event()],
        "LastEvaluatedKey": last_evaluated_key,
    }

    response = await client.get(TENANT_AUDIT_URL)

    assert response.status_code == 200
    assert response.json()["next_cursor"] == encode_audit_cursor(last_evaluated_key)


@pytest.mark.anyio
async def test_invalid_tenant_audit_event_is_not_returned(
    client,
    api_dependencies,
):
    make_tenant_admin(api_dependencies)

    invalid_event = valid_tenant_membership_event()
    invalid_event["tenant_id"] = "tenant-b"

    api_dependencies["audit_repository"].list_tenant_events.return_value = {
        "Items": [invalid_event],
    }

    response = await client.get(TENANT_AUDIT_URL)

    assert response.status_code == 500
    assert response.json()["error"]["message"] == "Internal server error"
