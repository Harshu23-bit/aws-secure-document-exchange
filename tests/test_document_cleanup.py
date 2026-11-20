import importlib.util
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "lambda" / "document_cleanup" / "handler.py"
)

SPEC = importlib.util.spec_from_file_location(
    "document_cleanup_handler",
    MODULE_PATH,
)
cleanup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cleanup)


NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)
TIMESTAMP = "2026-11-15T12:00:00Z"
EXPIRY = "2026-11-13T12:00:00Z"
CLEANUP_AFTER = "2026-11-14T12:00:00Z"

CONFIG = {
    "table_name": "cloudsec-test-submissions",
    "index_name": "PendingDocumentCleanupIndex",
    "bucket_name": "cloudsec-test-application-bucket",
    "shard_count": 4,
    "max_items": 50,
}

TENANT_ID = "tenant-001"
SUBMISSION_ID = "submission-001"
DOCUMENT_ID = "document-001"
OBJECT_KEY = f"tenants/{TENANT_ID}/submissions/{SUBMISSION_ID}/{DOCUMENT_ID}"


def make_candidate(
    document_id=DOCUMENT_ID,
    tenant_id=TENANT_ID,
    submission_id=SUBMISSION_ID,
    object_key=None,
    status="CLEANUP_PENDING",
    expires_at=EXPIRY,
    cleanup_after=CLEANUP_AFTER,
    cleanup_attempts=0,
    shard_count=4,
):
    shard = cleanup.get_document_cleanup_shard(
        document_id,
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
        "object_key": {"S": object_key},
        "status": {"S": status},
        "expires_at": {"S": expires_at},
        "cleanup_after": {"S": cleanup_after},
        "cleanup_attempts": {"N": str(cleanup_attempts)},
        "GSI4PK": {"S": f"CLEANUP_PENDING#{shard:02d}"},
        "GSI4SK": {"S": f"{cleanup_after}#{document_id}"},
    }


def validated_candidate(**kwargs):
    item = make_candidate(**kwargs)
    document_id = item["document_id"]["S"]
    shard = cleanup.get_document_cleanup_shard(
        document_id,
        CONFIG["shard_count"],
    )

    return cleanup.validate_candidate(
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


class LambdaContext:
    def __init__(self, remaining_ms=60000):
        self.remaining_ms = remaining_ms

    def get_remaining_time_in_millis(self):
        return self.remaining_ms


# Configuration


def test_get_config_accepts_valid_environment(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", CONFIG["table_name"])
    monkeypatch.setenv("CLEANUP_INDEX", CONFIG["index_name"])
    monkeypatch.setenv("BUCKET_NAME", CONFIG["bucket_name"])
    monkeypatch.setenv("SHARD_COUNT", "4")
    monkeypatch.setenv("MAX_ITEMS", "50")

    assert cleanup.get_config() == CONFIG


@pytest.mark.parametrize(
    "variable,value",
    [
        ("TABLE_NAME", ""),
        ("TABLE_NAME", "invalid table name"),
        ("CLEANUP_INDEX", "WrongIndex"),
        ("BUCKET_NAME", ""),
        ("BUCKET_NAME", "INVALID_BUCKET"),
        ("SHARD_COUNT", "0"),
        ("SHARD_COUNT", "17"),
        ("SHARD_COUNT", "not-a-number"),
        ("MAX_ITEMS", "0"),
        ("MAX_ITEMS", "101"),
        ("MAX_ITEMS", "not-a-number"),
    ],
)
def test_get_config_rejects_invalid_environment(
    monkeypatch,
    variable,
    value,
):
    monkeypatch.setenv("TABLE_NAME", CONFIG["table_name"])
    monkeypatch.setenv("CLEANUP_INDEX", CONFIG["index_name"])
    monkeypatch.setenv("BUCKET_NAME", CONFIG["bucket_name"])
    monkeypatch.setenv("SHARD_COUNT", "4")
    monkeypatch.setenv("MAX_ITEMS", "50")
    monkeypatch.setenv(variable, value)

    with pytest.raises(cleanup.ConfigurationError):
        cleanup.get_config()


# Timestamp handling


def test_format_utc_timestamp():
    assert cleanup.format_utc_timestamp(NOW) == TIMESTAMP


def test_format_utc_timestamp_rejects_naive_datetime():
    with pytest.raises(ValueError):
        cleanup.format_utc_timestamp(datetime(2026, 11, 15, 12, 0, 0))


def test_format_utc_timestamp_rejects_non_utc_datetime():
    non_utc = datetime(
        2026,
        11,
        15,
        17,
        30,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    with pytest.raises(ValueError):
        cleanup.format_utc_timestamp(non_utc)


def test_parse_utc_timestamp():
    parsed = cleanup.parse_utc_timestamp(TIMESTAMP)

    assert parsed == NOW
    assert parsed.tzinfo == UTC


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "2026-11-15",
        "2026-11-15T12:00:00",
        "2026-11-15T12:00:00+00:00",
        "2026-11-15T12:00:00.000Z",
        "2026-02-30T12:00:00Z",
    ],
)
def test_parse_utc_timestamp_rejects_noncanonical_values(value):
    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.parse_utc_timestamp(value)


# Sharding


def test_document_cleanup_shard_is_deterministic():
    first = cleanup.get_document_cleanup_shard(DOCUMENT_ID, 4)
    second = cleanup.get_document_cleanup_shard(DOCUMENT_ID, 4)

    assert first == second
    assert 0 <= first < 4


def test_document_cleanup_shard_is_within_configured_range():
    for shard_count in range(1, 17):
        shard = cleanup.get_document_cleanup_shard(
            DOCUMENT_ID,
            shard_count,
        )

        assert 0 <= shard < shard_count


# Candidate validation


def test_validate_candidate_accepts_valid_record():
    candidate = validated_candidate()

    assert candidate["tenant_id"] == TENANT_ID
    assert candidate["submission_id"] == SUBMISSION_ID
    assert candidate["document_id"] == DOCUMENT_ID
    assert candidate["object_key"] == OBJECT_KEY
    assert candidate["status"] == "CLEANUP_PENDING"
    assert candidate["cleanup_attempts"] == 0


def test_validate_candidate_rejects_non_dictionary():
    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.validate_candidate(
            None,
            0,
            4,
            NOW,
        )


@pytest.mark.parametrize(
    "attribute",
    [
        "tenant_id",
        "submission_id",
        "document_id",
        "object_key",
        "status",
        "expires_at",
        "cleanup_after",
        "PK",
        "SK",
        "GSI4PK",
        "GSI4SK",
        "cleanup_attempts",
    ],
)
def test_validate_candidate_rejects_missing_attributes(attribute):
    item = make_candidate()
    del item[attribute]

    shard = cleanup.get_document_cleanup_shard(DOCUMENT_ID, 4)

    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.validate_candidate(item, shard, 4, NOW)


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
    shard = cleanup.get_document_cleanup_shard(DOCUMENT_ID, 4)

    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.validate_candidate(item, shard, 4, NOW)


@pytest.mark.parametrize(
    "tenant_id",
    [
        "../tenant",
        "tenant/child",
        "tenant key",
        "",
        "..",
    ],
)
def test_validate_candidate_rejects_invalid_tenant_id(tenant_id):
    item = make_candidate(tenant_id=tenant_id)
    shard = cleanup.get_document_cleanup_shard(DOCUMENT_ID, 4)

    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.validate_candidate(item, shard, 4, NOW)


@pytest.mark.parametrize(
    "submission_id",
    [
        "../submission",
        "submission/child",
        "submission key",
        "",
        "..",
    ],
)
def test_validate_candidate_rejects_invalid_submission_id(
    submission_id,
):
    item = make_candidate(submission_id=submission_id)
    shard = cleanup.get_document_cleanup_shard(DOCUMENT_ID, 4)

    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.validate_candidate(item, shard, 4, NOW)


def test_validate_candidate_rejects_noncanonical_object_key():
    item = make_candidate(object_key="tenants/tenant-001/other-object")
    shard = cleanup.get_document_cleanup_shard(DOCUMENT_ID, 4)

    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.validate_candidate(item, shard, 4, NOW)


def test_validate_candidate_rejects_wrong_status():
    item = make_candidate(status="PENDING_UPLOAD")
    shard = cleanup.get_document_cleanup_shard(DOCUMENT_ID, 4)

    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.validate_candidate(item, shard, 4, NOW)


def test_validate_candidate_rejects_wrong_shard():
    item = make_candidate()
    actual_shard = cleanup.get_document_cleanup_shard(
        DOCUMENT_ID,
        4,
    )
    wrong_shard = (actual_shard + 1) % 4

    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.validate_candidate(item, wrong_shard, 4, NOW)


def test_validate_candidate_rejects_wrong_gsi_partition():
    item = make_candidate()
    item["GSI4PK"] = {"S": "CLEANUP_PENDING#99"}

    shard = cleanup.get_document_cleanup_shard(DOCUMENT_ID, 4)

    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.validate_candidate(item, shard, 4, NOW)


def test_validate_candidate_rejects_wrong_gsi_sort_key():
    item = make_candidate()
    item["GSI4SK"] = {"S": "wrong-sort-key"}

    shard = cleanup.get_document_cleanup_shard(DOCUMENT_ID, 4)

    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.validate_candidate(item, shard, 4, NOW)


def test_validate_candidate_rejects_future_cleanup_time():
    future_cleanup = "2026-11-16T12:00:00Z"
    item = make_candidate(cleanup_after=future_cleanup)
    shard = cleanup.get_document_cleanup_shard(DOCUMENT_ID, 4)

    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.validate_candidate(item, shard, 4, NOW)


def test_validate_candidate_rejects_cleanup_before_expiry():
    item = make_candidate(
        expires_at="2026-11-14T12:00:00Z",
        cleanup_after="2026-11-13T12:00:00Z",
    )
    shard = cleanup.get_document_cleanup_shard(DOCUMENT_ID, 4)

    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.validate_candidate(item, shard, 4, NOW)


@pytest.mark.parametrize(
    "attempts",
    [
        "-1",
        "invalid",
        "1.5",
    ],
)
def test_validate_candidate_rejects_invalid_cleanup_attempts(attempts):
    item = make_candidate()
    item["cleanup_attempts"] = {"N": attempts}

    shard = cleanup.get_document_cleanup_shard(DOCUMENT_ID, 4)

    with pytest.raises(cleanup.CandidateValidationError):
        cleanup.validate_candidate(item, shard, 4, NOW)


# Time budget


def test_has_time_remaining_without_context():
    assert cleanup.has_time_remaining(None) is True


def test_has_time_remaining_above_buffer():
    assert cleanup.has_time_remaining(LambdaContext(6000)) is True


def test_has_time_remaining_at_buffer():
    assert (
        cleanup.has_time_remaining(LambdaContext(cleanup.MINIMUM_REMAINING_TIME_MS))
        is False
    )


def test_has_time_remaining_below_buffer():
    assert cleanup.has_time_remaining(LambdaContext(1000)) is False


# S3 exact-key filtering


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

    result = cleanup.get_exact_key_versions(page, OBJECT_KEY)

    assert result == [
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
    with pytest.raises(cleanup.S3CleanupError):
        cleanup.get_exact_key_versions(page, OBJECT_KEY)


def test_list_object_versions_page_builds_first_page_request():
    s3 = MagicMock()
    s3.list_object_versions.return_value = {}

    cleanup.list_object_versions_page(
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

    cleanup.list_object_versions_page(
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


# S3 deletion and pagination


def test_delete_exact_key_versions_deletes_versions_and_markers():
    s3 = MagicMock()
    s3.list_object_versions.return_value = {
        "Versions": [
            {
                "Key": OBJECT_KEY,
                "VersionId": "version-1",
            }
        ],
        "DeleteMarkers": [
            {
                "Key": OBJECT_KEY,
                "VersionId": "marker-1",
            }
        ],
        "IsTruncated": False,
    }
    s3.delete_objects.return_value = {"Deleted": []}

    assert (
        cleanup.delete_exact_key_versions(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )
        is True
    )

    s3.delete_objects.assert_called_once_with(
        Bucket=CONFIG["bucket_name"],
        Delete={
            "Objects": [
                {
                    "Key": OBJECT_KEY,
                    "VersionId": "version-1",
                },
                {
                    "Key": OBJECT_KEY,
                    "VersionId": "marker-1",
                },
            ],
            "Quiet": True,
        },
    )


def test_delete_exact_key_versions_does_not_delete_similar_keys():
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

    cleanup.delete_exact_key_versions(
        s3,
        CONFIG["bucket_name"],
        OBJECT_KEY,
    )

    s3.delete_objects.assert_not_called()


def test_delete_exact_key_versions_handles_pagination():
    s3 = MagicMock()
    s3.list_object_versions.side_effect = [
        {
            "Versions": [
                {
                    "Key": OBJECT_KEY,
                    "VersionId": "version-1",
                }
            ],
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
    s3.delete_objects.return_value = {"Deleted": []}

    cleanup.delete_exact_key_versions(
        s3,
        CONFIG["bucket_name"],
        OBJECT_KEY,
    )

    assert s3.list_object_versions.call_count == 2
    assert s3.delete_objects.call_count == 2

    second_call = s3.list_object_versions.call_args_list[1]

    assert second_call.kwargs["KeyMarker"] == OBJECT_KEY
    assert second_call.kwargs["VersionIdMarker"] == "version-1"


def test_delete_exact_key_versions_rejects_truncated_response_without_marker():
    s3 = MagicMock()
    s3.list_object_versions.return_value = {
        "Versions": [],
        "DeleteMarkers": [],
        "IsTruncated": True,
    }

    with pytest.raises(cleanup.S3CleanupError):
        cleanup.delete_exact_key_versions(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )


def test_delete_exact_key_versions_rejects_partial_delete_failure():
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
    s3.delete_objects.return_value = {
        "Errors": [
            {
                "Key": OBJECT_KEY,
                "VersionId": "version-1",
                "Code": "AccessDenied",
            }
        ]
    }

    with pytest.raises(cleanup.S3CleanupError):
        cleanup.delete_exact_key_versions(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )


def test_delete_exact_key_versions_does_not_treat_empty_response_as_error():
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
    s3.delete_objects.return_value = {
        "Deleted": [
            {
                "Key": OBJECT_KEY,
                "VersionId": "version-1",
            }
        ]
    }

    assert (
        cleanup.delete_exact_key_versions(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )
        is True
    )


# S3 verification


def test_verify_object_key_empty_returns_true_when_no_versions_exist():
    s3 = MagicMock()
    s3.list_object_versions.return_value = {
        "Versions": [],
        "DeleteMarkers": [],
        "IsTruncated": False,
    }

    assert (
        cleanup.verify_object_key_empty(
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
        cleanup.verify_object_key_empty(
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
        cleanup.verify_object_key_empty(
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
        cleanup.verify_object_key_empty(
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
        cleanup.verify_object_key_empty(
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

    with pytest.raises(cleanup.S3CleanupError):
        cleanup.verify_object_key_empty(
            s3,
            CONFIG["bucket_name"],
            OBJECT_KEY,
        )


# DynamoDB attempt recording


def test_record_cleanup_attempt_updates_attempt_counter():
    dynamodb = MagicMock()
    candidate = validated_candidate()

    assert (
        cleanup.record_cleanup_attempt(
            dynamodb,
            CONFIG["table_name"],
            candidate,
            TIMESTAMP,
        )
        is True
    )

    arguments = dynamodb.update_item.call_args.kwargs

    assert arguments["TableName"] == CONFIG["table_name"]
    assert arguments["Key"]["PK"] == {"S": candidate["pk"]}
    assert arguments["Key"]["SK"] == {"S": candidate["sk"]}
    assert "cleanup_attempts" in arguments["UpdateExpression"]
    assert "entity_type = :document" in arguments["ConditionExpression"]


def test_record_cleanup_attempt_returns_false_on_conditional_conflict():
    dynamodb = MagicMock()
    dynamodb.update_item.side_effect = client_error(
        "ConditionalCheckFailedException",
        "UpdateItem",
    )

    assert (
        cleanup.record_cleanup_attempt(
            dynamodb,
            CONFIG["table_name"],
            validated_candidate(),
            TIMESTAMP,
        )
        is False
    )


def test_record_cleanup_attempt_propagates_unexpected_client_error():
    dynamodb = MagicMock()
    dynamodb.update_item.side_effect = client_error(
        "AccessDeniedException",
        "UpdateItem",
    )

    with pytest.raises(ClientError):
        cleanup.record_cleanup_attempt(
            dynamodb,
            CONFIG["table_name"],
            validated_candidate(),
            TIMESTAMP,
        )


# DynamoDB completion transition


def test_transition_cleanup_complete_sets_finalization_grace_period():
    dynamodb = MagicMock()
    candidate = validated_candidate()

    assert (
        cleanup.transition_cleanup_complete(
            dynamodb,
            CONFIG["table_name"],
            candidate,
            TIMESTAMP,
        )
        is True
    )

    arguments = dynamodb.update_item.call_args.kwargs
    values = arguments["ExpressionAttributeValues"]

    assert values[":complete"] == {"S": "CLEANUP_COMPLETE"}
    assert values[":completed_at"] == {"S": TIMESTAMP}
    assert values[":finalize_after"] == {"S": "2026-11-16T12:00:00Z"}
    assert values[":gsi4pk"] == {"S": f"CLEANUP_COMPLETE#{candidate['shard']:02d}"}
    assert values[":gsi4sk"] == {"S": f"2026-11-16T12:00:00Z#{DOCUMENT_ID}"}
    assert "REMOVE last_cleanup_error" in arguments["UpdateExpression"]


def test_transition_cleanup_complete_returns_false_on_conditional_conflict():
    dynamodb = MagicMock()
    dynamodb.update_item.side_effect = client_error(
        "ConditionalCheckFailedException",
        "UpdateItem",
    )

    assert (
        cleanup.transition_cleanup_complete(
            dynamodb,
            CONFIG["table_name"],
            validated_candidate(),
            TIMESTAMP,
        )
        is False
    )


def test_transition_cleanup_complete_propagates_unexpected_client_error():
    dynamodb = MagicMock()
    dynamodb.update_item.side_effect = client_error(
        "AccessDeniedException",
        "UpdateItem",
    )

    with pytest.raises(ClientError):
        cleanup.transition_cleanup_complete(
            dynamodb,
            CONFIG["table_name"],
            validated_candidate(),
            TIMESTAMP,
        )


# Error recording


def test_record_cleanup_error_stores_bounded_error_code():
    dynamodb = MagicMock()
    candidate = validated_candidate()

    cleanup.record_cleanup_error(
        dynamodb,
        CONFIG["table_name"],
        candidate,
        TIMESTAMP,
        "AccessDenied",
    )

    arguments = dynamodb.update_item.call_args.kwargs

    assert arguments["ExpressionAttributeValues"][":error"] == {"S": "AccessDenied"}
    assert arguments["ExpressionAttributeValues"][":timestamp"] == {"S": TIMESTAMP}


# Complete candidate workflow


def test_cleanup_candidate_completes_only_after_s3_verification():
    dynamodb = MagicMock()
    s3 = MagicMock()
    s3.delete_objects.return_value = {
        "Errors": [],
    }
    candidate = validated_candidate()

    s3.list_object_versions.side_effect = [
        {
            "Versions": [
                {
                    "Key": OBJECT_KEY,
                    "VersionId": "version-1",
                }
            ],
            "DeleteMarkers": [],
            "IsTruncated": False,
        },
        {
            "Versions": [],
            "DeleteMarkers": [],
            "IsTruncated": False,
        },
    ]

    assert (
        cleanup.cleanup_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
            NOW,
        )
        == "completed"
    )

    assert dynamodb.update_item.call_count == 2
    s3.delete_objects.assert_called_once()


def test_cleanup_candidate_does_not_complete_when_versions_remain():
    dynamodb = MagicMock()
    s3 = MagicMock()
    candidate = validated_candidate()

    s3.list_object_versions.side_effect = [
        {
            "Versions": [
                {
                    "Key": OBJECT_KEY,
                    "VersionId": "version-1",
                }
            ],
            "DeleteMarkers": [],
            "IsTruncated": False,
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

    assert (
        cleanup.cleanup_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
            NOW,
        )
        == "failed"
    )

    assert dynamodb.update_item.call_count == 2
    assert (
        "last_cleanup_error"
        in (dynamodb.update_item.call_args.kwargs["UpdateExpression"])
    )

    s3.delete_objects.assert_called_once()


def test_cleanup_candidate_records_s3_client_error():
    dynamodb = MagicMock()
    s3 = MagicMock()
    candidate = validated_candidate()

    s3.list_object_versions.side_effect = client_error(
        "AccessDenied",
        "ListObjectVersions",
    )

    assert (
        cleanup.cleanup_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
            NOW,
        )
        == "failed"
    )

    assert dynamodb.update_item.call_count == 2

    error_update = dynamodb.update_item.call_args.kwargs

    assert error_update["ExpressionAttributeValues"][":error"] == {"S": "AccessDenied"}


def test_cleanup_candidate_records_botocore_connection_error():
    dynamodb = MagicMock()
    s3 = MagicMock()
    candidate = validated_candidate()

    s3.list_object_versions.side_effect = EndpointConnectionError(
        endpoint_url="https://s3.example.invalid"
    )

    assert (
        cleanup.cleanup_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
            NOW,
        )
        == "failed"
    )

    error_update = dynamodb.update_item.call_args.kwargs

    assert error_update["ExpressionAttributeValues"][":error"] == {
        "S": "EndpointConnectionError"
    }


def test_cleanup_candidate_skips_when_attempt_claim_fails():
    dynamodb = MagicMock()
    s3 = MagicMock()
    candidate = validated_candidate()

    dynamodb.update_item.side_effect = client_error(
        "ConditionalCheckFailedException",
        "UpdateItem",
    )

    assert (
        cleanup.cleanup_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
            NOW,
        )
        == "skipped"
    )

    s3.list_object_versions.assert_not_called()
    s3.delete_objects.assert_not_called()


def test_cleanup_candidate_does_not_transition_after_delete_failure():
    dynamodb = MagicMock()
    s3 = MagicMock()
    candidate = validated_candidate()

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
    s3.delete_objects.return_value = {
        "Errors": [
            {
                "Key": OBJECT_KEY,
                "VersionId": "version-1",
                "Code": "AccessDenied",
            }
        ]
    }

    assert (
        cleanup.cleanup_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
            NOW,
        )
        == "failed"
    )

    assert dynamodb.update_item.call_count == 2
    assert (
        "CLEANUP_COMPLETE"
        not in (dynamodb.update_item.call_args.kwargs["UpdateExpression"])
    )


def test_cleanup_candidate_skips_when_completion_transition_conflicts():
    dynamodb = MagicMock()
    s3 = MagicMock()
    candidate = validated_candidate()

    s3.list_object_versions.side_effect = [
        {
            "Versions": [],
            "DeleteMarkers": [],
            "IsTruncated": False,
        },
        {
            "Versions": [],
            "DeleteMarkers": [],
            "IsTruncated": False,
        },
    ]

    dynamodb.update_item.side_effect = [
        {},
        client_error(
            "ConditionalCheckFailedException",
            "UpdateItem",
        ),
    ]

    assert (
        cleanup.cleanup_candidate(
            dynamodb,
            s3,
            CONFIG,
            candidate,
            NOW,
        )
        == "skipped"
    )


# Query and bounded processing


def test_query_cleanup_shard_uses_cleanup_index_and_cutoff():
    dynamodb = MagicMock()
    s3 = MagicMock()

    dynamodb.query.return_value = {
        "Items": [],
    }

    result = cleanup.query_cleanup_shard(
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
        "S": "CLEANUP_PENDING#00"
    }
    assert arguments["ExpressionAttributeValues"][":cutoff"] == {
        "S": f"{TIMESTAMP}#\uffff"
    }
    assert result == {
        "processed": 0,
        "completed": 0,
        "skipped": 0,
        "invalid": 0,
        "failed": 0,
    }


def test_query_cleanup_shard_counts_invalid_candidate():
    dynamodb = MagicMock()
    s3 = MagicMock()

    dynamodb.query.return_value = {
        "Items": [
            {
                "PK": {"S": "invalid"},
            }
        ]
    }

    result = cleanup.query_cleanup_shard(
        dynamodb,
        s3,
        CONFIG,
        shard=0,
        max_items=10,
        now=NOW,
    )

    assert result["processed"] == 1
    assert result["invalid"] == 1
    assert result["completed"] == 0

    s3.list_object_versions.assert_not_called()


def test_query_cleanup_shard_respects_time_budget_before_query():
    dynamodb = MagicMock()
    s3 = MagicMock()

    result = cleanup.query_cleanup_shard(
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


def test_query_cleanup_shard_respects_global_item_limit():
    dynamodb = MagicMock()
    s3 = MagicMock()

    dynamodb.query.return_value = {
        "Items": [
            {"PK": {"S": "invalid-1"}},
            {"PK": {"S": "invalid-2"}},
            {"PK": {"S": "invalid-3"}},
        ]
    }

    result = cleanup.query_cleanup_shard(
        dynamodb,
        s3,
        CONFIG,
        shard=0,
        max_items=2,
        now=NOW,
    )

    assert result["processed"] == 2
    assert result["invalid"] == 2


def test_cleanup_pending_documents_rejects_naive_datetime():
    dynamodb = MagicMock()
    s3 = MagicMock()

    with pytest.raises(ValueError):
        cleanup.cleanup_pending_documents(
            dynamodb,
            s3,
            CONFIG,
            datetime(2026, 11, 15, 12, 0, 0),
        )


def test_cleanup_pending_documents_aggregates_shard_results(monkeypatch):
    dynamodb = MagicMock()
    s3 = MagicMock()

    shard_results = [
        {
            "processed": 2,
            "completed": 1,
            "skipped": 0,
            "invalid": 1,
            "failed": 0,
        },
        {
            "processed": 3,
            "completed": 2,
            "skipped": 1,
            "invalid": 0,
            "failed": 0,
        },
    ]

    calls = []

    def fake_query_cleanup_shard(**kwargs):
        calls.append(kwargs)
        return shard_results[len(calls) - 1]

    monkeypatch.setattr(
        cleanup,
        "query_cleanup_shard",
        fake_query_cleanup_shard,
    )

    config = {
        **CONFIG,
        "shard_count": 2,
        "max_items": 10,
    }

    result = cleanup.cleanup_pending_documents(
        dynamodb,
        s3,
        config,
        NOW,
    )

    assert result == {
        "processed": 5,
        "completed": 3,
        "skipped": 1,
        "invalid": 1,
        "failed": 0,
    }

    assert len(calls) == 2
    assert calls[0]["shard"] == 0
    assert calls[1]["shard"] == 1
    assert calls[1]["max_items"] == 8


def test_cleanup_pending_documents_stops_at_global_max_items(
    monkeypatch,
):
    dynamodb = MagicMock()
    s3 = MagicMock()
    calls = []

    def fake_query_cleanup_shard(**kwargs):
        calls.append(kwargs)
        return {
            "processed": kwargs["max_items"],
            "completed": kwargs["max_items"],
            "skipped": 0,
            "invalid": 0,
            "failed": 0,
        }

    monkeypatch.setattr(
        cleanup,
        "query_cleanup_shard",
        fake_query_cleanup_shard,
    )

    config = {
        **CONFIG,
        "shard_count": 4,
        "max_items": 3,
    }

    result = cleanup.cleanup_pending_documents(
        dynamodb,
        s3,
        config,
        NOW,
    )

    assert result["processed"] == 3
    assert len(calls) == 1


def test_cleanup_pending_documents_stops_when_time_budget_expires(
    monkeypatch,
):
    dynamodb = MagicMock()
    s3 = MagicMock()

    def fake_query_cleanup_shard(**kwargs):
        return {
            "processed": 1,
            "completed": 1,
            "skipped": 0,
            "invalid": 0,
            "failed": 0,
        }

    monkeypatch.setattr(
        cleanup,
        "query_cleanup_shard",
        fake_query_cleanup_shard,
    )

    context = MagicMock()
    context.get_remaining_time_in_millis.side_effect = [
        10000,
        1000,
    ]

    result = cleanup.cleanup_pending_documents(
        dynamodb,
        s3,
        {
            **CONFIG,
            "max_items": 10,
        },
        NOW,
        context,
    )

    assert result["processed"] == 1
