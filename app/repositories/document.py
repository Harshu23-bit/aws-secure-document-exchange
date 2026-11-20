from decimal import Decimal
from typing import Any, Protocol

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.schemas.document import DocumentStatus


class DocumentAlreadyExistsError(Exception):
    pass


class DocumentNotFoundError(Exception):
    pass


class DocumentStateConflictError(Exception):
    pass


class DocumentQuotaExceededError(Exception):
    pass


class DocumentRepository(Protocol):
    def create_document(self, document: dict) -> None: ...

    def get_document(
        self,
        tenant_id: str,
        submission_id: str,
        document_id: str,
    ) -> dict | None: ...

    def mark_document_uploaded(
        self,
        tenant_id: str,
        submission_id: str,
        document_id: str,
        uploaded_at: str,
        version_id: str,
        owner_id: str,
        size_bytes: int,
        pending_gsi3_pk: str,
        pending_gsi3_sk: str,
        uploaded_gsi3_pk: str,
        uploaded_gsi3_sk: str,
        upload_url_expires_at: str,
        upload_hygiene_after: str,
    ) -> None: ...

    def list_documents(
        self,
        tenant_id: str,
        submission_id: str,
        limit: int,
        cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class DynamoDBDocumentRepository:
    def __init__(self, settings=None):
        settings = settings or get_settings()

        dynamodb = boto3.resource(
            "dynamodb",
            region_name=settings.aws_region,
            endpoint_url=settings.dynamodb_endpoint_url,
        )

        self.table = dynamodb.Table(settings.submissions_table_name)
        self.client = self.table.meta.client
        self.max_documents_per_submission = getattr(
            settings, "max_documents_per_submission", 10
        )
        self.max_submission_bytes = getattr(
            settings, "max_submission_bytes", 50 * 1024 * 1024
        )

    def create_document(self, document: dict) -> None:
        tenant_id = document["tenant_id"]
        submission_id = document["submission_id"]
        size_bytes = document["size_bytes"]

        if type(size_bytes) is not int or size_bytes <= 0:
            raise ValueError("Document size_bytes must be a positive integer")

        submission_key = {
            "PK": f"TENANT#{tenant_id}",
            "SK": f"SUBMISSION#{submission_id}",
        }

        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.table.name,
                            "Key": submission_key,
                            "UpdateExpression": (
                                "ADD pending_document_count :one, "
                                "pending_document_bytes :size, "
                                "total_document_count :one, "
                                "total_document_bytes :size"
                            ),
                            "ConditionExpression": (
                                "#status = :draft "
                                "AND owner_id = :owner "
                                "AND total_document_count < :max_documents "
                                "AND total_document_bytes <= :max_bytes_before"
                            ),
                            "ExpressionAttributeNames": {
                                "#status": "status",
                            },
                            "ExpressionAttributeValues": {
                                ":one": 1,
                                ":size": size_bytes,
                                ":draft": "DRAFT",
                                ":owner": document["owner_id"],
                                ":max_documents": self.max_documents_per_submission,
                                ":max_bytes_before": (
                                    self.max_submission_bytes - size_bytes
                                ),
                            },
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table.name,
                            "Item": document,
                            "ConditionExpression": (
                                "attribute_not_exists(PK) AND attribute_not_exists(SK)"
                            ),
                        }
                    },
                ]
            )

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")

            if error_code == "TransactionCanceledException":
                reasons = exc.response.get("CancellationReasons", [])

                if (
                    len(reasons) > 1
                    and reasons[1].get("Code") == "ConditionalCheckFailed"
                ):
                    raise DocumentAlreadyExistsError from exc

                if (
                    len(reasons) > 0
                    and reasons[0].get("Code") == "ConditionalCheckFailed"
                ):
                    response = self.table.get_item(
                        Key=submission_key,
                        ConsistentRead=True,
                    )
                    submission = response.get("Item")

                    if (
                        not submission
                        or submission.get("status") != "DRAFT"
                        or submission.get("owner_id") != document["owner_id"]
                    ):
                        raise DocumentStateConflictError from exc

                    count = submission.get("total_document_count")
                    total_bytes = submission.get("total_document_bytes")

                    # Missing or malformed counters fail closed. All newly
                    # created submissions initialize these attributes.
                    def is_non_negative_integer(value: object) -> bool:
                        if type(value) is int:
                            return value >= 0

                        if isinstance(value, Decimal):
                            return (
                                value.is_finite()
                                and value == value.to_integral_value()
                                and value >= 0
                            )

                        return False

                    if not is_non_negative_integer(
                        count
                    ) or not is_non_negative_integer(total_bytes):
                        raise DocumentStateConflictError from exc

                    count = int(count)
                    total_bytes = int(total_bytes)

                    if (
                        count >= self.max_documents_per_submission
                        or size_bytes > self.max_submission_bytes - total_bytes
                    ):
                        raise DocumentQuotaExceededError from exc

                    raise DocumentStateConflictError from exc

            raise

    def get_document(
        self,
        tenant_id: str,
        submission_id: str,
        document_id: str,
    ) -> dict | None:
        response = self.table.get_item(
            Key={
                "PK": f"TENANT#{tenant_id}#SUBMISSION#{submission_id}",
                "SK": f"DOCUMENT#{document_id}",
            },
            ConsistentRead=True,
        )
        return response.get("Item")

    def mark_document_uploaded(
        self,
        tenant_id: str,
        submission_id: str,
        document_id: str,
        uploaded_at: str,
        version_id: str,
        owner_id: str,
        size_bytes: int,
        pending_gsi3_pk: str,
        pending_gsi3_sk: str,
        uploaded_gsi3_pk: str,
        uploaded_gsi3_sk: str,
        upload_url_expires_at: str,
        upload_hygiene_after: str,
    ) -> None:
        if (
            not isinstance(version_id, str)
            or not version_id.strip()
            or version_id == "null"
        ):
            raise ValueError("A valid S3 object version is required")

        if type(size_bytes) is not int or size_bytes <= 0:
            raise ValueError("Document size_bytes must be a positive integer")

        submission_key = {
            "PK": f"TENANT#{tenant_id}",
            "SK": f"SUBMISSION#{submission_id}",
        }
        document_key = {
            "PK": f"TENANT#{tenant_id}#SUBMISSION#{submission_id}",
            "SK": f"DOCUMENT#{document_id}",
        }

        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.table.name,
                            "Key": submission_key,
                            "UpdateExpression": (
                                "SET pending_document_count = "
                                "pending_document_count - :one, "
                                "pending_document_bytes = "
                                "pending_document_bytes - :size, "
                                "uploaded_document_count = "
                                "uploaded_document_count + :one, "
                                "uploaded_document_bytes = "
                                "uploaded_document_bytes + :size"
                            ),
                            "ConditionExpression": (
                                "#status = :draft "
                                "AND owner_id = :owner "
                                "AND pending_document_count > :zero "
                                "AND pending_document_bytes >= :size"
                            ),
                            "ExpressionAttributeNames": {
                                "#status": "status",
                            },
                            "ExpressionAttributeValues": {
                                ":one": 1,
                                ":zero": 0,
                                ":size": size_bytes,
                                ":draft": "DRAFT",
                                ":owner": owner_id,
                            },
                        }
                    },
                    {
                        "Update": {
                            "TableName": self.table.name,
                            "Key": document_key,
                            "UpdateExpression": (
                                "SET #status = :uploaded, "
                                "uploaded_at = :uploaded_at, "
                                "version_id = :version_id, "
                                "GSI3PK = :uploaded_gsi3_pk, "
                                "GSI3SK = :uploaded_gsi3_sk"
                            ),
                            "ConditionExpression": (
                                "#status = :pending "
                                "AND owner_id = :owner "
                                "AND tenant_id = :tenant "
                                "AND submission_id = :submission "
                                "AND document_id = :document "
                                "AND size_bytes = :size "
                                "AND attribute_exists(expires_at) "
                                "AND expires_at > :uploaded_at "
                                "AND GSI3PK = :pending_gsi3_pk "
                                "AND GSI3SK = :pending_gsi3_sk "
                                "AND upload_url_expires_at = :upload_url_expires_at "
                                "AND upload_hygiene_after = :upload_hygiene_after"
                            ),
                            "ExpressionAttributeNames": {
                                "#status": "status",
                            },
                            "ExpressionAttributeValues": {
                                ":uploaded": DocumentStatus.UPLOADED.value,
                                ":pending": DocumentStatus.PENDING_UPLOAD.value,
                                ":uploaded_at": uploaded_at,
                                ":version_id": version_id,
                                ":owner": owner_id,
                                ":tenant": tenant_id,
                                ":submission": submission_id,
                                ":document": document_id,
                                ":size": size_bytes,
                                ":pending_gsi3_pk": pending_gsi3_pk,
                                ":pending_gsi3_sk": pending_gsi3_sk,
                                ":uploaded_gsi3_pk": uploaded_gsi3_pk,
                                ":uploaded_gsi3_sk": uploaded_gsi3_sk,
                                ":upload_url_expires_at": upload_url_expires_at,
                                ":upload_hygiene_after": upload_hygiene_after,
                            },
                        }
                    },
                ]
            )

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")

            if error_code == "TransactionCanceledException":
                reasons = exc.response.get("CancellationReasons", [])

                document_condition_failed = (
                    len(reasons) > 1
                    and reasons[1].get("Code") == "ConditionalCheckFailed"
                )

                if document_condition_failed:
                    response = self.table.get_item(
                        Key=document_key,
                        ConsistentRead=True,
                    )
                    if "Item" not in response:
                        raise DocumentNotFoundError from exc
                    raise DocumentStateConflictError from exc

                if (
                    len(reasons) > 0
                    and reasons[0].get("Code") == "ConditionalCheckFailed"
                ):
                    raise DocumentStateConflictError from exc

                raise DocumentStateConflictError from exc

            raise

    def list_documents(
        self,
        tenant_id: str,
        submission_id: str,
        limit: int,
        cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        query_params = {
            "KeyConditionExpression": (
                Key("PK").eq(f"TENANT#{tenant_id}#SUBMISSION#{submission_id}")
                & Key("SK").begins_with("DOCUMENT#")
            ),
            "Limit": limit,
            "ScanIndexForward": False,
            "ConsistentRead": True,
        }

        if cursor is not None:
            query_params["ExclusiveStartKey"] = cursor

        return self.table.query(**query_params)
