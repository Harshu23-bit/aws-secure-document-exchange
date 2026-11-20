import hashlib
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "lambda"
    / "document_finalization"
    / "handler.py"
)

SPEC = importlib.util.spec_from_file_location(
    "document_finalization_handler",
    MODULE_PATH,
)
finalization = importlib.util.module_from_spec(SPEC)

if SPEC.loader is not None:
    SPEC.loader.exec_module(finalization)


NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)
TIMESTAMP = "2026-11-15T12:00:00Z"

TENANT_ID = "tenant-001"
SUBMISSION_ID = "submission-001"
DOCUMENT_ID = "document-001"

EXPIRES_AT = "2026-11-13T12:00:00Z"
CLEANUP_AFTER = "2026-11-14T12:00:00Z"
CLEANUP_COMPLETED_AT = "2026-11-14T12:00:00Z"
FINALIZE_AFTER = "2026-11-15T12:00:00Z"

SHARD_COUNT = 4

OBJECT_KEY = f"tenants/{TENANT_ID}/submissions/{SUBMISSION_ID}/{DOCUMENT_ID}"

CONFIG = {
    "table_name": "cloudsec-test-submissions",
    "index_name": "PendingDocumentCleanupIndex",
    "bucket_name": "cloudsec-test-application-bucket",
    "shard_count": SHARD_COUNT,
    "max_items": 50,
}


def make_candidate(
    *,
    document_id=DOCUMENT_ID,
    tenant_id=TENANT_ID,
    submission_id=SUBMISSION_ID,
    object_key=None,
    status="CLEANUP_COMPLETE",
    expires_at=EXPIRES_AT,
    cleanup_after=CLEANUP_AFTER,
    cleanup_completed_at=CLEANUP_COMPLETED_AT,
    finalize_after=FINALIZE_AFTER,
    shard_count=SHARD_COUNT,
):
    try:
        shard = finalization.get_document_cleanup_shard(
            document_id,
            shard_count,
        )
    except ValueError:
        shard = 0

    if object_key is None:
        object_key = f"tenants/{tenant_id}/submissions/{submission_id}/{document_id}"

    return {
        "PK": {"S": f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"},
        "SK": {"S": f"DOCUMENT#{document_id}"},
        "tenant_id": {"S": tenant_id},
        "submission_id": {"S": submission_id},
        "document_id": {"S": document_id},
        "object_key": {"S": object_key},
        "status": {"S": status},
        "expires_at": {"S": expires_at},
        "cleanup_after": {"S": cleanup_after},
        "cleanup_completed_at": {"S": cleanup_completed_at},
        "finalize_after": {"S": finalize_after},
        "GSI4PK": {"S": f"CLEANUP_COMPLETE#{shard:02d}"},
        "GSI4SK": {"S": f"{finalize_after}#{document_id}"},
    }


def validated_candidate(**kwargs):
    item = make_candidate(**kwargs)
    document_id = item["document_id"]["S"]
    shard = finalization.get_document_cleanup_shard(
        document_id,
        SHARD_COUNT,
    )

    return finalization.validate_candidate(
        item,
        shard,
        SHARD_COUNT,
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


class LambdaContext:
    def __init__(self, remaining_ms=60000):
        self.remaining_ms = remaining_ms

    def get_remaining_time_in_millis(self):
        return self.remaining_ms


def test_format_utc_timestamp():
    assert finalization.format_utc_timestamp(NOW) == TIMESTAMP


def test_format_utc_timestamp_rejects_naive_datetime():
    with pytest.raises(ValueError):
        finalization.format_utc_timestamp(datetime(2026, 11, 15, 12, 0, 0))


def test_get_document_cleanup_shard_is_deterministic():
    first = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )
    second = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )

    assert first == second
    assert 0 <= first < SHARD_COUNT
    assert first == (
        hashlib.sha256(DOCUMENT_ID.encode("utf-8")).digest()[0] % SHARD_COUNT
    )


def test_validate_candidate_accepts_valid_completed_document():
    candidate = validated_candidate()

    assert candidate["document_id"] == DOCUMENT_ID
    assert candidate["tenant_id"] == TENANT_ID
    assert candidate["submission_id"] == SUBMISSION_ID
    assert candidate["object_key"] == OBJECT_KEY
    assert candidate["status"] == "CLEANUP_COMPLETE"
    assert candidate["finalize_after"] == FINALIZE_AFTER


@pytest.mark.parametrize(
    "attribute",
    [
        "PK",
        "SK",
        "tenant_id",
        "submission_id",
        "document_id",
        "object_key",
        "status",
        "expires_at",
        "cleanup_after",
        "cleanup_completed_at",
        "finalize_after",
        "GSI4PK",
        "GSI4SK",
    ],
)
def test_validate_candidate_rejects_missing_attributes(attribute):
    item = make_candidate()
    del item[attribute]

    shard = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )

    with pytest.raises(finalization.CandidateValidationError):
        finalization.validate_candidate(
            item,
            shard,
            SHARD_COUNT,
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
    shard = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )

    with pytest.raises(finalization.CandidateValidationError):
        finalization.validate_candidate(
            item,
            shard,
            SHARD_COUNT,
            NOW,
        )


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("tenant_id", "../tenant"),
        ("tenant_id", "tenant/child"),
        ("submission_id", "../submission"),
        ("submission_id", "submission/child"),
    ],
)
def test_validate_candidate_rejects_invalid_identity(attribute, value):
    arguments = {
        "tenant_id": TENANT_ID,
        "submission_id": SUBMISSION_ID,
    }
    arguments[attribute] = value

    item = make_candidate(**arguments)
    shard = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )

    with pytest.raises(finalization.CandidateValidationError):
        finalization.validate_candidate(
            item,
            shard,
            SHARD_COUNT,
            NOW,
        )


def test_validate_candidate_rejects_noncanonical_object_key():
    item = make_candidate(object_key="tenants/tenant-001/other-object")
    shard = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )

    with pytest.raises(finalization.CandidateValidationError):
        finalization.validate_candidate(
            item,
            shard,
            SHARD_COUNT,
            NOW,
        )


def test_validate_candidate_rejects_wrong_status():
    item = make_candidate(status="CLEANUP_PENDING")
    shard = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )

    with pytest.raises(finalization.CandidateValidationError):
        finalization.validate_candidate(
            item,
            shard,
            SHARD_COUNT,
            NOW,
        )


def test_validate_candidate_rejects_wrong_shard():
    item = make_candidate()
    actual_shard = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )
    wrong_shard = (actual_shard + 1) % SHARD_COUNT

    with pytest.raises(finalization.CandidateValidationError):
        finalization.validate_candidate(
            item,
            wrong_shard,
            SHARD_COUNT,
            NOW,
        )


def test_validate_candidate_rejects_wrong_gsi_partition():
    item = make_candidate()
    item["GSI4PK"] = {"S": "CLEANUP_PENDING#00"}

    shard = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )

    with pytest.raises(finalization.CandidateValidationError):
        finalization.validate_candidate(
            item,
            shard,
            SHARD_COUNT,
            NOW,
        )


def test_validate_candidate_rejects_wrong_gsi_sort_key():
    item = make_candidate()
    item["GSI4SK"] = {"S": "wrong-sort-key"}

    shard = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )

    with pytest.raises(finalization.CandidateValidationError):
        finalization.validate_candidate(
            item,
            shard,
            SHARD_COUNT,
            NOW,
        )


def test_validate_candidate_rejects_future_finalization_deadline():
    item = make_candidate(finalize_after="2026-11-16T12:00:00Z")
    shard = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )

    with pytest.raises(finalization.CandidateValidationError):
        finalization.validate_candidate(
            item,
            shard,
            SHARD_COUNT,
            NOW,
        )


def test_validate_candidate_rejects_inconsistent_finalization_deadline():
    item = make_candidate(
        cleanup_completed_at="2026-11-14T12:00:00Z",
        finalize_after="2026-11-15T11:00:00Z",
    )
    shard = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )

    with pytest.raises(finalization.CandidateValidationError):
        finalization.validate_candidate(
            item,
            shard,
            SHARD_COUNT,
            NOW,
        )


def test_validate_candidate_rejects_inconsistent_cleanup_deadline():
    item = make_candidate(cleanup_after="2026-11-14T11:00:00Z")
    shard = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )

    with pytest.raises(finalization.CandidateValidationError):
        finalization.validate_candidate(
            item,
            shard,
            SHARD_COUNT,
            NOW,
        )


def test_validate_candidate_rejects_naive_now():
    item = make_candidate()
    shard = finalization.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )

    with pytest.raises(ValueError):
        finalization.validate_candidate(
            item,
            shard,
            SHARD_COUNT,
            datetime(2026, 11, 15, 12, 0, 0),
        )


def test_get_exact_key_versions_filters_similar_prefixes():
    page = {
        "Versions": [
            {
                "Key": OBJECT_KEY,
                "VersionId": "version-1",
            },
            {
                "Key": OBJECT_KEY + "-other",
                "VersionId": "version-2",
            },
        ],
        "DeleteMarkers": [
            {
                "Key": OBJECT_KEY,
                "VersionId": "marker-1",
            },
            {
                "Key": OBJECT_KEY + "/child",
                "VersionId": "marker-2",
            },
        ],
    }

    assert finalization.get_exact_key_versions(
        page,
        OBJECT_KEY,
    ) == [
        {
            "Key": OBJECT_KEY,
            "VersionId": "version-1",
        },
        {
            "Key": OBJECT_KEY,
            "VersionId": "marker-1",
        },
    ]


@pytest.mark.parametrize(
    "page",
    [
        {
            "Versions": [
                {
                    "Key": OBJECT_KEY,
                }
            ]
        },
        {
            "DeleteMarkers": [
                {
                    "Key": OBJECT_KEY,
                }
            ]
        },
    ],
)
def test_get_exact_key_versions_rejects_missing_version_id(page):
    with pytest.raises(finalization.S3InspectionError):
        finalization.get_exact_key_versions(
            page,
            OBJECT_KEY,
        )


def test_list_object_versions_page_builds_first_page_request():
    s3 = MagicMock()
    s3.list_object_versions.return_value = {}

    finalization.list_object_versions_page(
        s3,
        CONFIG["bucket_name"],
        OBJECT_KEY,
    )

    s3.list_object_versions.assert_called_once_with(
        Bucket=CONFIG["bucket_name"],
        Prefix=OBJECT_KEY,
        MaxKeys=1000,
    )


def test_list_object_versions_page_builds_paginated_request():
    s3 = MagicMock()
    s3.list_object_versions.return_value = {}

    finalization.list_object_versions_page(
        s3,
        CONFIG["bucket_name"],
        OBJECT_KEY,
        "next-key",
        "next-version",
    )

    s3.list_object_versions.assert_called_once_with(
        Bucket=CONFIG["bucket_name"],
        Prefix=OBJECT_KEY,
        MaxKeys=1000,
        KeyMarker="next-key",
        VersionIdMarker="next-version",
    )


def test_verify_object_key_empty_returns_true_when_no_versions_exist():
    s3 = MagicMock()
    s3.list_object_versions.return_value = {
        "Versions": [],
        "DeleteMarkers": [],
        "IsTruncated": False,
    }

    assert (
        finalization.verify_object_key_empty(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )
        is True
    )


def test_verify_object_key_empty_returns_false_when_version_exists():
    s3 = MagicMock()
    s3.list_object_versions.return_value = {
        "Versions": [
            {
                "Key": OBJECT_KEY,
                "VersionId": "version-1",
            }
        ],
        "DeleteMarkers": [],
        "IsTruncated": False,
    }

    assert (
        finalization.verify_object_key_empty(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )
        is False
    )


def test_verify_object_key_empty_returns_false_when_delete_marker_exists():
    s3 = MagicMock()
    s3.list_object_versions.return_value = {
        "Versions": [],
        "DeleteMarkers": [
            {
                "Key": OBJECT_KEY,
                "VersionId": "marker-1",
            }
        ],
        "IsTruncated": False,
    }

    assert (
        finalization.verify_object_key_empty(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )
        is False
    )


def test_verify_object_key_empty_ignores_similar_prefixes():
    s3 = MagicMock()
    s3.list_object_versions.return_value = {
        "Versions": [
            {
                "Key": OBJECT_KEY + "-other",
                "VersionId": "other-version",
            }
        ],
        "DeleteMarkers": [],
        "IsTruncated": False,
    }

    assert (
        finalization.verify_object_key_empty(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )
        is True
    )


def test_verify_object_key_empty_handles_pagination():
    s3 = MagicMock()
    s3.list_object_versions.side_effect = [
        {
            "Versions": [],
            "DeleteMarkers": [],
            "IsTruncated": True,
            "NextKeyMarker": OBJECT_KEY,
            "NextVersionIdMarker": "version-1",
        },
        {
            "Versions": [],
            "DeleteMarkers": [],
            "IsTruncated": False,
        },
    ]

    assert (
        finalization.verify_object_key_empty(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )
        is True
    )

    assert s3.list_object_versions.call_count == 2


def test_verify_object_key_empty_rejects_truncated_response_without_marker():
    s3 = MagicMock()
    s3.list_object_versions.return_value = {
        "Versions": [],
        "DeleteMarkers": [],
        "IsTruncated": True,
    }

    with pytest.raises(finalization.S3InspectionError):
        finalization.verify_object_key_empty(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )


def test_finalize_candidate_requeues_when_version_exists_on_later_page():
    dynamodb = MagicMock()
    s3 = MagicMock()

    s3.list_object_versions.side_effect = [
        {
            "Versions": [],
            "DeleteMarkers": [],
            "IsTruncated": True,
            "NextKeyMarker": OBJECT_KEY,
            "NextVersionIdMarker": "version-1",
        },
        {
            "Versions": [
                {
                    "Key": OBJECT_KEY,
                    "VersionId": "version-2",
                }
            ],
            "DeleteMarkers": [],
            "IsTruncated": False,
        },
    ]

    result = finalization.finalize_candidate(
        dynamodb,
        s3,
        CONFIG,
        validated_candidate(),
        NOW,
    )

    assert result == "requeued"
    assert s3.list_object_versions.call_count == 2
    dynamodb.update_item.assert_called_once()
    dynamodb.delete_item.assert_not_called()


def test_verify_object_key_empty_rejects_invalid_next_version_marker():
    s3 = MagicMock()
    s3.list_object_versions.return_value = {
        "Versions": [],
        "DeleteMarkers": [],
        "IsTruncated": True,
        "NextKeyMarker": OBJECT_KEY,
        "NextVersionIdMarker": "",
    }

    with pytest.raises(finalization.S3InspectionError):
        finalization.verify_object_key_empty(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )


def test_verify_object_key_empty_rejects_non_advancing_markers():
    s3 = MagicMock()
    s3.list_object_versions.side_effect = [
        {
            "Versions": [],
            "DeleteMarkers": [],
            "IsTruncated": True,
            "NextKeyMarker": OBJECT_KEY,
            "NextVersionIdMarker": "version-1",
        },
        {
            "Versions": [],
            "DeleteMarkers": [],
            "IsTruncated": True,
            "NextKeyMarker": OBJECT_KEY,
            "NextVersionIdMarker": "version-1",
        },
    ]

    with pytest.raises(finalization.S3InspectionError):
        finalization.verify_object_key_empty(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )

    assert s3.list_object_versions.call_count == 2


@pytest.mark.parametrize(
    "is_truncated",
    [
        "true",
        1,
        None,
    ],
)
def test_verify_object_key_empty_rejects_invalid_pagination_indicator(
    is_truncated,
):
    s3 = MagicMock()
    s3.list_object_versions.return_value = {
        "Versions": [],
        "DeleteMarkers": [],
        "IsTruncated": is_truncated,
    }

    with pytest.raises(finalization.S3InspectionError):
        finalization.verify_object_key_empty(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )


def test_requeue_document_restores_pending_partition():
    dynamodb = MagicMock()
    candidate = validated_candidate()

    assert (
        finalization.requeue_document(
            dynamodb,
            CONFIG["table_name"],
            candidate,
            TIMESTAMP,
        )
        is True
    )

    arguments = dynamodb.update_item.call_args.kwargs
    values = arguments["ExpressionAttributeValues"]

    assert arguments["TableName"] == CONFIG["table_name"]
    assert arguments["Key"]["PK"] == {"S": candidate["pk"]}
    assert arguments["Key"]["SK"] == {"S": candidate["sk"]}
    assert values[":pending"] == {"S": "CLEANUP_PENDING"}
    assert values[":gsi4pk"] == {"S": f"CLEANUP_PENDING#{candidate['shard']:02d}"}
    assert values[":gsi4sk"] == {"S": f"{CLEANUP_AFTER}#{DOCUMENT_ID}"}
    assert "finalize_after" in arguments["ConditionExpression"]
    assert "object_key" in arguments["ConditionExpression"]


def test_requeue_document_returns_false_on_conditional_conflict():
    dynamodb = MagicMock()
    dynamodb.update_item.side_effect = client_error(
        "ConditionalCheckFailedException",
        "UpdateItem",
    )

    assert (
        finalization.requeue_document(
            dynamodb,
            CONFIG["table_name"],
            validated_candidate(),
            TIMESTAMP,
        )
        is False
    )


def test_requeue_document_propagates_unexpected_client_error():
    dynamodb = MagicMock()
    dynamodb.update_item.side_effect = client_error(
        "AccessDeniedException",
        "UpdateItem",
    )

    with pytest.raises(ClientError):
        finalization.requeue_document(
            dynamodb,
            CONFIG["table_name"],
            validated_candidate(),
            TIMESTAMP,
        )


def test_delete_finalized_document_is_conditional():
    dynamodb = MagicMock()
    candidate = validated_candidate()

    assert (
        finalization.delete_finalized_document(
            dynamodb,
            CONFIG["table_name"],
            candidate,
            TIMESTAMP,
        )
        is True
    )

    arguments = dynamodb.delete_item.call_args.kwargs

    assert arguments["TableName"] == CONFIG["table_name"]
    assert arguments["Key"]["PK"] == {"S": candidate["pk"]}
    assert arguments["Key"]["SK"] == {"S": candidate["sk"]}
    assert arguments["ExpressionAttributeValues"][":complete"] == {
        "S": "CLEANUP_COMPLETE"
    }
    assert "object_key" in arguments["ConditionExpression"]
    assert "finalize_after" in arguments["ConditionExpression"]


def test_delete_finalized_document_returns_false_on_conditional_conflict():
    dynamodb = MagicMock()
    dynamodb.delete_item.side_effect = client_error(
        "ConditionalCheckFailedException",
        "DeleteItem",
    )

    assert (
        finalization.delete_finalized_document(
            dynamodb,
            CONFIG["table_name"],
            validated_candidate(),
            TIMESTAMP,
        )
        is False
    )


def test_delete_finalized_document_propagates_unexpected_client_error():
    dynamodb = MagicMock()
    dynamodb.delete_item.side_effect = client_error(
        "AccessDeniedException",
        "DeleteItem",
    )

    with pytest.raises(ClientError):
        finalization.delete_finalized_document(
            dynamodb,
            CONFIG["table_name"],
            validated_candidate(),
            TIMESTAMP,
        )


def test_finalize_candidate_deletes_record_only_after_empty_s3_check():
    dynamodb = MagicMock()
    s3 = MagicMock()
    candidate = validated_candidate()

    s3.list_object_versions.return_value = {
        "Versions": [],
        "DeleteMarkers": [],
        "IsTruncated": False,
    }

    assert (
        finalization.finalize_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
            NOW,
        )
        == "deleted"
    )

    dynamodb.delete_item.assert_called_once()
    dynamodb.update_item.assert_not_called()


def test_finalize_candidate_requeues_when_s3_version_exists():
    dynamodb = MagicMock()
    s3 = MagicMock()
    candidate = validated_candidate()

    s3.list_object_versions.return_value = {
        "Versions": [
            {
                "Key": OBJECT_KEY,
                "VersionId": "late-version",
            }
        ],
        "DeleteMarkers": [],
        "IsTruncated": False,
    }

    assert (
        finalization.finalize_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
            NOW,
        )
        == "requeued"
    )

    dynamodb.update_item.assert_called_once()
    dynamodb.delete_item.assert_not_called()


def test_finalize_candidate_requeues_when_s3_delete_marker_exists():
    dynamodb = MagicMock()
    s3 = MagicMock()
    candidate = validated_candidate()

    s3.list_object_versions.return_value = {
        "Versions": [],
        "DeleteMarkers": [
            {
                "Key": OBJECT_KEY,
                "VersionId": "late-marker",
            }
        ],
        "IsTruncated": False,
    }

    assert (
        finalization.finalize_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
            NOW,
        )
        == "requeued"
    )

    dynamodb.update_item.assert_called_once()
    dynamodb.delete_item.assert_not_called()


def test_finalize_candidate_skips_when_requeue_conflicts():
    dynamodb = MagicMock()
    s3 = MagicMock()
    candidate = validated_candidate()

    s3.list_object_versions.return_value = {
        "Versions": [
            {
                "Key": OBJECT_KEY,
                "VersionId": "late-version",
            }
        ],
        "DeleteMarkers": [],
        "IsTruncated": False,
    }

    dynamodb.update_item.side_effect = client_error(
        "ConditionalCheckFailedException",
        "UpdateItem",
    )

    assert (
        finalization.finalize_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
            NOW,
        )
        == "skipped"
    )

    dynamodb.delete_item.assert_not_called()


def test_finalize_candidate_skips_when_delete_conflicts():
    dynamodb = MagicMock()
    s3 = MagicMock()
    candidate = validated_candidate()

    s3.list_object_versions.return_value = {
        "Versions": [],
        "DeleteMarkers": [],
        "IsTruncated": False,
    }

    dynamodb.delete_item.side_effect = client_error(
        "ConditionalCheckFailedException",
        "DeleteItem",
    )

    assert (
        finalization.finalize_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
            NOW,
        )
        == "skipped"
    )


def test_finalize_candidate_propagates_s3_inspection_failure():
    dynamodb = MagicMock()
    s3 = MagicMock()

    s3.list_object_versions.side_effect = client_error(
        "AccessDenied",
        "ListObjectVersions",
    )

    with pytest.raises(ClientError):
        finalization.finalize_candidate(
            dynamodb,
            s3,
            CONFIG,
            validated_candidate(),
            NOW,
        )

    dynamodb.delete_item.assert_not_called()
    dynamodb.update_item.assert_not_called()


def test_query_finalization_shard_uses_completed_partition():
    dynamodb = MagicMock()
    s3 = MagicMock()

    dynamodb.query.return_value = {
        "Items": [],
    }

    result = finalization.query_finalization_shard(
        dynamodb,
        s3,
        CONFIG,
        shard=0,
        max_items=10,
        now=NOW,
    )

    arguments = dynamodb.query.call_args.kwargs

    assert arguments["IndexName"] == CONFIG["index_name"]
    assert arguments["ExpressionAttributeValues"][":shard"] == {
        "S": "CLEANUP_COMPLETE#00"
    }
    assert arguments["ExpressionAttributeValues"][":cutoff"] == {
        "S": f"{TIMESTAMP}#\uffff"
    }
    assert result == {
        "processed": 0,
        "deleted": 0,
        "requeued": 0,
        "skipped": 0,
        "invalid": 0,
        "failed": 0,
    }


def test_query_finalization_shard_counts_invalid_candidate():
    dynamodb = MagicMock()
    s3 = MagicMock()

    dynamodb.query.return_value = {
        "Items": [
            {
                "PK": {"S": "invalid"},
            }
        ]
    }

    result = finalization.query_finalization_shard(
        dynamodb,
        s3,
        CONFIG,
        shard=0,
        max_items=10,
        now=NOW,
    )

    assert result["processed"] == 1
    assert result["invalid"] == 1
    s3.list_object_versions.assert_not_called()


def test_query_finalization_shard_follows_last_evaluated_key():
    dynamodb = MagicMock()
    s3 = MagicMock()

    last_evaluated_key = {
        "PK": {"S": "TENANT#tenant-001"},
        "SK": {"S": "DOCUMENT#document-001"},
        "GSI4PK": {"S": "CLEANUP_COMPLETE#00"},
        "GSI4SK": {"S": f"{FINALIZE_AFTER}#document-001"},
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

    result = finalization.query_finalization_shard(
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


def test_query_finalization_shard_respects_time_budget():
    dynamodb = MagicMock()
    s3 = MagicMock()

    result = finalization.query_finalization_shard(
        dynamodb,
        s3,
        CONFIG,
        shard=0,
        max_items=10,
        now=NOW,
        context=LambdaContext(1000),
    )

    assert result["processed"] == 0
    dynamodb.query.assert_not_called()


def test_finalize_completed_documents_rejects_naive_datetime():
    dynamodb = MagicMock()
    s3 = MagicMock()

    with pytest.raises(ValueError):
        finalization.finalize_completed_documents(
            dynamodb,
            s3,
            CONFIG,
            datetime(2026, 11, 15, 12, 0, 0),
        )


def test_finalize_completed_documents_aggregates_shard_results(monkeypatch):
    dynamodb = MagicMock()
    s3 = MagicMock()

    shard_results = [
        {
            "processed": 2,
            "deleted": 1,
            "requeued": 1,
            "skipped": 0,
            "invalid": 0,
            "failed": 0,
        },
        {
            "processed": 3,
            "deleted": 2,
            "requeued": 0,
            "skipped": 1,
            "invalid": 0,
            "failed": 0,
        },
    ]

    calls = []

    def fake_query_finalization_shard(**kwargs):
        calls.append(kwargs)
        return shard_results[len(calls) - 1]

    monkeypatch.setattr(
        finalization,
        "query_finalization_shard",
        fake_query_finalization_shard,
    )

    config = {
        **CONFIG,
        "shard_count": 2,
        "max_items": 10,
    }

    result = finalization.finalize_completed_documents(
        dynamodb,
        s3,
        config,
        NOW,
    )

    assert result == {
        "processed": 5,
        "deleted": 3,
        "requeued": 1,
        "skipped": 1,
        "invalid": 0,
        "failed": 0,
    }

    assert len(calls) == 2
    assert calls[0]["shard"] == 0
    assert calls[1]["shard"] == 1
    assert calls[1]["max_items"] == 8


def test_finalize_completed_documents_stops_at_global_max_items(
    monkeypatch,
):
    calls = []

    def fake_query_finalization_shard(**kwargs):
        calls.append(kwargs)
        return {
            "processed": kwargs["max_items"],
            "deleted": kwargs["max_items"],
            "requeued": 0,
            "skipped": 0,
            "invalid": 0,
            "failed": 0,
        }

    monkeypatch.setattr(
        finalization,
        "query_finalization_shard",
        fake_query_finalization_shard,
    )

    config = {
        **CONFIG,
        "shard_count": 4,
        "max_items": 3,
    }

    result = finalization.finalize_completed_documents(
        MagicMock(),
        MagicMock(),
        config,
        NOW,
    )

    assert result["processed"] == 3
    assert len(calls) == 1
