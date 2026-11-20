import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = PROJECT_ROOT / "lambda" / "document_expiry" / "handler.py"

spec = importlib.util.spec_from_file_location(
    "document_expiry_handler",
    HANDLER_PATH,
)

handler_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler_module)


NOW = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)
DOCUMENT_ID = "document-456"
TENANT_ID = "tenant-a"
SUBMISSION_ID = "submission-123"
SIZE_BYTES = 1024


def make_candidate(
    *,
    expires_at=None,
    status="PENDING_UPLOAD",
    size_bytes=SIZE_BYTES,
):
    expires_at = expires_at or (NOW - timedelta(minutes=1)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")

    shard = handler_module.get_document_expiry_shard(
        DOCUMENT_ID,
        4,
    )

    object_key = f"tenants/{TENANT_ID}/submissions/{SUBMISSION_ID}/{DOCUMENT_ID}"

    return {
        "PK": {"S": (f"TENANT#{TENANT_ID}#SUBMISSION#{SUBMISSION_ID}")},
        "SK": {"S": f"DOCUMENT#{DOCUMENT_ID}"},
        "tenant_id": {"S": TENANT_ID},
        "submission_id": {"S": SUBMISSION_ID},
        "document_id": {"S": DOCUMENT_ID},
        "object_key": {"S": object_key},
        "size_bytes": {"N": str(size_bytes)},
        "expires_at": {"S": expires_at},
        "status": {"S": status},
        "GSI3PK": {"S": f"PENDING_UPLOAD#{shard:02d}"},
        "GSI3SK": {"S": f"{expires_at}#{DOCUMENT_ID}"},
    }


def validated_candidate():
    shard = handler_module.get_document_expiry_shard(
        DOCUMENT_ID,
        4,
    )

    return handler_module.validate_candidate(
        make_candidate(),
        shard,
        4,
        NOW,
    )


class TestConfiguration:
    def test_valid_configuration(self, monkeypatch):
        monkeypatch.setenv("TABLE_NAME", "test-submissions")
        monkeypatch.setenv(
            "EXPIRY_INDEX",
            "PendingDocumentExpiryIndex",
        )
        monkeypatch.setenv("SHARD_COUNT", "4")
        monkeypatch.setenv("MAX_ITEMS", "100")

        config = handler_module.get_config()

        assert config == {
            "table_name": "test-submissions",
            "index_name": "PendingDocumentExpiryIndex",
            "shard_count": 4,
            "max_items": 100,
        }

    @pytest.mark.parametrize(
        ("variable", "value"),
        [
            ("TABLE_NAME", ""),
            ("TABLE_NAME", "bad table name"),
            ("EXPIRY_INDEX", "bad index"),
            ("SHARD_COUNT", "0"),
            ("SHARD_COUNT", "17"),
            ("SHARD_COUNT", "invalid"),
            ("MAX_ITEMS", "0"),
            ("MAX_ITEMS", "101"),
            ("MAX_ITEMS", "invalid"),
        ],
    )
    def test_invalid_configuration_rejected(
        self,
        monkeypatch,
        variable,
        value,
    ):
        monkeypatch.setenv("TABLE_NAME", "test-submissions")
        monkeypatch.setenv(
            "EXPIRY_INDEX",
            "PendingDocumentExpiryIndex",
        )
        monkeypatch.setenv("SHARD_COUNT", "4")
        monkeypatch.setenv("MAX_ITEMS", "100")
        monkeypatch.setenv(variable, value)

        with pytest.raises(handler_module.ConfigurationError):
            handler_module.get_config()


class TestCandidateValidation:
    def test_valid_expired_candidate(self):
        candidate = handler_module.validate_candidate(
            make_candidate(),
            handler_module.get_document_expiry_shard(
                DOCUMENT_ID,
                4,
            ),
            4,
            NOW,
        )

        assert candidate["tenant_id"] == TENANT_ID
        assert candidate["submission_id"] == SUBMISSION_ID
        assert candidate["document_id"] == DOCUMENT_ID
        assert candidate["size_bytes"] == SIZE_BYTES

    def test_future_expiry_rejected(self):
        item = make_candidate(
            expires_at=(NOW + timedelta(minutes=10))
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

        shard = handler_module.get_document_expiry_shard(
            DOCUMENT_ID,
            4,
        )

        with pytest.raises(handler_module.CandidateValidationError):
            handler_module.validate_candidate(
                item,
                shard,
                4,
                NOW,
            )

    def test_non_pending_status_rejected(self):
        item = make_candidate(status="UPLOADED")

        shard = handler_module.get_document_expiry_shard(
            DOCUMENT_ID,
            4,
        )

        with pytest.raises(handler_module.CandidateValidationError):
            handler_module.validate_candidate(
                item,
                shard,
                4,
                NOW,
            )

    @pytest.mark.parametrize(
        "expires_at",
        [
            "not-a-timestamp",
            "2026-11-14T11:00:00+00:00",
            "2026-11-14T11:00:00.000Z",
            "2026-11-14T11:00:00",
        ],
    )
    def test_noncanonical_expiry_rejected(self, expires_at):
        item = make_candidate(expires_at=expires_at)

        shard = handler_module.get_document_expiry_shard(
            DOCUMENT_ID,
            4,
        )

        with pytest.raises(handler_module.CandidateValidationError):
            handler_module.validate_candidate(
                item,
                shard,
                4,
                NOW,
            )

    @pytest.mark.parametrize(
        "object_key",
        [
            "",
            "tenants/another-tenant/submissions/submission-123/document-456",
            "tenants/tenant-a/submissions/another-submission/document-456",
            "tenants/tenant-a/submissions/submission-123/another-document",
            "tenants/tenant-a/submissions/submission-123/document-document-456",
        ],
    )
    def test_noncanonical_object_key_rejected(self, object_key):
        item = make_candidate()
        item["object_key"] = {"S": object_key}

        shard = handler_module.get_document_expiry_shard(
            DOCUMENT_ID,
            4,
        )

        with pytest.raises(handler_module.CandidateValidationError):
            handler_module.validate_candidate(
                item,
                shard,
                4,
                NOW,
            )

    def test_missing_object_key_rejected(self):
        item = make_candidate()
        del item["object_key"]

        shard = handler_module.get_document_expiry_shard(
            DOCUMENT_ID,
            4,
        )

        with pytest.raises(handler_module.CandidateValidationError):
            handler_module.validate_candidate(
                item,
                shard,
                4,
                NOW,
            )

    def test_wrong_document_key_rejected(self):
        item = make_candidate()
        item["SK"] = {"S": "DOCUMENT#another-document"}

        shard = handler_module.get_document_expiry_shard(
            DOCUMENT_ID,
            4,
        )

        with pytest.raises(handler_module.CandidateValidationError):
            handler_module.validate_candidate(
                item,
                shard,
                4,
                NOW,
            )

    def test_wrong_shard_rejected(self):
        item = make_candidate()

        shard = handler_module.get_document_expiry_shard(
            DOCUMENT_ID,
            4,
        )

        with pytest.raises(handler_module.CandidateValidationError):
            handler_module.validate_candidate(
                item,
                (shard + 1) % 4,
                4,
                NOW,
            )

    @pytest.mark.parametrize(
        "size",
        [
            "0",
            "-1",
            "1.5",
            "invalid",
            str(10 * 1024 * 1024 + 1),
        ],
    )
    def test_invalid_document_size_rejected(self, size):
        item = make_candidate()
        item["size_bytes"] = {"N": size}

        shard = handler_module.get_document_expiry_shard(
            DOCUMENT_ID,
            4,
        )

        with pytest.raises(handler_module.CandidateValidationError):
            handler_module.validate_candidate(
                item,
                shard,
                4,
                NOW,
            )


class TestCleanupTransaction:
    def test_transaction_updates_all_four_counters(self):
        candidate = validated_candidate()

        transaction = handler_module.build_cleanup_transaction(
            "test-submissions",
            candidate,
            "2026-11-14T12:00:00Z",
        )

        assert len(transaction) == 2

        update = transaction[0]["Update"]

        expression = update["UpdateExpression"]
        names = update["ExpressionAttributeNames"]

        assert "#pending_count = #pending_count - :one" in expression
        assert "#pending_bytes = #pending_bytes - :size" in expression
        assert "#total_count = #total_count - :one" in expression
        assert "#total_bytes = #total_bytes - :size" in expression

        assert names["#pending_count"] == "pending_document_count"
        assert names["#pending_bytes"] == "pending_document_bytes"
        assert names["#total_count"] == "total_document_count"
        assert names["#total_bytes"] == "total_document_bytes"

    def test_transaction_conditions_counters_and_document(self):
        candidate = validated_candidate()

        transaction = handler_module.build_cleanup_transaction(
            "test-submissions",
            candidate,
            "2026-11-14T12:00:00Z",
        )

        update = transaction[0]["Update"]
        document_update = transaction[1]["Update"]

        assert "attribute_type" in update["ConditionExpression"]
        assert "#pending_count > :zero" in update["ConditionExpression"]
        assert "#pending_bytes >= :size" in update["ConditionExpression"]
        assert "#total_count > :zero" in update["ConditionExpression"]
        assert "#total_bytes >= :size" in update["ConditionExpression"]
        assert "attribute_exists(#pending_count)" in update["ConditionExpression"]
        assert "attribute_exists(#pending_bytes)" in update["ConditionExpression"]
        assert "attribute_exists(#total_count)" in update["ConditionExpression"]
        assert "attribute_exists(#total_bytes)" in update["ConditionExpression"]

        assert "#status = :pending" in (document_update["ConditionExpression"])
        assert "entity_type = :entity_type" in (document_update["ConditionExpression"])
        assert "object_key = :object_key" in (document_update["ConditionExpression"])
        assert "expires_at <= :cutoff" in (document_update["ConditionExpression"])

        values = document_update["ExpressionAttributeValues"]
        assert values[":entity_type"] == {"S": "DOCUMENT"}
        assert values[":pending"] == {"S": "PENDING_UPLOAD"}
        assert values[":cleanup_pending"] == {"S": "CLEANUP_PENDING"}
        assert values[":object_key"] == {
            "S": (f"tenants/{TENANT_ID}/submissions/{SUBMISSION_ID}/{DOCUMENT_ID}")
        }
        assert values[":zero"] == {"N": "0"}

    def test_transaction_creates_cleanup_tombstone(self):
        candidate = validated_candidate()

        transaction = handler_module.build_cleanup_transaction(
            "test-submissions",
            candidate,
            "2026-11-14T12:00:00Z",
        )

        document_update = transaction[1]["Update"]
        expression = document_update["UpdateExpression"]
        values = document_update["ExpressionAttributeValues"]

        assert "SET #status = :cleanup_pending" in expression
        assert "GSI4PK = :gsi4pk" in expression
        assert "GSI4SK = :gsi4sk" in expression
        assert "cleanup_after = :cleanup_after" in expression
        assert "cleanup_attempts = :zero" in expression
        assert "REMOVE GSI3PK, GSI3SK" in expression

        assert values[":cleanup_pending"] == {"S": "CLEANUP_PENDING"}
        assert values[":gsi4pk"]["S"].startswith("CLEANUP_PENDING#")
        assert values[":gsi4sk"]["S"].endswith(f"#{DOCUMENT_ID}")
        assert values[":cleanup_after"] == {"S": "2026-11-15T11:59:00Z"}

    def test_successful_transaction_returns_true(self):
        dynamodb = MagicMock()

        result = handler_module.transition_expired_candidate(
            dynamodb,
            "test-submissions",
            validated_candidate(),
            "2026-11-14T12:00:00Z",
        )

        assert result is True
        dynamodb.transact_write_items.assert_called_once()

    def test_conditional_race_returns_false(self):
        dynamodb = MagicMock()

        dynamodb.transact_write_items.side_effect = ClientError(
            {
                "Error": {
                    "Code": "TransactionCanceledException",
                    "Message": "Conditional check failed",
                },
                "CancellationReasons": [
                    {"Code": "None"},
                    {"Code": "ConditionalCheckFailed"},
                ],
            },
            "TransactWriteItems",
        )

        result = handler_module.transition_expired_candidate(
            dynamodb,
            "test-submissions",
            validated_candidate(),
            "2026-11-14T12:00:00Z",
        )

        assert result is False

    def test_transaction_conflict_returns_false(self):
        dynamodb = MagicMock()

        dynamodb.transact_write_items.side_effect = ClientError(
            {
                "Error": {
                    "Code": "TransactionCanceledException",
                    "Message": "Transaction conflict",
                },
                "CancellationReasons": [
                    {"Code": "TransactionConflict"},
                    {"Code": "None"},
                ],
            },
            "TransactWriteItems",
        )

        result = handler_module.transition_expired_candidate(
            dynamodb,
            "test-submissions",
            validated_candidate(),
            "2026-11-14T12:00:00Z",
        )

        assert result is False

    def test_unknown_cancellation_reason_propagates(self):
        dynamodb = MagicMock()

        dynamodb.transact_write_items.side_effect = ClientError(
            {
                "Error": {
                    "Code": "TransactionCanceledException",
                    "Message": "Unexpected cancellation",
                },
                "CancellationReasons": [
                    {"Code": "ValidationError"},
                    {"Code": "None"},
                ],
            },
            "TransactWriteItems",
        )

        with pytest.raises(ClientError):
            handler_module.transition_expired_candidate(
                dynamodb,
                "test-submissions",
                validated_candidate(),
                "2026-11-14T12:00:00Z",
            )

    def test_missing_cancellation_reasons_propagate(self):
        dynamodb = MagicMock()

        dynamodb.transact_write_items.side_effect = ClientError(
            {
                "Error": {
                    "Code": "TransactionCanceledException",
                    "Message": "Unknown cancellation",
                },
            },
            "TransactWriteItems",
        )

        with pytest.raises(ClientError):
            handler_module.transition_expired_candidate(
                dynamodb,
                "test-submissions",
                validated_candidate(),
                "2026-11-14T12:00:00Z",
            )

    def test_unexpected_aws_error_propagates(self):
        dynamodb = MagicMock()

        dynamodb.transact_write_items.side_effect = ClientError(
            {
                "Error": {
                    "Code": "AccessDeniedException",
                    "Message": "Denied",
                },
            },
            "TransactWriteItems",
        )

        with pytest.raises(ClientError):
            handler_module.transition_expired_candidate(
                dynamodb,
                "test-submissions",
                validated_candidate(),
                "2026-11-14T12:00:00Z",
            )


class TestShardProcessing:
    def config(self, **overrides):
        return {
            "table_name": "test-submissions",
            "index_name": "PendingDocumentExpiryIndex",
            "shard_count": 4,
            "max_items": 100,
            **overrides,
        }

    def test_queries_all_shards(self):
        dynamodb = MagicMock()
        dynamodb.query.return_value = {
            "Items": [],
        }

        result = handler_module.cleanup_expired_documents(
            dynamodb,
            self.config(),
            NOW,
        )

        assert result == {
            "processed": 0,
            "transitioned": 0,
            "skipped": 0,
            "invalid": 0,
        }

        assert dynamodb.query.call_count == 4

    def test_query_uses_expiry_index_and_cutoff(self):
        dynamodb = MagicMock()
        dynamodb.query.return_value = {"Items": []}

        handler_module.query_shard(
            dynamodb,
            "test-submissions",
            "PendingDocumentExpiryIndex",
            0,
            4,
            100,
            NOW,
        )

        arguments = dynamodb.query.call_args.kwargs

        assert arguments["IndexName"] == ("PendingDocumentExpiryIndex")
        assert arguments["Limit"] == 100
        assert "LastEvaluatedKey" not in arguments
        assert arguments["ExpressionAttributeValues"][":cutoff_key"] == {
            "S": "2026-11-14T12:00:00Z#\uffff"
        }

    def test_invalid_candidate_is_skipped(self):
        dynamodb = MagicMock()
        dynamodb.query.return_value = {
            "Items": [{"PK": {"S": "invalid"}}],
        }

        result = handler_module.query_shard(
            dynamodb,
            "test-submissions",
            "PendingDocumentExpiryIndex",
            0,
            4,
            100,
            NOW,
        )

        assert result["processed"] == 1
        assert result["invalid"] == 1
        assert result["transitioned"] == 0

    def test_candidate_limit_is_respected(self):
        dynamodb = MagicMock()

        dynamodb.query.return_value = {
            "Items": [{"PK": {"S": "invalid"}}] * 3,
            "LastEvaluatedKey": {"PK": {"S": "next"}},
        }

        result = handler_module.query_shard(
            dynamodb,
            "test-submissions",
            "PendingDocumentExpiryIndex",
            0,
            4,
            3,
            NOW,
        )

        assert result["processed"] == 3
        assert result["invalid"] == 3
        assert dynamodb.query.call_count == 1

    def test_total_limit_is_shared_across_shards(self):
        dynamodb = MagicMock()

        dynamodb.query.return_value = {
            "Items": [{"PK": {"S": "invalid"}}] * 2,
        }

        result = handler_module.cleanup_expired_documents(
            dynamodb,
            self.config(max_items=3),
            NOW,
        )

        assert result["processed"] == 3
        assert dynamodb.query.call_count == 2

        second_query_limit = dynamodb.query.call_args_list[1].kwargs["Limit"]

        assert second_query_limit == 1

    def test_pagination_uses_last_evaluated_key(self):
        dynamodb = MagicMock()

        dynamodb.query.side_effect = [
            {
                "Items": [{"PK": {"S": "invalid"}}],
                "LastEvaluatedKey": {
                    "PK": {"S": "next"},
                    "SK": {"S": "next"},
                },
            },
            {
                "Items": [],
            },
        ]

        result = handler_module.query_shard(
            dynamodb,
            "test-submissions",
            "PendingDocumentExpiryIndex",
            0,
            4,
            100,
            NOW,
        )

        assert result["processed"] == 1
        assert dynamodb.query.call_count == 2

        second_query = dynamodb.query.call_args_list[1].kwargs

        assert second_query["ExclusiveStartKey"] == {
            "PK": {"S": "next"},
            "SK": {"S": "next"},
        }

    def test_time_budget_stops_processing(self):
        dynamodb = MagicMock()
        dynamodb.query.return_value = {"Items": []}

        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 1000

        result = handler_module.cleanup_expired_documents(
            dynamodb,
            self.config(),
            NOW,
            context,
        )

        assert result["processed"] == 0
        dynamodb.query.assert_not_called()

    def test_naive_datetime_rejected(self):
        dynamodb = MagicMock()

        with pytest.raises(ValueError):
            handler_module.cleanup_expired_documents(
                dynamodb,
                self.config(),
                datetime(2026, 11, 14, 12, 0, 0),
            )


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
