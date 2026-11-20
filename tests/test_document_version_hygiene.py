import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "lambda"
    / "document_version_hygiene"
    / "handler.py"
)

SPEC = importlib.util.spec_from_file_location(
    "document_version_hygiene_handler",
    MODULE_PATH,
)
hygiene = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hygiene)


NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)

TIMESTAMP = "2026-11-15T12:00:00Z"
EXPIRES_AT = "2026-11-14T12:00:00Z"
UPLOAD_URL_EXPIRES_AT = "2026-11-14T11:55:00Z"
UPLOAD_HYGIENE_AFTER = "2026-11-15T11:55:00Z"

TENANT_ID = "tenant-001"
SUBMISSION_ID = "submission-001"
DOCUMENT_ID = "document-001"

OBJECT_KEY = f"tenants/{TENANT_ID}/submissions/{SUBMISSION_ID}/{DOCUMENT_ID}"

ACCEPTED_VERSION_ID = "accepted-version-123"
EXTRA_VERSION_ID = "extra-version-456"
DELETE_MARKER_ID = "delete-marker-789"

CONFIG = {
    "table_name": "cloudsec-test-submissions",
    "index_name": "PendingDocumentExpiryIndex",
    "bucket_name": "cloudsec-test-application-bucket",
    "shard_count": 4,
    "max_items": 50,
}


def make_candidate(
    *,
    document_id=DOCUMENT_ID,
    tenant_id=TENANT_ID,
    submission_id=SUBMISSION_ID,
    object_key=None,
    status="UPLOADED",
    version_id=ACCEPTED_VERSION_ID,
    expires_at=EXPIRES_AT,
    upload_url_expires_at=UPLOAD_URL_EXPIRES_AT,
    upload_hygiene_after=UPLOAD_HYGIENE_AFTER,
    shard_count=4,
):
    try:
        shard = hygiene.get_document_hygiene_shard(
            document_id,
            shard_count,
        )
    except ValueError:
        shard = hygiene.get_document_hygiene_shard(
            DOCUMENT_ID,
            shard_count,
        )

    if object_key is None:
        object_key = f"tenants/{tenant_id}/submissions/{submission_id}/{document_id}"

    return {
        "PK": {"S": f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"},
        "SK": {"S": f"DOCUMENT#{document_id}"},
        "tenant_id": {"S": tenant_id},
        "submission_id": {"S": submission_id},
        "document_id": {"S": document_id},
        "entity_type": {"S": "DOCUMENT"},
        "object_key": {"S": object_key},
        "status": {"S": status},
        "version_id": {"S": version_id},
        "expires_at": {"S": expires_at},
        "upload_url_expires_at": {"S": upload_url_expires_at},
        "upload_hygiene_after": {"S": upload_hygiene_after},
        "GSI3PK": {"S": f"UPLOADED#{shard:02d}"},
        "GSI3SK": {"S": f"{upload_hygiene_after}#{document_id}"},
    }


def validated_candidate(**kwargs):
    item = make_candidate(**kwargs)
    document_id = item["document_id"]["S"]
    shard = hygiene.get_document_hygiene_shard(
        document_id,
        CONFIG["shard_count"],
    )

    return hygiene.validate_candidate(
        item,
        shard,
        CONFIG["shard_count"],
        NOW,
    )


def client_error(code, operation="TestOperation"):
    return ClientError(
        {
            "Error": {
                "Code": code,
                "Message": "Test error",
            }
        },
        operation,
    )


def s3_page(
    versions=None,
    delete_markers=None,
    truncated=False,
    next_key_marker=None,
    next_version_marker=None,
):
    return {
        "Versions": versions or [],
        "DeleteMarkers": delete_markers or [],
        "IsTruncated": truncated,
        "NextKeyMarker": next_key_marker,
        "NextVersionIdMarker": next_version_marker,
    }


def version(key=OBJECT_KEY, version_id=ACCEPTED_VERSION_ID):
    return {
        "Key": key,
        "VersionId": version_id,
    }


def delete_marker(key=OBJECT_KEY, version_id=DELETE_MARKER_ID):
    return {
        "Key": key,
        "VersionId": version_id,
    }


# Configuration


def test_get_config_accepts_valid_environment(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", CONFIG["table_name"])
    monkeypatch.setenv("HYGIENE_INDEX", CONFIG["index_name"])
    monkeypatch.setenv("BUCKET_NAME", CONFIG["bucket_name"])
    monkeypatch.setenv("SHARD_COUNT", "4")
    monkeypatch.setenv("MAX_ITEMS", "50")

    assert hygiene.get_config() == CONFIG


@pytest.mark.parametrize(
    "variable,value",
    [
        ("TABLE_NAME", ""),
        ("TABLE_NAME", "invalid table name"),
        ("HYGIENE_INDEX", "WrongIndex"),
        ("BUCKET_NAME", ""),
        ("BUCKET_NAME", "INVALID_BUCKET"),
        ("SHARD_COUNT", "0"),
        ("SHARD_COUNT", "17"),
        ("SHARD_COUNT", "invalid"),
        ("MAX_ITEMS", "0"),
        ("MAX_ITEMS", "101"),
        ("MAX_ITEMS", "invalid"),
    ],
)
def test_get_config_rejects_invalid_environment(
    monkeypatch,
    variable,
    value,
):
    monkeypatch.setenv("TABLE_NAME", CONFIG["table_name"])
    monkeypatch.setenv("HYGIENE_INDEX", CONFIG["index_name"])
    monkeypatch.setenv("BUCKET_NAME", CONFIG["bucket_name"])
    monkeypatch.setenv("SHARD_COUNT", "4")
    monkeypatch.setenv("MAX_ITEMS", "50")
    monkeypatch.setenv(variable, value)

    with pytest.raises(hygiene.ConfigurationError):
        hygiene.get_config()


# Timestamp and sharding


def test_format_utc_timestamp():
    assert hygiene.format_utc_timestamp(NOW) == TIMESTAMP


def test_parse_utc_timestamp():
    assert hygiene.parse_utc_timestamp(TIMESTAMP) == NOW


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "2026-11-15",
        "2026-11-15T12:00:00",
        "2026-11-15T12:00:00+00:00",
        "2026-02-30T12:00:00Z",
    ],
)
def test_parse_utc_timestamp_rejects_invalid_values(value):
    with pytest.raises(hygiene.CandidateValidationError):
        hygiene.parse_utc_timestamp(value)


def test_document_hygiene_shard_is_deterministic():
    first = hygiene.get_document_hygiene_shard(
        DOCUMENT_ID,
        4,
    )
    second = hygiene.get_document_hygiene_shard(
        DOCUMENT_ID,
        4,
    )

    assert first == second
    assert 0 <= first < 4


# Candidate validation


def test_validate_candidate_accepts_valid_document():
    candidate = validated_candidate()

    assert candidate["document_id"] == DOCUMENT_ID
    assert candidate["object_key"] == OBJECT_KEY
    assert candidate["version_id"] == ACCEPTED_VERSION_ID
    assert candidate["status"] == "UPLOADED"


def test_invalid_entity_type_never_reaches_s3():
    dynamodb = MagicMock()
    s3 = MagicMock()

    item = make_candidate()
    item["entity_type"] = {"S": "SUBMISSION"}

    dynamodb.query.return_value = {"Items": [item]}

    shard = hygiene.get_document_hygiene_shard(
        DOCUMENT_ID,
        CONFIG["shard_count"],
    )

    result = hygiene.query_hygiene_shard(
        dynamodb,
        s3,
        CONFIG,
        shard,
        1,
        NOW,
    )

    assert result["invalid"] == 1
    assert result["cleaned"] == 0
    s3.list_object_versions.assert_not_called()
    s3.delete_objects.assert_not_called()
    dynamodb.update_item.assert_not_called()


@pytest.mark.parametrize(
    "attribute",
    [
        "PK",
        "SK",
        "tenant_id",
        "submission_id",
        "document_id",
        "entity_type",
        "object_key",
        "status",
        "version_id",
        "expires_at",
        "upload_url_expires_at",
        "upload_hygiene_after",
        "GSI3PK",
        "GSI3SK",
    ],
)
def test_validate_candidate_rejects_missing_attributes(attribute):
    item = make_candidate()
    del item[attribute]

    shard = hygiene.get_document_hygiene_shard(
        DOCUMENT_ID,
        CONFIG["shard_count"],
    )

    with pytest.raises(hygiene.CandidateValidationError):
        hygiene.validate_candidate(
            item,
            shard,
            CONFIG["shard_count"],
            NOW,
        )


@pytest.mark.parametrize(
    "document_id",
    [
        "../document",
        "document/child",
        "document key",
        "",
        ".",
        "..",
        "-invalid",
    ],
)
def test_validate_candidate_rejects_invalid_document_id(document_id):
    item = make_candidate(document_id=document_id)

    with pytest.raises(hygiene.CandidateValidationError):
        hygiene.validate_candidate(
            item,
            0,
            CONFIG["shard_count"],
            NOW,
        )


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("entity_type", "SUBMISSION"),
        ("status", "PENDING_UPLOAD"),
        ("version_id", "null"),
        ("object_key", "tenants/other/object"),
        ("GSI3PK", "PENDING_UPLOAD#00"),
        ("GSI3SK", "wrong-sort-key"),
        ("upload_hygiene_after", "2026-11-15T12:30:00Z"),
        ("upload_url_expires_at", "2026-11-14T13:00:00Z"),
    ],
)
def test_validate_candidate_rejects_invalid_values(attribute, value):
    item = make_candidate()
    item[attribute]["S"] = value

    shard = hygiene.get_document_hygiene_shard(
        DOCUMENT_ID,
        CONFIG["shard_count"],
    )

    with pytest.raises(hygiene.CandidateValidationError):
        hygiene.validate_candidate(
            item,
            shard,
            CONFIG["shard_count"],
            NOW,
        )


def test_validate_candidate_rejects_wrong_shard():
    item = make_candidate()
    actual_shard = hygiene.get_document_hygiene_shard(
        DOCUMENT_ID,
        CONFIG["shard_count"],
    )

    wrong_shard = (actual_shard + 1) % CONFIG["shard_count"]

    with pytest.raises(hygiene.CandidateValidationError):
        hygiene.validate_candidate(
            item,
            wrong_shard,
            CONFIG["shard_count"],
            NOW,
        )


# S3 version collection


def test_collect_exact_key_versions_filters_prefix_lookalikes():
    s3 = MagicMock()

    s3.list_object_versions.return_value = s3_page(
        versions=[
            version(),
            version(
                key=OBJECT_KEY + "-another-object",
                version_id="unrelated-version",
            ),
        ],
        delete_markers=[delete_marker()],
    )

    result = hygiene.collect_exact_key_versions(
        s3,
        CONFIG["bucket_name"],
        OBJECT_KEY,
    )

    assert result == {
        "versions": [
            {
                "Key": OBJECT_KEY,
                "VersionId": ACCEPTED_VERSION_ID,
            },
        ],
        "delete_markers": [
            {
                "Key": OBJECT_KEY,
                "VersionId": DELETE_MARKER_ID,
            },
        ],
    }


def test_collect_exact_key_versions_stops_above_limit():
    s3 = MagicMock()
    pages = []

    for page_number in range(6):
        pages.append(
            s3_page(
                versions=[
                    version(version_id=f"version-{page_number}-{index}")
                    for index in range(1000)
                ],
                truncated=page_number < 5,
                next_key_marker=OBJECT_KEY if page_number < 5 else None,
                next_version_marker=(
                    f"marker-{page_number}"
                    if page_number < 5
                    else None
                ),
            )
        )

    s3.list_object_versions.side_effect = pages

    with pytest.raises(
        hygiene.S3HygieneError,
        match="exceeds configured limit",
    ):
        hygiene.collect_exact_key_versions(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )

    assert s3.list_object_versions.call_count == 6


def test_collect_exact_key_versions_paginates():
    s3 = MagicMock()

    s3.list_object_versions.side_effect = [
        s3_page(
            versions=[version(version_id=ACCEPTED_VERSION_ID)],
            truncated=True,
            next_key_marker=OBJECT_KEY,
            next_version_marker=ACCEPTED_VERSION_ID,
        ),
        s3_page(
            versions=[version(version_id=EXTRA_VERSION_ID)],
        ),
    ]

    result = hygiene.collect_exact_key_versions(
        s3,
        CONFIG["bucket_name"],
        OBJECT_KEY,
    )

    assert len(result["versions"]) == 2
    assert result["delete_markers"] == []
    assert s3.list_object_versions.call_count == 2

    second_call = s3.list_object_versions.call_args_list[1]

    assert second_call.kwargs["KeyMarker"] == OBJECT_KEY
    assert second_call.kwargs["VersionIdMarker"] == ACCEPTED_VERSION_ID


def test_collect_exact_key_versions_rejects_stalled_pagination():
    s3 = MagicMock()

    s3.list_object_versions.side_effect = [
        s3_page(
            truncated=True,
            next_key_marker=OBJECT_KEY,
        ),
        s3_page(
            truncated=True,
            next_key_marker=OBJECT_KEY,
        ),
    ]

    with pytest.raises(hygiene.S3HygieneError):
        hygiene.collect_exact_key_versions(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )


def test_pagination_stops_when_lambda_time_is_exhausted():
    s3 = MagicMock()
    context = MagicMock()
    context.get_remaining_time_in_millis.side_effect = [6000, 5000]

    s3.list_object_versions.return_value = s3_page(
        versions=[version()],
        truncated=True,
        next_key_marker=OBJECT_KEY,
        next_version_marker=ACCEPTED_VERSION_ID,
    )

    with pytest.raises(
        hygiene.S3HygieneError,
        match="Insufficient Lambda execution time",
    ):
        hygiene.collect_exact_key_versions(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
            context=context,
        )

    assert s3.list_object_versions.call_count == 1


# Accepted-version protection


def test_cleanup_candidate_preserves_accepted_version():
    dynamodb = MagicMock()
    s3 = MagicMock()

    s3.delete_objects.return_value = {
        "Deleted": [
            {
                "Key": OBJECT_KEY,
                "VersionId": EXTRA_VERSION_ID,
            },
            {
                "Key": OBJECT_KEY,
                "VersionId": DELETE_MARKER_ID,
            },
        ]
    }

    s3.list_object_versions.side_effect = [
        s3_page(
            versions=[
                version(version_id=ACCEPTED_VERSION_ID),
                version(version_id=EXTRA_VERSION_ID),
            ],
            delete_markers=[delete_marker()],
        ),
        s3_page(
            versions=[
                version(version_id=ACCEPTED_VERSION_ID),
            ],
        ),
    ]

    candidate = validated_candidate()

    result = hygiene.cleanup_candidate(
        dynamodb,
        s3,
        CONFIG,
        candidate,
    )

    assert result is True

    s3.delete_objects.assert_called_once()

    deleted = s3.delete_objects.call_args.kwargs["Delete"]["Objects"]

    assert {
        "Key": OBJECT_KEY,
        "VersionId": ACCEPTED_VERSION_ID,
    } not in deleted

    assert {
        "Key": OBJECT_KEY,
        "VersionId": EXTRA_VERSION_ID,
    } in deleted

    assert {
        "Key": OBJECT_KEY,
        "VersionId": DELETE_MARKER_ID,
    } in deleted

    dynamodb.update_item.assert_called_once()


def test_missing_accepted_version_fails_closed():
    dynamodb = MagicMock()
    s3 = MagicMock()

    s3.list_object_versions.return_value = s3_page(
        versions=[
            version(version_id=EXTRA_VERSION_ID),
        ],
    )

    candidate = validated_candidate()

    with pytest.raises(
        hygiene.S3HygieneError,
        match="Accepted S3 version is missing",
    ):
        hygiene.cleanup_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
        )

    s3.delete_objects.assert_not_called()
    dynamodb.update_item.assert_not_called()


def test_cleanup_candidate_does_not_delete_accepted_only():
    dynamodb = MagicMock()
    s3 = MagicMock()

    s3.list_object_versions.side_effect = [
        s3_page(
            versions=[
                version(version_id=ACCEPTED_VERSION_ID),
            ],
        ),
        s3_page(
            versions=[
                version(version_id=ACCEPTED_VERSION_ID),
            ],
        ),
    ]

    candidate = validated_candidate()

    assert hygiene.cleanup_candidate(
        dynamodb,
        s3,
        CONFIG,
        candidate,
    )

    s3.delete_objects.assert_not_called()
    dynamodb.update_item.assert_called_once()


def test_delete_response_errors_fail_hygiene():
    s3 = MagicMock()

    s3.delete_objects.return_value = {
        "Errors": [
            {
                "Key": OBJECT_KEY,
                "VersionId": EXTRA_VERSION_ID,
                "Code": "AccessDenied",
            }
        ]
    }

    with pytest.raises(hygiene.S3HygieneError):
        hygiene.delete_unaccepted_versions(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
            [
                {
                    "Key": OBJECT_KEY,
                    "VersionId": ACCEPTED_VERSION_ID,
                },
                {
                    "Key": OBJECT_KEY,
                    "VersionId": EXTRA_VERSION_ID,
                },
            ],
            ACCEPTED_VERSION_ID,
        )


def test_deletion_stops_when_lambda_time_is_exhausted():
    s3 = MagicMock()
    s3.delete_objects.return_value = {"Errors": []}
    context = MagicMock()
    context.get_remaining_time_in_millis.side_effect = [6000, 5000]

    versions = [
        {"Key": OBJECT_KEY, "VersionId": f"version-{index}"}
        for index in range(2002)
    ]
    versions[0]["VersionId"] = ACCEPTED_VERSION_ID

    with pytest.raises(
        hygiene.S3HygieneError,
        match="Insufficient Lambda execution time",
    ):
        hygiene.delete_unaccepted_versions(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
            versions,
            ACCEPTED_VERSION_ID,
            context=context,
        )

    assert s3.delete_objects.call_count == 1


def test_delete_versions_uses_batches_of_at_most_1000():
    s3 = MagicMock()
    s3.delete_objects.return_value = {"Errors": []}

    versions = [
        {
            "Key": OBJECT_KEY,
            "VersionId": f"version-{index}",
        }
        for index in range(2002)
    ]

    versions[0]["VersionId"] = ACCEPTED_VERSION_ID

    hygiene.delete_unaccepted_versions(
        s3,
        CONFIG["bucket_name"],
        OBJECT_KEY,
        versions,
        ACCEPTED_VERSION_ID,
    )

    assert s3.delete_objects.call_count == 3

    batch_sizes = [
        len(call.kwargs["Delete"]["Objects"])
        for call in s3.delete_objects.call_args_list
    ]

    assert batch_sizes == [1000, 1000, 1]


def test_verification_stops_when_lambda_time_is_exhausted():
    s3 = MagicMock()
    context = MagicMock()
    context.get_remaining_time_in_millis.return_value = 5000

    with pytest.raises(
        hygiene.S3HygieneError,
        match="Insufficient Lambda execution time",
    ):
        hygiene.verify_accepted_version_only(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
            ACCEPTED_VERSION_ID,
            context=context,
        )

    s3.list_object_versions.assert_not_called()


def test_verification_rejects_unexpected_remaining_version():
    s3 = MagicMock()

    s3.list_object_versions.return_value = s3_page(
        versions=[
            version(version_id=ACCEPTED_VERSION_ID),
            version(version_id=EXTRA_VERSION_ID),
        ],
    )

    with pytest.raises(hygiene.S3HygieneError):
        hygiene.verify_accepted_version_only(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
            ACCEPTED_VERSION_ID,
        )


def test_verification_rejects_remaining_delete_marker():
    s3 = MagicMock()

    s3.list_object_versions.return_value = s3_page(
        versions=[
            version(version_id=ACCEPTED_VERSION_ID),
        ],
        delete_markers=[
            delete_marker(),
        ],
    )

    with pytest.raises(
        hygiene.S3HygieneError,
        match="delete markers remain",
    ):
        hygiene.verify_accepted_version_only(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
            ACCEPTED_VERSION_ID,
        )


def test_delete_marker_cannot_satisfy_accepted_version_check():
    dynamodb = MagicMock()
    s3 = MagicMock()

    s3.list_object_versions.return_value = s3_page(
        delete_markers=[
            delete_marker(
                version_id=ACCEPTED_VERSION_ID,
            ),
        ],
    )

    candidate = validated_candidate()

    with pytest.raises(
        hygiene.S3HygieneError,
        match="Accepted S3 version is missing",
    ):
        hygiene.cleanup_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
        )

    s3.delete_objects.assert_not_called()
    dynamodb.update_item.assert_not_called()


# DynamoDB conditional update


def test_remove_hygiene_index_removes_only_gsi_keys():
    dynamodb = MagicMock()
    candidate = validated_candidate()

    assert hygiene.remove_hygiene_index(
        dynamodb,
        CONFIG["table_name"],
        candidate,
    )

    arguments = dynamodb.update_item.call_args.kwargs

    assert arguments["UpdateExpression"] == "REMOVE GSI3PK, GSI3SK"

    assert (
        arguments["ExpressionAttributeValues"][":version_id"]["S"]
        == ACCEPTED_VERSION_ID
    )


def test_remove_hygiene_index_handles_conditional_failure():
    dynamodb = MagicMock()

    dynamodb.update_item.side_effect = client_error(
        "ConditionalCheckFailedException",
    )

    candidate = validated_candidate()

    assert not hygiene.remove_hygiene_index(
        dynamodb,
        CONFIG["table_name"],
        candidate,
    )


def test_remove_hygiene_index_propagates_unexpected_errors():
    dynamodb = MagicMock()

    dynamodb.update_item.side_effect = client_error(
        "AccessDeniedException",
    )

    candidate = validated_candidate()

    with pytest.raises(ClientError):
        hygiene.remove_hygiene_index(
            dynamodb,
            CONFIG["table_name"],
            candidate,
        )


# Failure safety


def test_s3_listing_failure_does_not_update_dynamodb():
    dynamodb = MagicMock()
    s3 = MagicMock()

    s3.list_object_versions.side_effect = client_error(
        "AccessDenied",
    )

    candidate = validated_candidate()

    with pytest.raises(ClientError):
        hygiene.cleanup_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
        )

    dynamodb.update_item.assert_not_called()


def test_verification_failure_does_not_update_dynamodb():
    dynamodb = MagicMock()
    s3 = MagicMock()

    s3.list_object_versions.side_effect = [
        s3_page(
            versions=[
                version(version_id=ACCEPTED_VERSION_ID),
                version(version_id=EXTRA_VERSION_ID),
            ],
        ),
        s3_page(
            versions=[
                version(version_id=ACCEPTED_VERSION_ID),
                version(version_id=EXTRA_VERSION_ID),
            ],
        ),
    ]

    candidate = validated_candidate()

    with pytest.raises(hygiene.S3HygieneError):
        hygiene.cleanup_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
        )

    dynamodb.update_item.assert_not_called()


def test_query_hygiene_shard_follows_last_evaluated_key():
    dynamodb = MagicMock()
    s3 = MagicMock()

    last_evaluated_key = {
        "PK": {"S": "TENANT#tenant-001"},
        "SK": {"S": "DOCUMENT#document-001"},
        "GSI3PK": {"S": "UPLOADED#00"},
        "GSI3SK": {"S": f"{UPLOAD_HYGIENE_AFTER}#document-001"},
    }

    dynamodb.query.side_effect = [
        {
            "Items": [{"PK": {"S": "invalid"}}],
            "LastEvaluatedKey": last_evaluated_key,
        },
        {
            "Items": [],
        },
    ]

    result = hygiene.query_hygiene_shard(
        dynamodb,
        s3,
        CONFIG,
        shard=0,
        max_items=10,
        now=NOW,
    )

    assert result["processed"] == 1
    assert result["invalid"] == 1
    assert dynamodb.query.call_count == 2

    second_query = dynamodb.query.call_args_list[1].kwargs
    assert second_query["ExclusiveStartKey"] == last_evaluated_key

    s3.list_object_versions.assert_not_called()
