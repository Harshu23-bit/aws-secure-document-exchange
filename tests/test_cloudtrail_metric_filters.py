import json

import boto3

REGION = "ap-south-1"

# These patterns mirror cloudtrail-detections.tf.
# Keep them synchronized if you modify the Terraform filters.

TESTS = {
    "Root account usage": {
        "pattern": '{ $.userIdentity.type = "Root" }',
        "events": [
            {
                "eventSource": "iam.amazonaws.com",
                "eventName": "CreateUser",
                "userIdentity": {"type": "Root"},
            },
            {
                "eventSource": "iam.amazonaws.com",
                "eventName": "CreateUser",
                "userIdentity": {"type": "IAMUser"},
            },
        ],
        "expected_matches": [0],
    },
    "Failed console sign-ins": {
        "pattern": '{ $.eventSource = "signin.amazonaws.com" && $.eventName = "ConsoleLogin" && $.responseElements.ConsoleLogin = "Failure" }',
        "events": [
            {
                "eventSource": "signin.amazonaws.com",
                "eventName": "ConsoleLogin",
                "responseElements": {"ConsoleLogin": "Failure"},
            },
            {
                "eventSource": "signin.amazonaws.com",
                "eventName": "ConsoleLogin",
                "responseElements": {"ConsoleLogin": "Success"},
            },
        ],
        "expected_matches": [0],
    },
    "Unauthorized API calls": {
        "pattern": '{ $.errorCode = "*AccessDenied*" || $.errorCode = "*UnauthorizedOperation*" }',
        "events": [
            {
                "eventSource": "s3.amazonaws.com",
                "eventName": "GetObject",
                "errorCode": "AccessDenied",
            },
            {
                "eventSource": "ec2.amazonaws.com",
                "eventName": "RunInstances",
                "errorCode": "UnauthorizedOperation",
            },
            {"eventSource": "s3.amazonaws.com", "eventName": "ListBucket"},
        ],
        "expected_matches": [0, 1],
    },
    "IAM policy changes": {
        "pattern": '{ $.eventSource = "iam.amazonaws.com" && ($.eventName = "CreatePolicy" || $.eventName = "CreatePolicyVersion" || $.eventName = "DeletePolicy" || $.eventName = "DeletePolicyVersion" || $.eventName = "SetDefaultPolicyVersion" || $.eventName = "AttachGroupPolicy" || $.eventName = "AttachRolePolicy" || $.eventName = "AttachUserPolicy" || $.eventName = "DetachGroupPolicy" || $.eventName = "DetachRolePolicy" || $.eventName = "DetachUserPolicy" || $.eventName = "PutGroupPolicy" || $.eventName = "PutRolePolicy" || $.eventName = "PutUserPolicy" || $.eventName = "DeleteGroupPolicy" || $.eventName = "DeleteRolePolicy" || $.eventName = "DeleteUserPolicy" || $.eventName = "UpdateAssumeRolePolicy") }',
        "events": [
            {"eventSource": "iam.amazonaws.com", "eventName": "CreatePolicyVersion"},
            {"eventSource": "iam.amazonaws.com", "eventName": "CreateUser"},
            {"eventSource": "ec2.amazonaws.com", "eventName": "CreatePolicyVersion"},
        ],
        "expected_matches": [0],
    },
    "IAM identity and credential changes": {
        "pattern": '{ $.eventSource = "iam.amazonaws.com" && ($.eventName = "CreateUser" || $.eventName = "DeleteUser" || $.eventName = "CreateRole" || $.eventName = "DeleteRole" || $.eventName = "CreateAccessKey" || $.eventName = "UpdateAccessKey" || $.eventName = "DeleteAccessKey" || $.eventName = "CreateLoginProfile" || $.eventName = "UpdateLoginProfile" || $.eventName = "DeleteLoginProfile" || $.eventName = "AddUserToGroup" || $.eventName = "RemoveUserFromGroup" || $.eventName = "CreateVirtualMFADevice" || $.eventName = "EnableMFADevice" || $.eventName = "DeactivateMFADevice" || $.eventName = "DeleteVirtualMFADevice" || $.eventName = "ResyncMFADevice") }',
        "events": [
            {"eventSource": "iam.amazonaws.com", "eventName": "CreateAccessKey"},
            {"eventSource": "iam.amazonaws.com", "eventName": "ListAccessKeys"},
            {"eventSource": "ec2.amazonaws.com", "eventName": "CreateAccessKey"},
        ],
        "expected_matches": [0],
    },
    "Security group changes": {
        "pattern": '{ $.eventSource = "ec2.amazonaws.com" && ($.eventName = "CreateSecurityGroup" || $.eventName = "DeleteSecurityGroup" || $.eventName = "AuthorizeSecurityGroupIngress" || $.eventName = "AuthorizeSecurityGroupEgress" || $.eventName = "RevokeSecurityGroupIngress" || $.eventName = "RevokeSecurityGroupEgress" || $.eventName = "ModifySecurityGroupRules") }',
        "events": [
            {
                "eventSource": "ec2.amazonaws.com",
                "eventName": "AuthorizeSecurityGroupIngress",
            },
            {"eventSource": "ec2.amazonaws.com", "eventName": "DescribeSecurityGroups"},
            {
                "eventSource": "iam.amazonaws.com",
                "eventName": "AuthorizeSecurityGroupIngress",
            },
        ],
        "expected_matches": [0],
    },
    "CloudTrail tampering": {
        "pattern": '{ $.eventSource = "cloudtrail.amazonaws.com" && ($.eventName = "StopLogging" || $.eventName = "DeleteTrail" || $.eventName = "UpdateTrail" || $.eventName = "PutEventSelectors" || $.eventName = "PutInsightSelectors") }',
        "events": [
            {"eventSource": "cloudtrail.amazonaws.com", "eventName": "StopLogging"},
            {"eventSource": "cloudtrail.amazonaws.com", "eventName": "LookupEvents"},
            {"eventSource": "iam.amazonaws.com", "eventName": "StopLogging"},
        ],
        "expected_matches": [0],
    },
}


def main():
    client = boto3.client("logs", region_name=REGION)

    passed = 0
    failed = 0

    print(f"\nTesting CloudTrail metric filters in {REGION}\n")

    for name, test in TESTS.items():
        messages = [json.dumps(event) for event in test["events"]]

        try:
            response = client.test_metric_filter(
                filterPattern=test["pattern"], logEventMessages=messages
            )

            # Identify matched fixtures by their event messages rather
            # than assuming AWS eventNumber is zero-based.
            matched_messages = {
                match["eventMessage"] for match in response.get("matches", [])
            }

            actual_matches = [
                index
                for index, message in enumerate(messages)
                if message in matched_messages
            ]

            raw_event_numbers = [
                match["eventNumber"] for match in response.get("matches", [])
            ]

            expected_matches = test["expected_matches"]

            if actual_matches == expected_matches:
                print(f"[PASS] {name}")
                print(f"       Expected matches: {expected_matches}")
                print(f"       Actual matches:   {actual_matches}")
                print(f"       AWS eventNumbers: {raw_event_numbers}")
                passed += 1
            else:
                print(f"[FAIL] {name}")
                print(f"       Expected matches: {expected_matches}")
                print(f"       Actual matches:   {actual_matches}")
                print(f"       AWS eventNumbers: {raw_event_numbers}")
                failed += 1

        except Exception as exc:  # noqa: BLE001
            # Keep individual CloudTrail test failures isolated.
            print(f"[ERROR] {name}")
            print(f"        {type(exc).__name__}: {exc}")
            failed += 1

        print()

    print("=" * 55)
    print(f"RESULT: {passed} passed, {failed} failed")
    print("=" * 55)

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
