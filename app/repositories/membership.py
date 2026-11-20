from typing import Any, Protocol

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.core.config import Settings


class MembershipActorAuthorizationError(Exception):
    """Raised when the acting administrator no longer has authority."""


class MembershipStateConflictError(Exception):
    """Raised when the target membership or audit state has changed."""


class MembershipRepository(Protocol):
    def get_membership(
        self,
        user_id: str,
        tenant_id: str,
    ) -> dict[str, Any] | None: ...

    def list_memberships(
        self,
        user_id: str,
    ) -> list[dict[str, Any]]: ...

    def list_tenant_members(
        self,
        tenant_id: str,
    ) -> list[dict[str, Any]]: ...

    def change_member_role(
        self,
        tenant_id: str,
        actor_id: str,
        target_user_id: str,
        expected_role: str,
        new_role: str,
        updated_at: str,
        audit_event: dict[str, Any],
    ) -> None: ...

    def deactivate_member(
        self,
        tenant_id: str,
        actor_id: str,
        target_user_id: str,
        expected_role: str,
        updated_at: str,
        audit_event: dict[str, Any],
    ) -> None: ...


class DynamoDBMembershipRepository:
    def __init__(self, settings: Settings):
        dynamodb = boto3.resource(
            "dynamodb",
            region_name=settings.aws_region,
            endpoint_url=settings.dynamodb_endpoint_url,
        )

        self.table = dynamodb.Table(settings.memberships_table_name)
        self.client = self.table.meta.client
        self.audit_table_name = settings.audit_events_table_name

    def get_membership(
        self,
        user_id: str,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        response = self.table.get_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"TENANT#{tenant_id}",
            },
            ConsistentRead=True,
        )

        return response.get("Item")

    def list_memberships(
        self,
        user_id: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        query_kwargs = {
            "KeyConditionExpression": Key("PK").eq(f"USER#{user_id}"),
            "ConsistentRead": True,
        }

        while True:
            response = self.table.query(**query_kwargs)
            items.extend(response.get("Items", []))

            last_evaluated_key = response.get("LastEvaluatedKey")

            if not last_evaluated_key:
                break

            query_kwargs["ExclusiveStartKey"] = last_evaluated_key

        return items

    def list_tenant_members(
        self,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        query_kwargs = {
            "IndexName": "TenantMembersIndex",
            "KeyConditionExpression": Key("GSI1PK").eq(f"TENANT#{tenant_id}"),
        }

        while True:
            response = self.table.query(**query_kwargs)
            items.extend(response.get("Items", []))

            last_evaluated_key = response.get("LastEvaluatedKey")

            if not last_evaluated_key:
                break

            query_kwargs["ExclusiveStartKey"] = last_evaluated_key

        return items

    def change_member_role(
        self,
        tenant_id: str,
        actor_id: str,
        target_user_id: str,
        expected_role: str,
        new_role: str,
        updated_at: str,
        audit_event: dict[str, Any],
    ) -> None:
        if actor_id == target_user_id:
            raise MembershipActorAuthorizationError

        if expected_role not in {"SUBMITTER", "REVIEWER"}:
            raise ValueError("Invalid expected membership role")

        if new_role not in {"SUBMITTER", "REVIEWER"}:
            raise ValueError("Invalid target membership role")

        if expected_role == new_role:
            raise ValueError("New role must differ from current role")

        self._transact_membership_change(
            tenant_id=tenant_id,
            actor_id=actor_id,
            target_user_id=target_user_id,
            expected_role=expected_role,
            updated_at=updated_at,
            audit_event=audit_event,
            update_expression=("SET #role = :new_role, updated_at = :updated_at"),
            update_values={
                ":new_role": new_role,
                ":updated_at": updated_at,
            },
        )

    def deactivate_member(
        self,
        tenant_id: str,
        actor_id: str,
        target_user_id: str,
        expected_role: str,
        updated_at: str,
        audit_event: dict[str, Any],
    ) -> None:
        if actor_id == target_user_id:
            raise MembershipActorAuthorizationError

        if expected_role not in {"SUBMITTER", "REVIEWER"}:
            raise ValueError("Invalid expected membership role")

        self._transact_membership_change(
            tenant_id=tenant_id,
            actor_id=actor_id,
            target_user_id=target_user_id,
            expected_role=expected_role,
            updated_at=updated_at,
            audit_event=audit_event,
            update_expression=("SET #status = :inactive, updated_at = :updated_at"),
            update_values={
                ":inactive": "INACTIVE",
                ":updated_at": updated_at,
            },
        )

    def _transact_membership_change(
        self,
        tenant_id: str,
        actor_id: str,
        target_user_id: str,
        expected_role: str,
        updated_at: str,
        audit_event: dict[str, Any],
        update_expression: str,
        update_values: dict[str, Any],
    ) -> None:
        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "ConditionCheck": {
                            "TableName": self.table.name,
                            "Key": {
                                "PK": f"USER#{actor_id}",
                                "SK": f"TENANT#{tenant_id}",
                            },
                            "ConditionExpression": (
                                "#role = :tenant_admin "
                                "AND #status = :active "
                                "AND user_id = :actor_id "
                                "AND tenant_id = :tenant_id"
                            ),
                            "ExpressionAttributeNames": {
                                "#role": "role",
                                "#status": "status",
                            },
                            "ExpressionAttributeValues": {
                                ":tenant_admin": "TENANT_ADMIN",
                                ":active": "ACTIVE",
                                ":actor_id": actor_id,
                                ":tenant_id": tenant_id,
                            },
                        }
                    },
                    {
                        "Update": {
                            "TableName": self.table.name,
                            "Key": {
                                "PK": f"USER#{target_user_id}",
                                "SK": f"TENANT#{tenant_id}",
                            },
                            "UpdateExpression": update_expression,
                            "ConditionExpression": (
                                "#role = :expected_role "
                                "AND #status = :active "
                                "AND user_id = :target_user_id "
                                "AND tenant_id = :tenant_id"
                            ),
                            "ExpressionAttributeNames": {
                                "#role": "role",
                                "#status": "status",
                            },
                            "ExpressionAttributeValues": {
                                ":expected_role": expected_role,
                                ":active": "ACTIVE",
                                ":target_user_id": target_user_id,
                                ":tenant_id": tenant_id,
                                **update_values,
                            },
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
            )

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")

            if error_code == "TransactionCanceledException":
                reasons = exc.response.get("CancellationReasons", [])

                if (
                    len(reasons) > 0
                    and reasons[0].get("Code") == "ConditionalCheckFailed"
                ):
                    raise MembershipActorAuthorizationError from exc

                if (
                    len(reasons) > 1
                    and reasons[1].get("Code") == "ConditionalCheckFailed"
                ):
                    raise MembershipStateConflictError from exc

                if (
                    len(reasons) > 2
                    and reasons[2].get("Code") == "ConditionalCheckFailed"
                ):
                    raise MembershipStateConflictError from exc

            raise
