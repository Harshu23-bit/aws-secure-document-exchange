from datetime import UTC, datetime, timedelta

import pytest

from app.services.documents import get_document_expiry_shard
from app.services.storage import StorageObjectValidationError

BASE_URL = "/api/v1/tenants/tenant-a/submissions/submission-123/documents"

DOCUMENT_ID = "document-456"

DOCUMENT_OBJECT_KEY = "tenants/tenant-a/submissions/submission-123/document-456"


def upload_payload():
    return {
        "filename": "invoice.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1024,
    }


def pending_document():
    now = datetime.now(UTC).replace(microsecond=0)

    expires_at = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    upload_url_expires_at = (now + timedelta(seconds=300)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    upload_hygiene_after = (
        now + timedelta(seconds=300) + timedelta(hours=24)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    shard = get_document_expiry_shard(DOCUMENT_ID)

    return {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": "DOCUMENT#document-456",
        "entity_type": "DOCUMENT",
        "tenant_id": "tenant-a",
        "submission_id": "submission-123",
        "document_id": DOCUMENT_ID,
        "owner_id": "user-a",
        "original_filename": "invoice.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1024,
        "object_key": DOCUMENT_OBJECT_KEY,
        "status": "PENDING_UPLOAD",
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires_at,
        "GSI3PK": f"PENDING_UPLOAD#{shard:02d}",
        "GSI3SK": f"{expires_at}#{DOCUMENT_ID}",
        "upload_url_expires_at": upload_url_expires_at,
        "upload_hygiene_after": upload_hygiene_after,
    }


def uploaded_document():
    document = pending_document()
    document["status"] = "UPLOADED"
    document["version_id"] = "version-123"
    return document


def set_membership_role(api_dependencies, role):
    api_dependencies["membership_repository"].get_membership.return_value = {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "role": role,
        "status": "ACTIVE",
    }


# ============================================================
# UPLOAD REQUEST
# ============================================================


@pytest.mark.anyio
async def test_submitter_can_request_document_upload(
    client,
    api_dependencies,
):
    response = await client.post(
        BASE_URL,
        json=upload_payload(),
    )

    assert response.status_code == 201

    body = response.json()

    assert body["document_id"]
    assert body["upload_url"] == "https://example.com/upload"
    assert body["expires_in"] == 300
    assert body["upload_fields"]["Content-Type"] == "application/pdf"

    repository = api_dependencies["document_repository"]
    storage = api_dependencies["storage"]

    repository.create_document.assert_called_once()

    document = repository.create_document.call_args.args[0]

    assert document["tenant_id"] == "tenant-a"
    assert document["submission_id"] == "submission-123"
    assert document["owner_id"] == "user-a"
    assert document["status"] == "PENDING_UPLOAD"
    assert document["content_type"] == "application/pdf"
    assert document["size_bytes"] == 1024

    assert document["object_key"] == (
        f"tenants/tenant-a/submissions/submission-123/{body['document_id']}"
    )

    storage.generate_upload_request.assert_called_once_with(
        document["object_key"],
        "application/pdf",
        1024,
    )


@pytest.mark.anyio
async def test_reviewer_cannot_request_document_upload(
    client,
    api_dependencies,
):
    set_membership_role(api_dependencies, "REVIEWER")

    response = await client.post(
        BASE_URL,
        json=upload_payload(),
    )

    assert response.status_code == 403

    api_dependencies["document_repository"].create_document.assert_not_called()

    api_dependencies["storage"].generate_upload_request.assert_not_called()


@pytest.mark.anyio
async def test_document_upload_is_tenant_scoped(
    client,
    api_dependencies,
):
    response = await client.post(
        "/api/v1/tenants/tenant-b/submissions/submission-123/documents",
        json=upload_payload(),
    )

    assert response.status_code == 403

    api_dependencies["submission_repository"].get_submission.assert_not_called()

    api_dependencies["document_repository"].create_document.assert_not_called()


@pytest.mark.anyio
async def test_document_upload_rejects_non_draft_submission(
    client,
    api_dependencies,
):
    api_dependencies["submission_repository"].get_submission.return_value["status"] = (
        "SUBMITTED"
    )

    response = await client.post(
        BASE_URL,
        json=upload_payload(),
    )

    assert response.status_code == 409

    api_dependencies["document_repository"].create_document.assert_not_called()


@pytest.mark.anyio
async def test_document_upload_rejects_oversized_file(
    client,
    api_dependencies,
):
    payload = upload_payload()
    payload["size_bytes"] = 11 * 1024 * 1024

    response = await client.post(
        BASE_URL,
        json=payload,
    )

    assert response.status_code == 422

    api_dependencies["document_repository"].create_document.assert_not_called()


@pytest.mark.anyio
async def test_document_upload_rejects_string_size(
    client,
    api_dependencies,
):
    payload = upload_payload()
    payload["size_bytes"] = "1024"

    response = await client.post(
        BASE_URL,
        json=payload,
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_document_upload_rejects_extra_request_fields(
    client,
    api_dependencies,
):
    payload = upload_payload()
    payload["owner_id"] = "attacker-controlled-user"

    response = await client.post(
        BASE_URL,
        json=payload,
    )

    assert response.status_code == 422

    api_dependencies["document_repository"].create_document.assert_not_called()


# ============================================================
# UPLOAD COMPLETION
# ============================================================


@pytest.mark.anyio
async def test_submitter_can_complete_verified_upload(
    client,
    api_dependencies,
):
    api_dependencies[
        "document_repository"
    ].get_document.return_value = pending_document()

    response = await client.post(
        f"{BASE_URL}/{DOCUMENT_ID}/complete",
    )

    assert response.status_code == 200

    body = response.json()

    assert body["document_id"] == DOCUMENT_ID
    assert body["submission_id"] == "submission-123"
    assert body["status"] == "UPLOADED"
    assert body["filename"] == "invoice.pdf"
    assert body["content_type"] == "application/pdf"
    assert body["size_bytes"] == 1024

    storage = api_dependencies["storage"]
    repository = api_dependencies["document_repository"]

    storage.get_object_metadata.assert_called_once_with(DOCUMENT_OBJECT_KEY)

    storage.validate_object_metadata.assert_called_once()

    storage.validate_object_content.assert_called_once_with(
        DOCUMENT_OBJECT_KEY,
        "version-123",
        "application/pdf",
    )

    repository.mark_document_uploaded.assert_called_once()

    call_args = repository.mark_document_uploaded.call_args.args

    assert call_args[0] == "tenant-a"
    assert call_args[1] == "submission-123"
    assert call_args[2] == DOCUMENT_ID
    assert call_args[4] == "version-123"
    assert call_args[5] == "user-a"
    assert call_args[6] == 1024


@pytest.mark.anyio
async def test_upload_completion_rejects_invalid_document_signature(
    client,
    api_dependencies,
):
    api_dependencies[
        "document_repository"
    ].get_document.return_value = pending_document()

    storage = api_dependencies["storage"]

    storage.validate_object_content.side_effect = StorageObjectValidationError(
        "Invalid PDF signature"
    )

    response = await client.post(
        f"{BASE_URL}/{DOCUMENT_ID}/complete",
    )

    assert response.status_code == 400

    body = response.json()

    assert body["error"]["code"] == "http_error"
    assert body["error"]["message"] == ("Uploaded document failed content validation")
    assert body["request_id"]

    storage.validate_object_content.assert_called_once_with(
        DOCUMENT_OBJECT_KEY,
        "version-123",
        "application/pdf",
    )

    api_dependencies["document_repository"].mark_document_uploaded.assert_not_called()


@pytest.mark.anyio
async def test_reviewer_cannot_complete_upload(
    client,
    api_dependencies,
):
    set_membership_role(api_dependencies, "REVIEWER")

    response = await client.post(
        f"{BASE_URL}/{DOCUMENT_ID}/complete",
    )

    assert response.status_code == 403

    api_dependencies["document_repository"].get_document.assert_not_called()


@pytest.mark.anyio
async def test_upload_completion_rejects_missing_document(
    client,
    api_dependencies,
):
    api_dependencies["document_repository"].get_document.return_value = None

    response = await client.post(
        f"{BASE_URL}/{DOCUMENT_ID}/complete",
    )

    assert response.status_code == 404

    api_dependencies["storage"].get_object_metadata.assert_not_called()


@pytest.mark.anyio
async def test_upload_completion_rejects_another_users_document(
    client,
    api_dependencies,
):
    document = pending_document()
    document["owner_id"] = "another-user"

    api_dependencies["document_repository"].get_document.return_value = document

    response = await client.post(
        f"{BASE_URL}/{DOCUMENT_ID}/complete",
    )

    assert response.status_code == 404

    api_dependencies["storage"].get_object_metadata.assert_not_called()


@pytest.mark.anyio
async def test_upload_completion_rejects_invalid_object_version(
    client,
    api_dependencies,
):
    api_dependencies[
        "document_repository"
    ].get_document.return_value = pending_document()

    api_dependencies["storage"].get_object_metadata.return_value["VersionId"] = "null"

    response = await client.post(
        f"{BASE_URL}/{DOCUMENT_ID}/complete",
    )

    assert response.status_code == 503

    api_dependencies["document_repository"].mark_document_uploaded.assert_not_called()


# ============================================================
# DOCUMENT DOWNLOAD
# ============================================================


@pytest.mark.anyio
async def test_submitter_can_download_own_uploaded_document(
    client,
    api_dependencies,
):
    api_dependencies[
        "document_repository"
    ].get_document.return_value = uploaded_document()

    response = await client.get(
        f"{BASE_URL}/{DOCUMENT_ID}/download",
    )

    assert response.status_code == 200

    body = response.json()

    assert body["document_id"] == DOCUMENT_ID
    assert body["download_url"] == "https://example.com/download"
    assert body["expires_in"] == 300

    api_dependencies["storage"].generate_download_url.assert_called_once_with(
        DOCUMENT_OBJECT_KEY,
        "application/pdf",
        "invoice.pdf",
        "version-123",
    )


@pytest.mark.anyio
async def test_reviewer_can_download_document_after_submission(
    client,
    api_dependencies,
):
    set_membership_role(api_dependencies, "REVIEWER")

    api_dependencies["submission_repository"].get_submission.return_value["status"] = (
        "SUBMITTED"
    )

    api_dependencies[
        "document_repository"
    ].get_document.return_value = uploaded_document()

    response = await client.get(
        f"{BASE_URL}/{DOCUMENT_ID}/download",
    )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_reviewer_cannot_download_document_from_draft(
    client,
    api_dependencies,
):
    set_membership_role(api_dependencies, "REVIEWER")

    response = await client.get(
        f"{BASE_URL}/{DOCUMENT_ID}/download",
    )

    assert response.status_code == 404

    api_dependencies["document_repository"].get_document.assert_not_called()

    api_dependencies["storage"].generate_download_url.assert_not_called()


@pytest.mark.anyio
async def test_download_rejects_pending_document(
    client,
    api_dependencies,
):
    api_dependencies[
        "document_repository"
    ].get_document.return_value = pending_document()

    response = await client.get(
        f"{BASE_URL}/{DOCUMENT_ID}/download",
    )

    assert response.status_code == 409

    api_dependencies["storage"].generate_download_url.assert_not_called()


@pytest.mark.anyio
async def test_download_rejects_missing_document(
    client,
    api_dependencies,
):
    api_dependencies["document_repository"].get_document.return_value = None

    response = await client.get(
        f"{BASE_URL}/{DOCUMENT_ID}/download",
    )

    assert response.status_code == 404

    api_dependencies["storage"].generate_download_url.assert_not_called()


@pytest.mark.anyio
async def test_download_rejects_invalid_version_id(
    client,
    api_dependencies,
):
    document = uploaded_document()
    document["version_id"] = "null"

    api_dependencies["document_repository"].get_document.return_value = document

    response = await client.get(
        f"{BASE_URL}/{DOCUMENT_ID}/download",
    )

    assert response.status_code == 409

    api_dependencies["storage"].generate_download_url.assert_not_called()


@pytest.mark.anyio
async def test_download_is_tenant_scoped(
    client,
    api_dependencies,
):
    response = await client.get(
        "/api/v1/tenants/tenant-b/"
        f"submissions/submission-123/documents/{DOCUMENT_ID}/download",
    )

    assert response.status_code == 403

    api_dependencies["document_repository"].get_document.assert_not_called()

    api_dependencies["storage"].generate_download_url.assert_not_called()


# ============================================================
# DOCUMENT LISTING
# ============================================================


@pytest.mark.anyio
async def test_submitter_can_list_own_submission_documents(
    client,
    api_dependencies,
):
    api_dependencies["document_repository"].list_documents.return_value = {
        "Items": [pending_document()],
    }

    response = await client.get(BASE_URL)

    assert response.status_code == 200

    body = response.json()

    assert body["next_cursor"] is None
    assert len(body["items"]) == 1

    item = body["items"][0]

    assert item == {
        "document_id": DOCUMENT_ID,
        "submission_id": "submission-123",
        "filename": "invoice.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1024,
        "status": "PENDING_UPLOAD",
        "created_at": pending_document()["created_at"],
    }

    api_dependencies["document_repository"].list_documents.assert_called_once()


@pytest.mark.anyio
async def test_document_listing_does_not_expose_internal_metadata(
    client,
    api_dependencies,
):
    api_dependencies["document_repository"].list_documents.return_value = {
        "Items": [uploaded_document()],
    }

    response = await client.get(BASE_URL)

    assert response.status_code == 200

    item = response.json()["items"][0]

    forbidden_fields = {
        "owner_id",
        "object_key",
        "version_id",
        "expires_at",
        "upload_url_expires_at",
        "upload_hygiene_after",
        "GSI3PK",
        "GSI3SK",
        "PK",
        "SK",
        "entity_type",
    }

    assert forbidden_fields.isdisjoint(item.keys())


@pytest.mark.anyio
async def test_reviewer_can_list_documents_after_submission(
    client,
    api_dependencies,
):
    set_membership_role(api_dependencies, "REVIEWER")

    api_dependencies["submission_repository"].get_submission.return_value["status"] = (
        "SUBMITTED"
    )

    api_dependencies["document_repository"].list_documents.return_value = {
        "Items": [pending_document()],
    }

    response = await client.get(BASE_URL)

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1

    api_dependencies["document_repository"].list_documents.assert_called_once()


@pytest.mark.anyio
async def test_reviewer_cannot_list_documents_from_draft(
    client,
    api_dependencies,
):
    set_membership_role(api_dependencies, "REVIEWER")

    response = await client.get(BASE_URL)

    assert response.status_code == 404

    api_dependencies["document_repository"].list_documents.assert_not_called()


@pytest.mark.anyio
async def test_document_listing_is_tenant_scoped(
    client,
    api_dependencies,
):
    response = await client.get(
        "/api/v1/tenants/tenant-b/submissions/submission-123/documents",
    )

    assert response.status_code == 403

    api_dependencies["document_repository"].list_documents.assert_not_called()


@pytest.mark.anyio
async def test_document_listing_rejects_limit_above_maximum(
    client,
    api_dependencies,
):
    response = await client.get(
        f"{BASE_URL}?limit=101",
    )

    assert response.status_code == 422

    api_dependencies["document_repository"].list_documents.assert_not_called()


@pytest.mark.anyio
async def test_document_listing_rejects_invalid_cursor(
    client,
    api_dependencies,
):
    response = await client.get(
        f"{BASE_URL}?cursor=not-valid!",
    )

    assert response.status_code == 400

    api_dependencies["document_repository"].list_documents.assert_not_called()


@pytest.mark.anyio
async def test_document_listing_returns_pagination_cursor(
    client,
    api_dependencies,
):
    api_dependencies["document_repository"].list_documents.return_value = {
        "Items": [pending_document()],
        "LastEvaluatedKey": {
            "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
            "SK": "DOCUMENT#document-456",
        },
    }

    response = await client.get(
        f"{BASE_URL}?limit=1",
    )

    assert response.status_code == 200

    body = response.json()

    assert len(body["items"]) == 1
    assert isinstance(body["next_cursor"], str)
    assert body["next_cursor"]
