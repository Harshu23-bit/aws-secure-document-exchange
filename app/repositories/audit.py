from typing import Any, Protocol

import boto3
from boto3.dynamodb.conditions import Key

from app.core.config import Settings


class AuditRepository(Protocol):
    def list_submission_events(
        self,
        tenant_id: str,
        submission_id: str,
        limit: int,
        cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def list_tenant_events(
        self,
        tenant_id: str,
        limit: int,
        cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class DynamoDBAuditRepository:
    def __init__(self, settings: Settings):
        dynamodb = boto3.resource(
            "dynamodb",
            region_name=settings.aws_region,
            endpoint_url=settings.dynamodb_endpoint_url,
        )

        self.table = dynamodb.Table(settings.audit_events_table_name)

    def list_submission_events(
        self,
        tenant_id: str,
        submission_id: str,
        limit: int,
        cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        query_params = {
            "KeyConditionExpression": (
                Key("PK").eq(f"TENANT#{tenant_id}#SUBMISSION#{submission_id}")
                & Key("SK").begins_with("EVENT#")
            ),
            "Limit": limit,
            "ScanIndexForward": False,
        }

        if cursor is not None:
            query_params["ExclusiveStartKey"] = cursor

        return self.table.query(**query_params)

    def list_tenant_events(
        self,
        tenant_id: str,
        limit: int,
        cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        query_params = {
            "IndexName": "TenantAuditIndex",
            "KeyConditionExpression": (
                Key("GSI1PK").eq(f"TENANT#{tenant_id}")
                & Key("GSI1SK").begins_with("EVENT#")
            ),
            "Limit": limit,
            "ScanIndexForward": False,
        }

        if cursor is not None:
            query_params["ExclusiveStartKey"] = cursor

        return self.table.query(**query_params)
