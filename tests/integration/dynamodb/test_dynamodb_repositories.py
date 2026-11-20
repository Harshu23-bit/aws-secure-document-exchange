from datetime import UTC, datetime, timedelta

import pytest

from app.repositories.document import (
    DocumentAlreadyExistsError,
    DocumentNotFoundError,
    DocumentQuotaExceededError,
    DocumentStateConflictError,
)
from app.repositories.membership import (
    MembershipActorAuthorizationError,
    MembershipStateConflictError,
)
from app.repositories.submission import (
    SubmissionActorAuthorizationError,
    SubmissionAlreadyExistsError,
    SubmissionStateConflictError,
)
from app.services.documents import get_document_expiry_shard


def create_document(
    tenant_id="tenant-a",
    submission_id="submission-001",
    document_id="document-001",
    owner_id="user-a",
    size_bytes=1024,
):
    now = datetime.now(UTC).replace(microsecond=0)

    expires_at = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    upload_url_expires_at = (now + timedelta(seconds=300)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    upload_hygiene_after = (
        now + timedelta(seconds=300) + timedelta(hours=24)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    shard = get_document_expiry_shard(document_id)

    return {
        "PK": (f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"),
        "SK": f"DOCUMENT#{document_id}",
        "entity_type": "DOCUMENT",
        "tenant_id": tenant_id,
        "submission_id": submission_id,
        "document_id": document_id,
        "owner_id": owner_id,
        "file_name": "assessment.pdf",
        "content_type": "application/pdf",
        "size_bytes": size_bytes,
        "status": "PENDING_UPLOAD",
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires_at,
        "GSI3PK": f"PENDING_UPLOAD#{shard:02d}",
        "GSI3SK": f"{expires_at}#{document_id}",
        "upload_url_expires_at": upload_url_expires_at,
        "upload_hygiene_after": upload_hygiene_after,
    }


def create_audit_event(
    tenant_id="tenant-a",
    submission_id="submission-001",
    event_id="event-001",
    timestamp="2026-11-12T10:01:00Z",
):
    return {
        "PK": f"TENANT#{tenant_id}#SUBMISSION#{submission_id}",
        "SK": f"EVENT#{timestamp}#{event_id}",
        "GSI1PK": f"TENANT#{tenant_id}",
        "GSI1SK": f"EVENT#{timestamp}#{event_id}",
        "entity_type": "AUDIT_EVENT",
        "tenant_id": tenant_id,
        "submission_id": submission_id,
        "event_id": event_id,
        "action": "SUBMISSION_TRANSITION",
        "actor_id": "user-a",
        "created_at": timestamp,
    }


def test_submission_create_and_retrieve(
    dynamodb_repositories,
    submission_factory,
):
    repository = dynamodb_repositories["submissions"]

    submission = submission_factory()

    repository.create_submission(submission)

    result = repository.get_submission(
        "tenant-a",
        "submission-001",
    )

    assert result is not None
    assert result["submission_id"] == "submission-001"
    assert result["owner_id"] == "user-a"
    assert result["status"] == "DRAFT"


def test_duplicate_submission_is_rejected(
    dynamodb_repositories,
    submission_factory,
):
    repository = dynamodb_repositories["submissions"]

    submission = submission_factory()

    repository.create_submission(submission)

    with pytest.raises(SubmissionAlreadyExistsError):
        repository.create_submission(submission)


def test_submission_partition_isolation(
    dynamodb_repositories,
    submission_factory,
):
    repository = dynamodb_repositories["submissions"]

    repository.create_submission(
        submission_factory(
            tenant_id="tenant-a",
            submission_id="submission-001",
        )
    )

    assert (
        repository.get_submission(
            "tenant-b",
            "submission-001",
        )
        is None
    )


def test_owner_index_returns_only_owner_submissions(
    dynamodb_repositories,
    submission_factory,
):
    repository = dynamodb_repositories["submissions"]

    repository.create_submission(
        submission_factory(
            submission_id="submission-001",
            owner_id="user-a",
        )
    )

    repository.create_submission(
        submission_factory(
            submission_id="submission-002",
            owner_id="user-b",
        )
    )

    result = repository.list_submitter_submissions(
        tenant_id="tenant-a",
        user_id="user-a",
        limit=10,
    )

    assert len(result["Items"]) == 1
    assert result["Items"][0]["owner_id"] == "user-a"


def test_reviewer_query_is_tenant_scoped(
    dynamodb_repositories,
    submission_factory,
):
    repository = dynamodb_repositories["submissions"]

    repository.create_submission(
        submission_factory(
            tenant_id="tenant-a",
            submission_id="submission-001",
        )
    )

    repository.create_submission(
        submission_factory(
            tenant_id="tenant-b",
            submission_id="submission-002",
        )
    )

    result = repository.list_reviewer_submissions(
        tenant_id="tenant-a",
        limit=10,
    )

    assert len(result["Items"]) == 1
    assert result["Items"][0]["tenant_id"] == "tenant-a"


def test_membership_lookup_and_tenant_isolation(
    dynamodb_repositories,
    dynamodb_local,
):
    repository = dynamodb_repositories["memberships"]

    table = dynamodb_local.Table("cloudsec-test-memberships")

    table.put_item(
        Item={
            "PK": "USER#user-a",
            "SK": "TENANT#tenant-a",
            "user_id": "user-a",
            "tenant_id": "tenant-a",
            "role": "SUBMITTER",
            "status": "ACTIVE",
            "GSI1PK": "TENANT#tenant-a",
            "GSI1SK": "USER#user-a",
        }
    )

    result = repository.get_membership(
        "user-a",
        "tenant-a",
    )

    assert result is not None
    assert result["role"] == "SUBMITTER"

    assert (
        repository.get_membership(
            "user-a",
            "tenant-b",
        )
        is None
    )


def test_list_memberships_returns_all_tenants_for_user(
    dynamodb_repositories,
    dynamodb_local,
):
    repository = dynamodb_repositories["memberships"]
    table = dynamodb_local.Table("cloudsec-test-memberships")

    memberships = [
        {
            "PK": "USER#discovery-user",
            "SK": "TENANT#tenant-alpha",
            "user_id": "discovery-user",
            "tenant_id": "tenant-alpha",
            "role": "SUBMITTER",
            "status": "ACTIVE",
            "GSI1PK": "TENANT#tenant-alpha",
            "GSI1SK": "USER#discovery-user",
        },
        {
            "PK": "USER#discovery-user",
            "SK": "TENANT#tenant-beta",
            "user_id": "discovery-user",
            "tenant_id": "tenant-beta",
            "role": "REVIEWER",
            "status": "ACTIVE",
            "GSI1PK": "TENANT#tenant-beta",
            "GSI1SK": "USER#discovery-user",
        },
        {
            "PK": "USER#another-discovery-user",
            "SK": "TENANT#tenant-gamma",
            "user_id": "another-discovery-user",
            "tenant_id": "tenant-gamma",
            "role": "SUBMITTER",
            "status": "ACTIVE",
            "GSI1PK": "TENANT#tenant-gamma",
            "GSI1SK": "USER#another-discovery-user",
        },
    ]

    for membership in memberships:
        table.put_item(Item=membership)

    result = repository.list_memberships("discovery-user")

    assert len(result) == 2
    assert {item["tenant_id"] for item in result} == {"tenant-alpha", "tenant-beta"}

    assert all(item["user_id"] == "discovery-user" for item in result)


def test_list_memberships_returns_empty_list_for_unknown_user(
    dynamodb_repositories,
):
    repository = dynamodb_repositories["memberships"]

    result = repository.list_memberships("user-with-no-memberships")

    assert result == []


def test_list_memberships_handles_pagination(
    dynamodb_repositories,
    monkeypatch,
):
    repository = dynamodb_repositories["memberships"]

    first_page = {
        "Items": [
            {
                "user_id": "pagination-user",
                "tenant_id": "tenant-alpha",
                "role": "SUBMITTER",
                "status": "ACTIVE",
            }
        ],
        "LastEvaluatedKey": {
            "PK": "USER#pagination-user",
            "SK": "TENANT#tenant-alpha",
        },
    }

    second_page = {
        "Items": [
            {
                "user_id": "pagination-user",
                "tenant_id": "tenant-beta",
                "role": "REVIEWER",
                "status": "ACTIVE",
            }
        ]
    }

    responses = [first_page, second_page]
    calls = []

    def fake_query(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr(
        repository.table,
        "query",
        fake_query,
    )

    result = repository.list_memberships("pagination-user")

    assert len(result) == 2
    assert [item["tenant_id"] for item in result] == ["tenant-alpha", "tenant-beta"]

    assert len(calls) == 2
    assert calls[0]["ConsistentRead"] is True
    assert "ExclusiveStartKey" not in calls[0]

    assert calls[1]["ExclusiveStartKey"] == {
        "PK": "USER#pagination-user",
        "SK": "TENANT#tenant-alpha",
    }
    assert calls[1]["ConsistentRead"] is True


def test_list_tenant_members_returns_only_members_of_requested_tenant(
    dynamodb_repositories,
    dynamodb_local,
):
    repository = dynamodb_repositories["memberships"]
    table = dynamodb_local.Table("cloudsec-test-memberships")

    memberships = [
        {
            "PK": "USER#user-a",
            "SK": "TENANT#tenant-alpha",
            "user_id": "user-a",
            "tenant_id": "tenant-alpha",
            "role": "TENANT_ADMIN",
            "status": "ACTIVE",
            "created_at": "2026-11-17T10:00:00Z",
            "GSI1PK": "TENANT#tenant-alpha",
            "GSI1SK": "USER#user-a",
        },
        {
            "PK": "USER#user-b",
            "SK": "TENANT#tenant-alpha",
            "user_id": "user-b",
            "tenant_id": "tenant-alpha",
            "role": "REVIEWER",
            "status": "ACTIVE",
            "created_at": "2026-11-17T10:05:00Z",
            "GSI1PK": "TENANT#tenant-alpha",
            "GSI1SK": "USER#user-b",
        },
        {
            "PK": "USER#user-c",
            "SK": "TENANT#tenant-alpha",
            "user_id": "user-c",
            "tenant_id": "tenant-alpha",
            "role": "SUBMITTER",
            "status": "INACTIVE",
            "created_at": "2026-11-17T10:10:00Z",
            "GSI1PK": "TENANT#tenant-alpha",
            "GSI1SK": "USER#user-c",
        },
        {
            "PK": "USER#user-d",
            "SK": "TENANT#tenant-beta",
            "user_id": "user-d",
            "tenant_id": "tenant-beta",
            "role": "SUBMITTER",
            "status": "ACTIVE",
            "created_at": "2026-11-17T10:15:00Z",
            "GSI1PK": "TENANT#tenant-beta",
            "GSI1SK": "USER#user-d",
        },
    ]

    for membership in memberships:
        table.put_item(Item=membership)

    result = repository.list_tenant_members("tenant-alpha")

    assert len(result) == 3

    assert {item["user_id"] for item in result} == {"user-a", "user-b", "user-c"}

    assert all(item["tenant_id"] == "tenant-alpha" for item in result)

    assert {item["status"] for item in result} == {"ACTIVE", "INACTIVE"}

    assert all("role" in item and "created_at" in item for item in result)


def test_list_tenant_members_handles_pagination(
    dynamodb_repositories,
    monkeypatch,
):
    repository = dynamodb_repositories["memberships"]

    first_page = {
        "Items": [
            {
                "user_id": "user-a",
                "tenant_id": "tenant-alpha",
                "role": "TENANT_ADMIN",
                "status": "ACTIVE",
            }
        ],
        "LastEvaluatedKey": {
            "PK": "USER#user-a",
            "SK": "TENANT#tenant-alpha",
            "GSI1PK": "TENANT#tenant-alpha",
            "GSI1SK": "USER#user-a",
        },
    }

    second_page = {
        "Items": [
            {
                "user_id": "user-b",
                "tenant_id": "tenant-alpha",
                "role": "REVIEWER",
                "status": "ACTIVE",
            }
        ]
    }

    responses = [first_page, second_page]
    calls = []

    def fake_query(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr(
        repository.table,
        "query",
        fake_query,
    )

    result = repository.list_tenant_members("tenant-alpha")

    assert len(result) == 2

    assert [item["user_id"] for item in result] == ["user-a", "user-b"]

    assert len(calls) == 2

    for call in calls:
        assert call["IndexName"] == "TenantMembersIndex"
        assert "ConsistentRead" not in call

    assert "ExclusiveStartKey" not in calls[0]

    assert calls[1]["ExclusiveStartKey"] == {
        "PK": "USER#user-a",
        "SK": "TENANT#tenant-alpha",
        "GSI1PK": "TENANT#tenant-alpha",
        "GSI1SK": "USER#user-a",
    }


def test_document_creation_updates_pending_counter_atomically(
    dynamodb_repositories,
    submission_factory,
):
    submissions = dynamodb_repositories["submissions"]
    documents = dynamodb_repositories["documents"]

    submissions.create_submission(submission_factory())

    document = create_document()

    documents.create_document(document)

    submission = submissions.get_submission(
        "tenant-a",
        "submission-001",
    )

    stored_document = documents.get_document(
        "tenant-a",
        "submission-001",
        "document-001",
    )

    assert submission["pending_document_count"] == 1
    assert submission["pending_document_bytes"] == 1024
    assert submission["total_document_count"] == 1
    assert submission["total_document_bytes"] == 1024
    assert stored_document is not None
    assert stored_document["status"] == "PENDING_UPLOAD"


def test_duplicate_document_creation_rolls_back_counter(
    dynamodb_repositories,
    submission_factory,
):
    submissions = dynamodb_repositories["submissions"]
    documents = dynamodb_repositories["documents"]

    submissions.create_submission(submission_factory())

    document = create_document()

    documents.create_document(document)

    with pytest.raises(DocumentAlreadyExistsError):
        documents.create_document(document)

    submission = submissions.get_submission(
        "tenant-a",
        "submission-001",
    )

    assert submission["pending_document_count"] == 1


def test_document_creation_rejects_wrong_owner(
    dynamodb_repositories,
    submission_factory,
):
    submissions = dynamodb_repositories["submissions"]
    documents = dynamodb_repositories["documents"]

    submissions.create_submission(submission_factory())

    document = create_document(owner_id="user-b")

    with pytest.raises(DocumentStateConflictError):
        documents.create_document(document)

    submission = submissions.get_submission(
        "tenant-a",
        "submission-001",
    )

    assert submission["pending_document_count"] == 0
    assert (
        documents.get_document(
            "tenant-a",
            "submission-001",
            "document-001",
        )
        is None
    )


def test_document_upload_updates_document_and_counters_atomically(
    dynamodb_repositories,
    submission_factory,
):
    submissions = dynamodb_repositories["submissions"]
    documents = dynamodb_repositories["documents"]

    submissions.create_submission(submission_factory())

    document = create_document()
    documents.create_document(document)

    shard = document["GSI3PK"].split("#")[-1]

    documents.mark_document_uploaded(
        tenant_id="tenant-a",
        submission_id="submission-001",
        document_id="document-001",
        uploaded_at="2026-11-12T10:05:00Z",
        version_id="s3-version-123",
        owner_id="user-a",
        size_bytes=1024,
        pending_gsi3_pk=document["GSI3PK"],
        pending_gsi3_sk=document["GSI3SK"],
        uploaded_gsi3_pk=f"UPLOADED#{shard}",
        uploaded_gsi3_sk=(f"{document['upload_hygiene_after']}#document-001"),
        upload_url_expires_at=document["upload_url_expires_at"],
        upload_hygiene_after=document["upload_hygiene_after"],
    )

    submission = submissions.get_submission(
        "tenant-a",
        "submission-001",
    )

    document = documents.get_document(
        "tenant-a",
        "submission-001",
        "document-001",
    )

    assert submission["pending_document_count"] == 0
    assert submission["pending_document_bytes"] == 0
    assert submission["uploaded_document_count"] == 1
    assert submission["uploaded_document_bytes"] == 1024
    assert submission["total_document_count"] == 1
    assert submission["total_document_bytes"] == 1024
    assert document["status"] == "UPLOADED"
    assert document["version_id"] == "s3-version-123"


def test_failed_document_upload_rolls_back_submission_counters(
    dynamodb_repositories,
    submission_factory,
):
    submissions = dynamodb_repositories["submissions"]
    documents = dynamodb_repositories["documents"]

    submissions.create_submission(submission_factory())

    with pytest.raises(DocumentNotFoundError):
        missing_document = create_document(document_id="missing-document")
        shard = missing_document["GSI3PK"].split("#")[-1]

        documents.mark_document_uploaded(
            tenant_id="tenant-a",
            submission_id="submission-001",
            document_id="missing-document",
            uploaded_at="2026-11-12T10:05:00Z",
            version_id="s3-version-123",
            owner_id="user-a",
            size_bytes=1024,
            pending_gsi3_pk=missing_document["GSI3PK"],
            pending_gsi3_sk=missing_document["GSI3SK"],
            uploaded_gsi3_pk=f"UPLOADED#{shard}",
            uploaded_gsi3_sk=(
                f"{missing_document['upload_hygiene_after']}#missing-document"
            ),
            upload_url_expires_at=(missing_document["upload_url_expires_at"]),
            upload_hygiene_after=(missing_document["upload_hygiene_after"]),
        )

    submission = submissions.get_submission(
        "tenant-a",
        "submission-001",
    )

    assert submission["pending_document_count"] == 0
    assert submission["uploaded_document_count"] == 0


def test_invalid_s3_version_is_rejected(
    dynamodb_repositories,
):
    documents = dynamodb_repositories["documents"]

    document = create_document()
    shard = document["GSI3PK"].split("#")[-1]

    with pytest.raises(
        ValueError,
        match="A valid S3 object version is required",
    ):
        documents.mark_document_uploaded(
            tenant_id="tenant-a",
            submission_id="submission-001",
            document_id="document-001",
            uploaded_at="2026-11-12T10:05:00Z",
            version_id="null",
            owner_id="user-a",
            size_bytes=1024,
            pending_gsi3_pk=document["GSI3PK"],
            pending_gsi3_sk=document["GSI3SK"],
            uploaded_gsi3_pk=f"UPLOADED#{shard}",
            uploaded_gsi3_sk=(f"{document['upload_hygiene_after']}#document-001"),
            upload_url_expires_at=document["upload_url_expires_at"],
            upload_hygiene_after=document["upload_hygiene_after"],
        )


def test_submission_transition_and_audit_write_are_atomic(
    dynamodb_repositories,
    submission_factory,
):
    submissions = dynamodb_repositories["submissions"]

    submissions.create_submission(
        submission_factory(
            uploaded_document_count=1,
        )
    )

    put_membership(
        dynamodb_repositories,
        user_id="user-a",
        role="SUBMITTER",
        status="ACTIVE",
    )

    event = create_audit_event()

    submissions.transition_submission(
        tenant_id="tenant-a",
        submission_id="submission-001",
        previous_status="DRAFT",
        new_status="SUBMITTED",
        expected_version=1,
        updated_at="2026-11-12T10:10:00Z",
        audit_event=event,
        owner_id="user-a",
        require_uploaded_documents=True,
        actor_id="user-a",
        actor_role="SUBMITTER",
    )

    submission = submissions.get_submission(
        "tenant-a",
        "submission-001",
    )

    assert submission["status"] == "SUBMITTED"
    assert submission["version"] == 2
    assert submission["GSI2PK"] == ("TENANT#tenant-a#STATUS#SUBMITTED")

    audit = dynamodb_repositories["audit"]

    events = audit.list_submission_events(
        tenant_id="tenant-a",
        submission_id="submission-001",
        limit=10,
    )

    assert len(events["Items"]) == 1
    assert events["Items"][0]["event_id"] == "event-001"


def test_stale_submission_version_is_rejected(
    dynamodb_repositories,
    submission_factory,
):
    submissions = dynamodb_repositories["submissions"]

    submissions.create_submission(
        submission_factory(
            uploaded_document_count=1,
        )
    )

    put_membership(
        dynamodb_repositories,
        user_id="user-a",
        role="SUBMITTER",
        status="ACTIVE",
    )

    with pytest.raises(SubmissionStateConflictError):
        submissions.transition_submission(
            tenant_id="tenant-a",
            submission_id="submission-001",
            previous_status="DRAFT",
            new_status="SUBMITTED",
            expected_version=99,
            updated_at="2026-11-12T10:10:00Z",
            audit_event=create_audit_event(),
            owner_id="user-a",
            require_uploaded_documents=True,
            actor_id="user-a",
            actor_role="SUBMITTER",
        )

    submission = submissions.get_submission(
        "tenant-a",
        "submission-001",
    )

    assert submission["status"] == "DRAFT"
    assert submission["version"] == 1

    events = dynamodb_repositories["audit"].list_submission_events(
        tenant_id="tenant-a",
        submission_id="submission-001",
        limit=10,
    )

    assert events["Items"] == []


def test_duplicate_audit_event_rolls_back_status_transition(
    dynamodb_repositories,
    submission_factory,
):
    submissions = dynamodb_repositories["submissions"]
    audit = dynamodb_repositories["audit"]

    submissions.create_submission(
        submission_factory(
            uploaded_document_count=1,
        )
    )

    put_membership(
        dynamodb_repositories,
        user_id="user-a",
        role="SUBMITTER",
        status="ACTIVE",
    )

    event = create_audit_event()

    submissions.transition_submission(
        tenant_id="tenant-a",
        submission_id="submission-001",
        previous_status="DRAFT",
        new_status="SUBMITTED",
        expected_version=1,
        updated_at="2026-11-12T10:10:00Z",
        audit_event=event,
        owner_id="user-a",
        require_uploaded_documents=True,
        actor_id="user-a",
        actor_role="SUBMITTER",
    )

    submissions.create_submission(
        submission_factory(
            submission_id="submission-002",
            uploaded_document_count=1,
        )
    )

    with pytest.raises(SubmissionStateConflictError):
        submissions.transition_submission(
            tenant_id="tenant-a",
            submission_id="submission-002",
            previous_status="DRAFT",
            new_status="SUBMITTED",
            expected_version=1,
            updated_at="2026-11-12T10:11:00Z",
            audit_event=event,
            owner_id="user-a",
            require_uploaded_documents=True,
            actor_id="user-a",
            actor_role="SUBMITTER",
        )

    second_submission = submissions.get_submission(
        "tenant-a",
        "submission-002",
    )

    assert second_submission["status"] == "DRAFT"
    assert second_submission["version"] == 1

    events = audit.list_submission_events(
        tenant_id="tenant-a",
        submission_id="submission-001",
        limit=10,
    )

    assert len(events["Items"]) == 1


def test_tenant_audit_query_is_tenant_scoped(
    dynamodb_repositories,
    dynamodb_local,
):
    audit = dynamodb_repositories["audit"]
    table = dynamodb_local.Table("cloudsec-test-audit-events")

    table.put_item(
        Item=create_audit_event(
            tenant_id="tenant-a",
            submission_id="submission-001",
            event_id="event-a1",
            timestamp="2026-11-12T10:01:00Z",
        )
    )

    table.put_item(
        Item=create_audit_event(
            tenant_id="tenant-a",
            submission_id="submission-002",
            event_id="event-a2",
            timestamp="2026-11-12T10:02:00Z",
        )
    )

    table.put_item(
        Item=create_audit_event(
            tenant_id="tenant-b",
            submission_id="submission-003",
            event_id="event-b1",
            timestamp="2026-11-12T10:03:00Z",
        )
    )

    result = audit.list_tenant_events(
        tenant_id="tenant-a",
        limit=10,
    )

    assert len(result["Items"]) == 2
    assert {event["event_id"] for event in result["Items"]} == {
        "event-a1",
        "event-a2",
    }
    assert all(event["tenant_id"] == "tenant-a" for event in result["Items"])


def test_tenant_audit_query_pagination(
    dynamodb_repositories,
    dynamodb_local,
):
    audit = dynamodb_repositories["audit"]
    table = dynamodb_local.Table("cloudsec-test-audit-events")

    for index in range(1, 5):
        timestamp = f"2026-11-12T10:0{index}:00Z"

        table.put_item(
            Item=create_audit_event(
                submission_id=f"submission-{index:03d}",
                event_id=f"event-{index}",
                timestamp=timestamp,
            )
        )

    first_page = audit.list_tenant_events(
        tenant_id="tenant-a",
        limit=2,
    )

    assert len(first_page["Items"]) == 2
    assert "LastEvaluatedKey" in first_page

    second_page = audit.list_tenant_events(
        tenant_id="tenant-a",
        limit=2,
        cursor=first_page["LastEvaluatedKey"],
    )

    assert len(second_page["Items"]) == 2

    first_ids = {event["event_id"] for event in first_page["Items"]}
    second_ids = {event["event_id"] for event in second_page["Items"]}

    assert first_ids.isdisjoint(second_ids)

    all_events = first_page["Items"] + second_page["Items"]

    assert {event["event_id"] for event in all_events} == {
        "event-1",
        "event-2",
        "event-3",
        "event-4",
    }

    assert [event["event_id"] for event in all_events] == [
        "event-4",
        "event-3",
        "event-2",
        "event-1",
    ]


def test_audit_query_pagination(
    dynamodb_repositories,
    dynamodb_local,
):
    audit = dynamodb_repositories["audit"]

    table = dynamodb_local.Table("cloudsec-test-audit-events")

    for index in range(1, 5):
        timestamp = f"2026-11-12T10:0{index}:00Z"

        table.put_item(
            Item=create_audit_event(
                event_id=f"event-{index}",
                timestamp=timestamp,
            )
        )

    first_page = audit.list_submission_events(
        tenant_id="tenant-a",
        submission_id="submission-001",
        limit=2,
    )

    assert len(first_page["Items"]) == 2
    assert "LastEvaluatedKey" in first_page

    second_page = audit.list_submission_events(
        tenant_id="tenant-a",
        submission_id="submission-001",
        limit=2,
        cursor=first_page["LastEvaluatedKey"],
    )

    assert len(second_page["Items"]) == 2

    first_ids = {event["event_id"] for event in first_page["Items"]}

    second_ids = {event["event_id"] for event in second_page["Items"]}

    assert first_ids.isdisjoint(second_ids)


def test_audit_query_is_tenant_scoped(
    dynamodb_repositories,
    dynamodb_local,
):
    audit = dynamodb_repositories["audit"]

    table = dynamodb_local.Table("cloudsec-test-audit-events")

    table.put_item(
        Item=create_audit_event(
            tenant_id="tenant-a",
            event_id="event-a",
        )
    )

    table.put_item(
        Item=create_audit_event(
            tenant_id="tenant-b",
            event_id="event-b",
        )
    )

    result = audit.list_submission_events(
        tenant_id="tenant-a",
        submission_id="submission-001",
        limit=10,
    )

    assert len(result["Items"]) == 1
    assert result["Items"][0]["tenant_id"] == "tenant-a"


@pytest.mark.parametrize(
    (
        "pending_document_count",
        "uploaded_document_count",
    ),
    [
        (1, 1),
        (0, 0),
    ],
)
def test_submission_transition_requires_completed_documents(
    dynamodb_repositories,
    submission_factory,
    pending_document_count,
    uploaded_document_count,
):
    submissions = dynamodb_repositories["submissions"]
    audit = dynamodb_repositories["audit"]

    submissions.create_submission(
        submission_factory(
            pending_document_count=pending_document_count,
            uploaded_document_count=uploaded_document_count,
        )
    )

    put_membership(
        dynamodb_repositories,
        user_id="user-a",
        role="SUBMITTER",
        status="ACTIVE",
    )

    with pytest.raises(SubmissionStateConflictError):
        submissions.transition_submission(
            tenant_id="tenant-a",
            submission_id="submission-001",
            previous_status="DRAFT",
            new_status="SUBMITTED",
            expected_version=1,
            updated_at="2026-11-13T10:10:00Z",
            audit_event=create_audit_event(),
            owner_id="user-a",
            require_uploaded_documents=True,
            actor_id="user-a",
            actor_role="SUBMITTER",
        )

    submission = submissions.get_submission(
        "tenant-a",
        "submission-001",
    )

    assert submission["status"] == "DRAFT"
    assert submission["version"] == 1
    assert submission["pending_document_count"] == (pending_document_count)
    assert submission["uploaded_document_count"] == (uploaded_document_count)

    events = audit.list_submission_events(
        tenant_id="tenant-a",
        submission_id="submission-001",
        limit=10,
    )

    assert events["Items"] == []


def test_document_count_quota_is_enforced_atomically(
    dynamodb_repositories,
    submission_factory,
):
    submissions = dynamodb_repositories["submissions"]
    documents = dynamodb_repositories["documents"]

    submissions.create_submission(submission_factory(total_document_count=10))

    with pytest.raises(DocumentQuotaExceededError):
        documents.create_document(create_document())

    submission = submissions.get_submission("tenant-a", "submission-001")
    assert submission["total_document_count"] == 10
    assert submission["pending_document_count"] == 0
    assert documents.get_document("tenant-a", "submission-001", "document-001") is None


def test_submission_byte_quota_is_enforced_at_boundary(
    dynamodb_repositories,
    submission_factory,
):
    submissions = dynamodb_repositories["submissions"]
    documents = dynamodb_repositories["documents"]

    limit = 50 * 1024 * 1024
    submissions.create_submission(submission_factory(total_document_bytes=limit - 1024))

    documents.create_document(create_document(size_bytes=1024))

    with pytest.raises(DocumentQuotaExceededError):
        documents.create_document(
            create_document(
                document_id="document-002",
                size_bytes=1,
            )
        )

    submission = submissions.get_submission("tenant-a", "submission-001")
    assert submission["total_document_bytes"] == limit
    assert submission["pending_document_bytes"] == 1024


def test_document_completion_moves_pending_bytes_to_uploaded_bytes(
    dynamodb_repositories,
    submission_factory,
):
    submissions = dynamodb_repositories["submissions"]
    documents = dynamodb_repositories["documents"]

    submissions.create_submission(submission_factory())

    document = create_document(size_bytes=2048)
    documents.create_document(document)

    shard = document["GSI3PK"].split("#")[-1]

    documents.mark_document_uploaded(
        tenant_id="tenant-a",
        submission_id="submission-001",
        document_id="document-001",
        uploaded_at="2026-11-12T10:05:00Z",
        version_id="s3-version-123",
        owner_id="user-a",
        size_bytes=2048,
        pending_gsi3_pk=document["GSI3PK"],
        pending_gsi3_sk=document["GSI3SK"],
        uploaded_gsi3_pk=f"UPLOADED#{shard}",
        uploaded_gsi3_sk=(f"{document['upload_hygiene_after']}#document-001"),
        upload_url_expires_at=document["upload_url_expires_at"],
        upload_hygiene_after=document["upload_hygiene_after"],
    )

    submission = submissions.get_submission(
        "tenant-a",
        "submission-001",
    )

    assert submission["pending_document_count"] == 0
    assert submission["pending_document_bytes"] == 0
    assert submission["uploaded_document_count"] == 1
    assert submission["uploaded_document_bytes"] == 2048
    assert submission["total_document_count"] == 1
    assert submission["total_document_bytes"] == 2048


def create_membership(
    user_id,
    tenant_id="tenant-a",
    role="SUBMITTER",
    status="ACTIVE",
):
    return {
        "PK": f"USER#{user_id}",
        "SK": f"TENANT#{tenant_id}",
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "status": status,
        "created_at": "2026-11-17T12:00:00Z",
        "GSI1PK": f"TENANT#{tenant_id}",
        "GSI1SK": f"USER#{user_id}",
    }


def put_membership(
    dynamodb_repositories,
    user_id,
    tenant_id="tenant-a",
    role="SUBMITTER",
    status="ACTIVE",
):
    dynamodb_repositories["memberships"].table.put_item(
        Item=create_membership(
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            status=status,
        )
    )


def create_membership_audit_event(
    target_user_id,
    event_id="membership-event-001",
    event_type="MEMBERSHIP_ROLE_CHANGED",
    previous_role="SUBMITTER",
    new_role="REVIEWER",
):
    timestamp = "2026-11-17T12:30:00Z"

    return {
        "PK": (f"TENANT#tenant-a#MEMBERSHIP#{target_user_id}"),
        "SK": f"EVENT#{timestamp}#{event_id}",
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": f"EVENT#{timestamp}#{event_id}",
        "entity_type": "AUDIT_EVENT",
        "event_id": event_id,
        "event_type": event_type,
        "tenant_id": "tenant-a",
        "target_user_id": target_user_id,
        "actor_id": "admin-a",
        "actor_role": "TENANT_ADMIN",
        "previous_role": previous_role,
        "new_role": new_role,
        "timestamp": timestamp,
        "request_id": "request-123",
    }


def test_tenant_admin_can_change_member_role_atomically(
    dynamodb_repositories,
    dynamodb_local,
):
    memberships = dynamodb_repositories["memberships"]
    membership_table = dynamodb_local.Table("cloudsec-test-memberships")
    audit_table = dynamodb_local.Table("cloudsec-test-audit-events")

    membership_table.put_item(
        Item=create_membership(
            "admin-a",
            role="TENANT_ADMIN",
        )
    )
    membership_table.put_item(
        Item=create_membership(
            "user-b",
            role="SUBMITTER",
        )
    )

    audit_event = create_membership_audit_event("user-b")

    memberships.change_member_role(
        tenant_id="tenant-a",
        actor_id="admin-a",
        target_user_id="user-b",
        expected_role="SUBMITTER",
        new_role="REVIEWER",
        updated_at="2026-11-17T12:30:00Z",
        audit_event=audit_event,
    )

    updated = memberships.get_membership(
        "user-b",
        "tenant-a",
    )

    assert updated["role"] == "REVIEWER"
    assert updated["status"] == "ACTIVE"
    assert updated["updated_at"] == "2026-11-17T12:30:00Z"

    stored_event = audit_table.get_item(
        Key={
            "PK": audit_event["PK"],
            "SK": audit_event["SK"],
        },
        ConsistentRead=True,
    ).get("Item")

    assert stored_event == audit_event


def test_tenant_admin_can_deactivate_member_atomically(
    dynamodb_repositories,
    dynamodb_local,
):
    memberships = dynamodb_repositories["memberships"]
    membership_table = dynamodb_local.Table("cloudsec-test-memberships")
    audit_table = dynamodb_local.Table("cloudsec-test-audit-events")

    membership_table.put_item(
        Item=create_membership(
            "admin-a",
            role="TENANT_ADMIN",
        )
    )
    membership_table.put_item(
        Item=create_membership(
            "user-b",
            role="REVIEWER",
        )
    )

    audit_event = create_membership_audit_event(
        "user-b",
        event_id="membership-event-002",
        event_type="MEMBERSHIP_DEACTIVATED",
        previous_role="REVIEWER",
        new_role="REVIEWER",
    )

    memberships.deactivate_member(
        tenant_id="tenant-a",
        actor_id="admin-a",
        target_user_id="user-b",
        expected_role="REVIEWER",
        updated_at="2026-11-17T12:35:00Z",
        audit_event=audit_event,
    )

    updated = memberships.get_membership(
        "user-b",
        "tenant-a",
    )

    assert updated["role"] == "REVIEWER"
    assert updated["status"] == "INACTIVE"
    assert updated["updated_at"] == "2026-11-17T12:35:00Z"

    stored_event = audit_table.get_item(
        Key={
            "PK": audit_event["PK"],
            "SK": audit_event["SK"],
        },
        ConsistentRead=True,
    ).get("Item")

    assert stored_event == audit_event


def test_non_admin_cannot_change_member_role(
    dynamodb_repositories,
    dynamodb_local,
):
    memberships = dynamodb_repositories["memberships"]
    table = dynamodb_local.Table("cloudsec-test-memberships")

    table.put_item(
        Item=create_membership(
            "user-a",
            role="REVIEWER",
        )
    )
    table.put_item(
        Item=create_membership(
            "user-b",
            role="SUBMITTER",
        )
    )

    audit_event = create_membership_audit_event("user-b")

    with pytest.raises(MembershipActorAuthorizationError):
        memberships.change_member_role(
            tenant_id="tenant-a",
            actor_id="user-a",
            target_user_id="user-b",
            expected_role="SUBMITTER",
            new_role="REVIEWER",
            updated_at="2026-11-17T12:40:00Z",
            audit_event=audit_event,
        )

    target = memberships.get_membership(
        "user-b",
        "tenant-a",
    )

    assert target["role"] == "SUBMITTER"

    assert (
        dynamodb_local.Table("cloudsec-test-audit-events")
        .get_item(
            Key={
                "PK": audit_event["PK"],
                "SK": audit_event["SK"],
            },
            ConsistentRead=True,
        )
        .get("Item")
        is None
    )


def test_stale_membership_role_causes_conflict_without_changes(
    dynamodb_repositories,
    dynamodb_local,
):
    memberships = dynamodb_repositories["memberships"]
    table = dynamodb_local.Table("cloudsec-test-memberships")

    table.put_item(
        Item=create_membership(
            "admin-a",
            role="TENANT_ADMIN",
        )
    )
    table.put_item(
        Item=create_membership(
            "user-b",
            role="REVIEWER",
        )
    )

    audit_event = create_membership_audit_event("user-b")

    with pytest.raises(MembershipStateConflictError):
        memberships.change_member_role(
            tenant_id="tenant-a",
            actor_id="admin-a",
            target_user_id="user-b",
            expected_role="SUBMITTER",
            new_role="REVIEWER",
            updated_at="2026-11-17T12:45:00Z",
            audit_event=audit_event,
        )

    target = memberships.get_membership(
        "user-b",
        "tenant-a",
    )

    assert target["role"] == "REVIEWER"
    assert target["status"] == "ACTIVE"
    assert "updated_at" not in target


def test_tenant_admin_cannot_modify_another_tenants_member(
    dynamodb_repositories,
    dynamodb_local,
):
    memberships = dynamodb_repositories["memberships"]
    table = dynamodb_local.Table("cloudsec-test-memberships")

    table.put_item(
        Item=create_membership(
            "admin-a",
            tenant_id="tenant-a",
            role="TENANT_ADMIN",
        )
    )
    table.put_item(
        Item=create_membership(
            "user-b",
            tenant_id="tenant-b",
            role="SUBMITTER",
        )
    )

    audit_event = create_membership_audit_event("user-b")

    with pytest.raises(MembershipStateConflictError):
        memberships.change_member_role(
            tenant_id="tenant-a",
            actor_id="admin-a",
            target_user_id="user-b",
            expected_role="SUBMITTER",
            new_role="REVIEWER",
            updated_at="2026-11-17T12:50:00Z",
            audit_event=audit_event,
        )

    other_tenant_member = memberships.get_membership(
        "user-b",
        "tenant-b",
    )

    assert other_tenant_member["role"] == "SUBMITTER"
    assert other_tenant_member["status"] == "ACTIVE"


def test_audit_event_collision_rolls_back_membership_update(
    dynamodb_repositories,
    dynamodb_local,
):
    memberships = dynamodb_repositories["memberships"]
    membership_table = dynamodb_local.Table("cloudsec-test-memberships")
    audit_table = dynamodb_local.Table("cloudsec-test-audit-events")

    membership_table.put_item(
        Item=create_membership(
            "admin-a",
            role="TENANT_ADMIN",
        )
    )
    membership_table.put_item(
        Item=create_membership(
            "user-b",
            role="SUBMITTER",
        )
    )

    audit_event = create_membership_audit_event("user-b")

    # Occupy the audit event key before the transaction.
    audit_table.put_item(Item=audit_event)

    with pytest.raises(MembershipStateConflictError):
        memberships.change_member_role(
            tenant_id="tenant-a",
            actor_id="admin-a",
            target_user_id="user-b",
            expected_role="SUBMITTER",
            new_role="REVIEWER",
            updated_at="2026-11-17T12:55:00Z",
            audit_event=audit_event,
        )

    target = memberships.get_membership(
        "user-b",
        "tenant-a",
    )

    # The failed audit Put must roll back the membership Update.
    assert target["role"] == "SUBMITTER"
    assert target["status"] == "ACTIVE"
    assert "updated_at" not in target

    # The original audit record must remain unchanged.
    stored_event = audit_table.get_item(
        Key={
            "PK": audit_event["PK"],
            "SK": audit_event["SK"],
        },
        ConsistentRead=True,
    ).get("Item")

    assert stored_event == audit_event


@pytest.mark.parametrize(
    ("membership_role", "membership_status"),
    [
        ("SUBMITTER", "INACTIVE"),
        ("REVIEWER", "ACTIVE"),
    ],
)
def test_submission_transition_rejects_unauthorized_membership(
    dynamodb_repositories,
    submission_factory,
    membership_role,
    membership_status,
):
    submissions = dynamodb_repositories["submissions"]
    audit = dynamodb_repositories["audit"]

    submissions.create_submission(
        submission_factory(
            uploaded_document_count=1,
        )
    )

    put_membership(
        dynamodb_repositories,
        user_id="user-a",
        role=membership_role,
        status=membership_status,
    )

    with pytest.raises(SubmissionActorAuthorizationError):
        submissions.transition_submission(
            tenant_id="tenant-a",
            submission_id="submission-001",
            previous_status="DRAFT",
            new_status="SUBMITTED",
            expected_version=1,
            updated_at="2026-11-13T10:10:00Z",
            audit_event=create_audit_event(),
            owner_id="user-a",
            require_uploaded_documents=True,
            actor_id="user-a",
            actor_role="SUBMITTER",
        )

    submission = submissions.get_submission(
        "tenant-a",
        "submission-001",
    )

    assert submission["status"] == "DRAFT"
    assert submission["version"] == 1

    events = audit.list_submission_events(
        tenant_id="tenant-a",
        submission_id="submission-001",
        limit=10,
    )

    assert events["Items"] == []
