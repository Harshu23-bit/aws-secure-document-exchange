from typing import Any, Protocol

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.core.config import Settings


class SubmissionAlreadyExistsError(Exception):
    pass


class SubmissionStateConflictError(Exception):
    pass


class SubmissionActorAuthorizationError(Exception):
    pass


class SubmissionRepository(Protocol):
    def get_submission(
        self,
        tenant_id: str,
        submission_id: str,
    ) -> dict[str, Any] | None: ...

    def create_submission(
        self,
        submission: dict[str, Any],
    ) -> None: ...

    def list_submitter_submissions(
        self,
        tenant_id: str,
        user_id: str,
        limit: int,
        cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def list_reviewer_submissions(
        self,
        tenant_id: str,
        limit: int,
        cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def transition_submission(
        self,
        tenant_id: str,
        submission_id: str,
        previous_status: str,
        new_status: str,
        expected_version: int,
        updated_at: str,
        audit_event: dict[str, Any],
        owner_id: str | None = None,
        require_uploaded_documents: bool = False,
        *,
        actor_id: str,
        actor_role: str,
    ) -> None: ...


class DynamoDBSubmissionRepository:
    def __init__(self, settings: Settings):
        dynamodb = boto3.resource(
            "dynamodb",
            region_name=settings.aws_region,
            endpoint_url=settings.dynamodb_endpoint_url,
        )

        self.table = dynamodb.Table(settings.submissions_table_name)
        self.client = self.table.meta.client

        self.audit_table_name = settings.audit_events_table_name

        self.memberships_table_name = settings.memberships_table_name

    def get_submission(
        self,
        tenant_id: str,
        submission_id: str,
    ) -> dict[str, Any] | None:
        response = self.table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}",
                "SK": f"SUBMISSION#{submission_id}",
            },
            ConsistentRead=True,
        )

        return response.get("Item")

    def create_submission(
        self,
        submission: dict[str, Any],
    ) -> None:
        try:
            self.table.put_item(
                Item=submission,
                ConditionExpression=(
                    "attribute_not_exists(PK) AND attribute_not_exists(SK)"
                ),
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")

            if error_code == "ConditionalCheckFailedException":
                raise SubmissionAlreadyExistsError from exc

            raise

    def transition_submission(
        self,
        tenant_id: str,
        submission_id: str,
        previous_status: str,
        new_status: str,
        expected_version: int,
        updated_at: str,
        audit_event: dict[str, Any],
        owner_id: str | None = None,
        require_uploaded_documents: bool = False,
        *,
        actor_id: str,
        actor_role: str,
    ) -> None:
        conditions = [
            "#status = :previous_status",
            "#version = :expected_version",
        ]

        values = {
            ":previous_status": previous_status,
            ":new_status": new_status,
            ":expected_version": expected_version,
            ":next_version": expected_version + 1,
            ":updated_at": updated_at,
            ":gsi2pk": f"TENANT#{tenant_id}#STATUS#{new_status}",
        }

        if owner_id is not None:
            conditions.append("owner_id = :owner_id")
            values[":owner_id"] = owner_id

        if require_uploaded_documents:
            conditions.extend(
                [
                    "pending_document_count = :zero",
                    "uploaded_document_count >= :one",
                ]
            )
            values[":zero"] = 0
            values[":one"] = 1

        if (
            not isinstance(actor_id, str)
            or not actor_id
            or actor_role not in {"SUBMITTER", "REVIEWER"}
        ):
            raise ValueError("Invalid workflow actor")

        membership_check = {
            "ConditionCheck": {
                "TableName": self.memberships_table_name,
                "Key": {
                    "PK": f"USER#{actor_id}",
                    "SK": f"TENANT#{tenant_id}",
                },
                "ConditionExpression": (
                    "#role = :actor_role "
                    "AND #status = :active "
                    "AND user_id = :actor_id "
                    "AND tenant_id = :tenant_id"
                ),
                "ExpressionAttributeNames": {
                    "#role": "role",
                    "#status": "status",
                },
                "ExpressionAttributeValues": {
                    ":actor_role": actor_role,
                    ":active": "ACTIVE",
                    ":actor_id": actor_id,
                    ":tenant_id": tenant_id,
                },
            }
        }

        try:
            transaction_items = [
                {
                    "Update": {
                        "TableName": self.table.name,
                        "Key": {
                            "PK": f"TENANT#{tenant_id}",
                            "SK": f"SUBMISSION#{submission_id}",
                        },
                        "UpdateExpression": (
                            "SET #status = :new_status, "
                            "updated_at = :updated_at, "
                            "#version = :next_version, "
                            "GSI2PK = :gsi2pk"
                        ),
                        "ConditionExpression": " AND ".join(conditions),
                        "ExpressionAttributeNames": {
                            "#status": "status",
                            "#version": "version",
                        },
                        "ExpressionAttributeValues": values,
                    }
                },
                {
                    "Put": {
                        "TableName": self.audit_table_name,
                        "Item": audit_event,
                        "ConditionExpression": (
                            "attribute_not_exists(PK) AND attribute_not_exists(SK)"
                        ),
                    }
                },
            ]

            transaction_items.append(membership_check)

            self.client.transact_write_items(TransactItems=transaction_items)

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")

            if error_code == "TransactionCanceledException":
                reasons = exc.response.get("CancellationReasons", [])

                if (
                    len(reasons) > 2
                    and reasons[2].get("Code") == "ConditionalCheckFailed"
                ):
                    raise SubmissionActorAuthorizationError from exc

                if (
                    len(reasons) > 0
                    and reasons[0].get("Code") == "ConditionalCheckFailed"
                ):
                    raise SubmissionStateConflictError from exc

                if (
                    len(reasons) > 1
                    and reasons[1].get("Code") == "ConditionalCheckFailed"
                ):
                    raise SubmissionStateConflictError from exc

            raise

    def list_submitter_submissions(
        self,
        tenant_id: str,
        user_id: str,
        limit: int,
        cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        query_params = {
            "IndexName": "OwnerIndex",
            "KeyConditionExpression": (
                Key("GSI1PK").eq(f"TENANT#{tenant_id}#USER#{user_id}")
            ),
            "Limit": limit,
            "ScanIndexForward": False,
        }

        if cursor is not None:
            query_params["ExclusiveStartKey"] = cursor

        return self.table.query(**query_params)

    def list_reviewer_submissions(
        self,
        tenant_id: str,
        limit: int,
        cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        query_params = {
            "KeyConditionExpression": (
                Key("PK").eq(f"TENANT#{tenant_id}")
                & Key("SK").begins_with("SUBMISSION#")
            ),
            "Limit": limit,
            "ScanIndexForward": False,
        }

        if cursor is not None:
            query_params["ExclusiveStartKey"] = cursor

        return self.table.query(**query_params)
