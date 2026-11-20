from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from app.repositories.document import (
    DocumentAlreadyExistsError,
    DocumentNotFoundError,
    DocumentStateConflictError,
    DynamoDBDocumentRepository,
)


@pytest.fixture
def repository(monkeypatch):
    table = MagicMock()
    table.name = "cloudsec-submissions-dev"

    dynamodb = SimpleNamespace(Table=MagicMock(return_value=table))

    monkeypatch.setattr(
        "app.repositories.document.boto3.resource",
        MagicMock(return_value=dynamodb),
    )

    settings = SimpleNamespace(
        aws_region="ap-south-1",
        submissions_table_name="cloudsec-submissions-dev",
        dynamodb_endpoint_url=None,
    )

    return DynamoDBDocumentRepository(settings), table


@pytest.fixture
def sample_document():
    return {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": "DOCUMENT#document-456",
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": "EVENT#2026-11-17T12:00:00Z#event-123",
        "entity_type": "DOCUMENT",
        "tenant_id": "tenant-a",
        "submission_id": "submission-123",
        "document_id": "document-456",
        "owner_id": "user-123",
        "original_filename": "invoice.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1024,
        "object_key": ("tenants/tenant-a/submissions/submission-123/document-456"),
        "status": "PENDING_UPLOAD",
        "expires_at": "2026-11-14T12:30:00Z",
        "GSI3PK": "PENDING_UPLOAD#02",
        "GSI3SK": "2026-11-14T12:30:00Z#document-456",
        "upload_url_expires_at": "2026-11-14T12:05:00Z",
        "upload_hygiene_after": "2026-11-15T12:05:00Z",
    }


def make_client_error(
    code,
    operation,
    cancellation_reasons=None,
):
    response = {
        "Error": {
            "Code": code,
            "Message": "Test error",
        }
    }

    if cancellation_reasons is not None:
        response["CancellationReasons"] = cancellation_reasons

    return ClientError(response, operation)


def test_create_document_uses_atomic_transaction(
    repository,
    sample_document,
):
    repo, table = repository

    repo.create_document(sample_document)

    client = table.meta.client
    client.transact_write_items.assert_called_once()

    transactions = client.transact_write_items.call_args.kwargs["TransactItems"]

    assert len(transactions) == 2

    update = transactions[0]["Update"]

    assert update["TableName"] == table.name
    assert update["Key"] == {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
    }
    assert update["UpdateExpression"] == (
        "ADD pending_document_count :one, "
        "pending_document_bytes :size, "
        "total_document_count :one, "
        "total_document_bytes :size"
    )
    assert "#status = :draft" in update["ConditionExpression"]
    assert "owner_id = :owner" in update["ConditionExpression"]
    assert "total_document_count < :max_documents" in update["ConditionExpression"]
    assert "total_document_bytes <= :max_bytes_before" in update["ConditionExpression"]
    assert update["ExpressionAttributeValues"] == {
        ":one": 1,
        ":size": 1024,
        ":draft": "DRAFT",
        ":owner": "user-123",
        ":max_documents": 10,
        ":max_bytes_before": 50 * 1024 * 1024 - 1024,
    }

    put = transactions[1]["Put"]

    assert put["TableName"] == table.name
    assert put["Item"] == sample_document
    assert "attribute_not_exists(PK)" in put["ConditionExpression"]

    table.put_item.assert_not_called()


def test_create_document_duplicate(
    repository,
    sample_document,
):
    repo, table = repository

    table.meta.client.transact_write_items.side_effect = make_client_error(
        "TransactionCanceledException",
        "TransactWriteItems",
        [
            {"Code": "None"},
            {"Code": "ConditionalCheckFailed"},
        ],
    )

    with pytest.raises(DocumentAlreadyExistsError):
        repo.create_document(sample_document)


def test_create_document_rejects_submission_state_conflict(
    repository,
    sample_document,
):
    repo, table = repository

    table.meta.client.transact_write_items.side_effect = make_client_error(
        "TransactionCanceledException",
        "TransactWriteItems",
        [
            {"Code": "ConditionalCheckFailed"},
            {"Code": "None"},
        ],
    )

    with pytest.raises(DocumentStateConflictError):
        repo.create_document(sample_document)


def test_create_document_propagates_unclassified_error(
    repository,
    sample_document,
):
    repo, table = repository

    table.meta.client.transact_write_items.side_effect = make_client_error(
        "TransactionCanceledException",
        "TransactWriteItems",
        [
            {"Code": "None"},
            {"Code": "None"},
        ],
    )

    with pytest.raises(ClientError):
        repo.create_document(sample_document)


def test_get_document_uses_consistent_read(
    repository,
    sample_document,
):
    repo, table = repository

    table.get_item.return_value = {
        "Item": sample_document,
    }

    result = repo.get_document(
        "tenant-a",
        "submission-123",
        "document-456",
    )

    assert result == sample_document

    table.get_item.assert_called_once_with(
        Key={
            "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
            "SK": "DOCUMENT#document-456",
        },
        ConsistentRead=True,
    )


def test_get_document_not_found(repository):
    repo, table = repository
    table.get_item.return_value = {}

    result = repo.get_document(
        "tenant-a",
        "submission-123",
        "missing-document",
    )

    assert result is None


def test_mark_document_uploaded_uses_atomic_transaction(
    repository,
):
    repo, table = repository

    repo.mark_document_uploaded(
        tenant_id="tenant-a",
        submission_id="submission-123",
        document_id="document-456",
        uploaded_at="2026-11-12T12:00:00Z",
        version_id="s3-version-123",
        owner_id="user-123",
        pending_gsi3_pk="PENDING_UPLOAD#02",
        pending_gsi3_sk="2026-11-14T12:30:00Z#document-456",
        uploaded_gsi3_pk="UPLOADED#02",
        uploaded_gsi3_sk="2026-11-15T12:05:00Z#document-456",
        upload_url_expires_at="2026-11-14T12:05:00Z",
        upload_hygiene_after="2026-11-15T12:05:00Z",
        size_bytes=1024,
    )

    client = table.meta.client
    client.transact_write_items.assert_called_once()

    transactions = client.transact_write_items.call_args.kwargs["TransactItems"]

    assert len(transactions) == 2

    submission_update = transactions[0]["Update"]

    assert submission_update["Key"] == {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
    }

    assert "pending_document_count - :one" in (submission_update["UpdateExpression"])

    assert "uploaded_document_count + :one" in (submission_update["UpdateExpression"])

    assert (
        "pending_document_count > :zero" in (submission_update["ConditionExpression"])
    )
    assert (
        "pending_document_bytes >= :size" in (submission_update["ConditionExpression"])
    )
    assert "pending_document_bytes - :size" in (submission_update["UpdateExpression"])

    document_update = transactions[1]["Update"]

    assert document_update["Key"] == {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": "DOCUMENT#document-456",
    }

    assert document_update["ExpressionAttributeValues"] == {
        ":uploaded": "UPLOADED",
        ":pending": "PENDING_UPLOAD",
        ":uploaded_at": "2026-11-12T12:00:00Z",
        ":version_id": "s3-version-123",
        ":owner": "user-123",
        ":tenant": "tenant-a",
        ":submission": "submission-123",
        ":document": "document-456",
        ":size": 1024,
        ":pending_gsi3_pk": "PENDING_UPLOAD#02",
        ":pending_gsi3_sk": "2026-11-14T12:30:00Z#document-456",
        ":uploaded_gsi3_pk": "UPLOADED#02",
        ":uploaded_gsi3_sk": "2026-11-15T12:05:00Z#document-456",
        ":upload_url_expires_at": "2026-11-14T12:05:00Z",
        ":upload_hygiene_after": "2026-11-15T12:05:00Z",
    }

    assert "owner_id = :owner" in (document_update["ConditionExpression"])

    assert ":pending" in document_update["ConditionExpression"]
    assert "attribute_exists(expires_at)" in (document_update["ConditionExpression"])
    assert "expires_at > :uploaded_at" in (document_update["ConditionExpression"])
    assert "GSI3PK = :uploaded_gsi3_pk" in (document_update["UpdateExpression"])
    assert "GSI3SK = :uploaded_gsi3_sk" in (document_update["UpdateExpression"])
    assert "GSI3PK = :pending_gsi3_pk" in (document_update["ConditionExpression"])
    assert "GSI3SK = :pending_gsi3_sk" in (document_update["ConditionExpression"])
    assert (
        "upload_url_expires_at = :upload_url_expires_at"
        in (document_update["ConditionExpression"])
    )
    assert (
        "upload_hygiene_after = :upload_hygiene_after"
        in (document_update["ConditionExpression"])
    )
    assert document_update["ExpressionAttributeValues"][":pending"] == (
        "PENDING_UPLOAD"
    )


@pytest.mark.parametrize(
    "version_id",
    [None, "", "null"],
)
def test_mark_document_uploaded_rejects_invalid_version_id(
    repository,
    version_id,
):
    repo, table = repository

    with pytest.raises(ValueError):
        repo.mark_document_uploaded(
            tenant_id="tenant-a",
            submission_id="submission-123",
            document_id="document-456",
            uploaded_at="2026-11-12T12:00:00Z",
            version_id=version_id,
            owner_id="user-123",
            pending_gsi3_pk="PENDING_UPLOAD#02",
            pending_gsi3_sk="2026-11-14T12:30:00Z#document-456",
            uploaded_gsi3_pk="UPLOADED#02",
            uploaded_gsi3_sk="2026-11-15T12:05:00Z#document-456",
            upload_url_expires_at="2026-11-14T12:05:00Z",
            upload_hygiene_after="2026-11-15T12:05:00Z",
            size_bytes=1024,
        )

    table.meta.client.transact_write_items.assert_not_called()


def test_mark_document_uploaded_rejects_submission_conflict(
    repository,
):
    repo, table = repository

    table.meta.client.transact_write_items.side_effect = make_client_error(
        "TransactionCanceledException",
        "TransactWriteItems",
        [
            {"Code": "ConditionalCheckFailed"},
            {"Code": "None"},
        ],
    )

    with pytest.raises(DocumentStateConflictError):
        repo.mark_document_uploaded(
            tenant_id="tenant-a",
            submission_id="submission-123",
            document_id="document-456",
            uploaded_at="2026-11-12T12:00:00Z",
            version_id="s3-version-123",
            owner_id="user-123",
            pending_gsi3_pk="PENDING_UPLOAD#02",
            pending_gsi3_sk="2026-11-14T12:30:00Z#document-456",
            uploaded_gsi3_pk="UPLOADED#02",
            uploaded_gsi3_sk="2026-11-15T12:05:00Z#document-456",
            upload_url_expires_at="2026-11-14T12:05:00Z",
            upload_hygiene_after="2026-11-15T12:05:00Z",
            size_bytes=1024,
        )

    table.get_item.assert_not_called()


def test_mark_document_uploaded_missing_document(repository):
    repo, table = repository

    table.meta.client.transact_write_items.side_effect = make_client_error(
        "TransactionCanceledException",
        "TransactWriteItems",
        [
            {"Code": "None"},
            {"Code": "ConditionalCheckFailed"},
        ],
    )

    table.get_item.return_value = {}

    with pytest.raises(DocumentNotFoundError):
        repo.mark_document_uploaded(
            tenant_id="tenant-a",
            submission_id="submission-123",
            document_id="missing-document",
            uploaded_at="2026-11-12T12:00:00Z",
            version_id="s3-version-123",
            owner_id="user-123",
            pending_gsi3_pk="PENDING_UPLOAD#01",
            pending_gsi3_sk="2026-11-14T12:30:00Z#missing-document",
            uploaded_gsi3_pk="UPLOADED#01",
            uploaded_gsi3_sk="2026-11-15T12:05:00Z#missing-document",
            upload_url_expires_at="2026-11-14T12:05:00Z",
            upload_hygiene_after="2026-11-15T12:05:00Z",
            size_bytes=1024,
        )


def test_mark_document_uploaded_rejects_invalid_state(
    repository,
    sample_document,
):
    repo, table = repository

    table.meta.client.transact_write_items.side_effect = make_client_error(
        "TransactionCanceledException",
        "TransactWriteItems",
        [
            {"Code": "None"},
            {"Code": "ConditionalCheckFailed"},
        ],
    )

    table.get_item.return_value = {
        "Item": sample_document,
    }

    with pytest.raises(DocumentStateConflictError):
        repo.mark_document_uploaded(
            tenant_id="tenant-a",
            submission_id="submission-123",
            document_id="document-456",
            uploaded_at="2026-11-12T12:00:00Z",
            version_id="s3-version-123",
            owner_id="user-123",
            size_bytes=1024,
            pending_gsi3_pk="PENDING_UPLOAD#02",
            pending_gsi3_sk="2026-11-14T12:30:00Z#document-456",
            uploaded_gsi3_pk="UPLOADED#02",
            uploaded_gsi3_sk="2026-11-15T12:05:00Z#document-456",
            upload_url_expires_at="2026-11-14T12:05:00Z",
            upload_hygiene_after="2026-11-15T12:05:00Z",
        )


def test_create_document_rejects_invalid_size(repository, sample_document):
    repo, table = repository
    sample_document["size_bytes"] = 0

    with pytest.raises(ValueError):
        repo.create_document(sample_document)

    table.meta.client.transact_write_items.assert_not_called()


def test_create_document_maps_quota_failure(repository, sample_document):
    repo, table = repository
    table.meta.client.transact_write_items.side_effect = make_client_error(
        "TransactionCanceledException",
        "TransactWriteItems",
        [
            {"Code": "ConditionalCheckFailed"},
            {"Code": "None"},
        ],
    )
    table.get_item.return_value = {
        "Item": {
            "status": "DRAFT",
            "owner_id": "user-123",
            "total_document_count": 10,
            "total_document_bytes": 1024,
        }
    }

    from app.repositories.document import DocumentQuotaExceededError

    with pytest.raises(DocumentQuotaExceededError):
        repo.create_document(sample_document)

    table.get_item.assert_called_once_with(
        Key={"PK": "TENANT#tenant-a", "SK": "SUBMISSION#submission-123"},
        ConsistentRead=True,
    )


def test_list_documents_queries_submission_partition(repository):
    repo, table = repository

    result = {
        "Items": [],
    }
    table.query.return_value = result

    response = repo.list_documents(
        tenant_id="tenant-a",
        submission_id="submission-123",
        limit=20,
    )

    assert response == result

    query = table.query.call_args.kwargs

    assert query["Limit"] == 20
    assert query["ScanIndexForward"] is False
    assert query["ConsistentRead"] is True
    assert "KeyConditionExpression" in query
    assert "ExclusiveStartKey" not in query


def test_list_documents_uses_pagination_cursor(repository):
    repo, table = repository

    cursor = {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": "DOCUMENT#document-456",
    }

    table.query.return_value = {
        "Items": [],
    }

    repo.list_documents(
        tenant_id="tenant-a",
        submission_id="submission-123",
        limit=10,
        cursor=cursor,
    )

    query = table.query.call_args.kwargs

    assert query["ExclusiveStartKey"] == cursor
    assert query["Limit"] == 10
    assert query["ConsistentRead"] is True
