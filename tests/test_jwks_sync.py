import base64
import importlib.util
import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric import rsa

# Load handler.py directly because "lambda" is a Python keyword.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = PROJECT_ROOT / "lambda" / "jwks_sync" / "handler.py"

spec = importlib.util.spec_from_file_location(
    "jwks_sync_handler",
    HANDLER_PATH,
)

handler_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler_module)


def encode_base64url_uint(value: int) -> str:
    encoded = value.to_bytes((value.bit_length() + 7) // 8, "big")

    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


_test_private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)

_test_public_numbers = _test_private_key.public_key().public_numbers()

VALID_JWKS = {
    "keys": [
        {
            "kid": "test-key-123",
            "kty": "RSA",
            "alg": "RS256",
            "use": "sig",
            "n": encode_base64url_uint(_test_public_numbers.n),
            "e": encode_base64url_uint(_test_public_numbers.e),
        }
    ]
}


class FakeS3:
    def __init__(self, existing=None):
        self.existing = existing
        self.put_calls = []

    def get_object(self, Bucket, Key):
        if self.existing is None:
            raise ClientError(
                {
                    "Error": {
                        "Code": "NoSuchKey",
                        "Message": "Object does not exist",
                    }
                },
                "GetObject",
            )

        data = self.existing

        return {
            "Body": io.BytesIO(data),
            "ContentLength": len(data),
        }

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)


class TestJWKSValidation(unittest.TestCase):
    def test_valid_jwks(self):
        self.assertEqual(
            handler_module.validate_jwks(VALID_JWKS),
            1,
        )

    def test_empty_keys_rejected(self):
        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.validate_jwks({"keys": []})

    def test_invalid_algorithm_rejected(self):
        document = json.loads(json.dumps(VALID_JWKS))
        document["keys"][0]["alg"] = "HS256"

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.validate_jwks(document)

    def test_duplicate_kid_rejected(self):
        document = json.loads(json.dumps(VALID_JWKS))
        document["keys"].append(document["keys"][0])

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.validate_jwks(document)

    def test_private_key_material_rejected(self):
        document = json.loads(json.dumps(VALID_JWKS))
        document["keys"][0]["d"] = "private-key-material"

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.validate_jwks(document)

    def test_invalid_json_rejected(self):
        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.canonicalize_jwks(b"{invalid-json")

    def test_canonicalization(self):
        raw = json.dumps(VALID_JWKS).encode("utf-8")

        canonical, key_count = handler_module.canonicalize_jwks(raw)

        self.assertEqual(key_count, 1)
        self.assertEqual(json.loads(canonical), VALID_JWKS)

    def test_expected_cognito_url(self):
        url = handler_module.build_jwks_url(
            "ap-south-1",
            "ap-south-1_AbCdEf123",
        )

        self.assertEqual(
            url,
            "https://cognito-idp.ap-south-1.amazonaws.com/"
            "ap-south-1_AbCdEf123/.well-known/jwks.json",
        )

    def test_invalid_region_rejected(self):
        with self.assertRaises(ValueError):
            handler_module.build_jwks_url(
                "https://malicious.example",
                "ap-south-1_AbCdEf123",
            )

    def test_invalid_base64url_modulus_rejected(self):
        document = json.loads(json.dumps(VALID_JWKS))
        document["keys"][0]["n"] = "invalid+base64"

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.validate_jwks(document)

    def test_undersized_rsa_modulus_rejected(self):
        document = json.loads(json.dumps(VALID_JWKS))
        document["keys"][0]["n"] = encode_base64url_uint(2**1023 + 1)

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.validate_jwks(document)

    def test_oversized_rsa_modulus_rejected(self):
        document = json.loads(json.dumps(VALID_JWKS))
        document["keys"][0]["n"] = encode_base64url_uint(2**8192 + 1)

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.validate_jwks(document)

    def test_even_rsa_modulus_rejected(self):
        document = json.loads(json.dumps(VALID_JWKS))
        document["keys"][0]["n"] = encode_base64url_uint(2**2047)

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.validate_jwks(document)

    def test_invalid_rsa_exponent_rejected(self):
        document = json.loads(json.dumps(VALID_JWKS))
        document["keys"][0]["e"] = encode_base64url_uint(2)

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.validate_jwks(document)

    def test_excessive_key_count_rejected(self):
        document = json.loads(json.dumps(VALID_JWKS))
        document["keys"] = [
            {
                **document["keys"][0],
                "kid": f"key-{index}",
            }
            for index in range(11)
        ]

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.validate_jwks(document)

    def test_oversized_kid_rejected(self):
        document = json.loads(json.dumps(VALID_JWKS))
        document["keys"][0]["kid"] = "a" * 257

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.validate_jwks(document)

    def test_unsupported_key_type_rejected(self):
        document = json.loads(json.dumps(VALID_JWKS))
        document["keys"][0]["kty"] = "EC"

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.validate_jwks(document)

    def test_unsupported_key_usage_rejected(self):
        document = json.loads(json.dumps(VALID_JWKS))
        document["keys"][0]["use"] = "enc"

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.validate_jwks(document)

    def test_leading_zero_rsa_integer_rejected(self):
        # AAAB represents the bytes 00 00 01.
        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.decode_base64url_uint("AAAB")

    def test_duplicate_json_properties_rejected(self):
        document = (
            b'{"keys":[],"keys":['
            b'{"kid":"first","kty":"RSA","alg":"RS256",'
            b'"use":"sig","n":"abc","e":"AQAB"}]}'
        )

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.canonicalize_jwks(document)

    def test_duplicate_nested_json_properties_rejected(self):
        document = (
            b'{"keys":[{"kid":"first","kid":"second",'
            b'"kty":"RSA","alg":"RS256","use":"sig",'
            b'"n":"abc","e":"AQAB"}]}'
        )

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.canonicalize_jwks(document)

    def test_nan_json_constant_rejected(self):
        document = b'{"keys":[],"value":NaN}'

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.canonicalize_jwks(document)

    def test_infinity_json_constant_rejected(self):
        document = b'{"keys":[],"value":Infinity}'

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.canonicalize_jwks(document)

    def test_negative_infinity_json_constant_rejected(self):
        document = b'{"keys":[],"value":-Infinity}'

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.canonicalize_jwks(document)

    def test_invalid_utf8_rejected(self):
        document = b'{"keys":[]}\xff'

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.canonicalize_jwks(document)

    def test_deeply_nested_json_rejected(self):
        document = b"[" * 1100 + b"0" + b"]" * 1100

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.canonicalize_jwks(document)

    def test_user_pool_region_must_match_aws_region(self):
        with self.assertRaises(ValueError):
            handler_module.build_jwks_url(
                "ap-south-1",
                "us-east-1_AbCdEf123",
            )

    def test_unexpected_jwks_urls_rejected(self):
        invalid_urls = [
            (
                "http://cognito-idp.ap-south-1.amazonaws.com/"
                "ap-south-1_AbCdEf123/.well-known/jwks.json"
            ),
            ("https://evil.example/ap-south-1_AbCdEf123/.well-known/jwks.json"),
            (
                "https://cognito-idp.ap-south-1.amazonaws.com/"
                "ap-south-1_AbCdEf123/unexpected.json"
            ),
            (
                "https://cognito-idp.us-east-1.amazonaws.com/"
                "ap-south-1_AbCdEf123/.well-known/jwks.json"
            ),
        ]

        with patch("urllib.request.build_opener") as mock_opener:
            for url in invalid_urls:
                with (
                    self.subTest(url=url),
                    self.assertRaises(ValueError),
                ):
                    handler_module.fetch_jwks(url)

            mock_opener.assert_not_called()


class TestJWKSHTTP(unittest.TestCase):
    TEST_URL = (
        "https://cognito-idp.ap-south-1.amazonaws.com/"
        "ap-south-1_AbCdEf123/.well-known/jwks.json"
    )

    def make_response(self, status=200, content=b'{"keys":[]}'):
        response = MagicMock()
        response.status = status
        response.read.return_value = content
        response.__enter__.return_value = response
        return response

    @patch("urllib.request.build_opener")
    def test_successful_https_retrieval(self, mock_build_opener):
        response = self.make_response()
        opener = MagicMock()
        opener.open.return_value = response
        mock_build_opener.return_value = opener

        result = handler_module.fetch_jwks(self.TEST_URL)

        self.assertEqual(result, b'{"keys":[]}')
        opener.open.assert_called_once()
        self.assertEqual(
            opener.open.call_args.kwargs["timeout"],
            handler_module.HTTP_TIMEOUT_SECONDS,
        )
        response.read.assert_called_once_with(handler_module.MAX_RESPONSE_BYTES + 1)

    @patch("urllib.request.build_opener")
    def test_non_200_response_rejected(self, mock_build_opener):
        response = self.make_response(status=503)
        opener = MagicMock()
        opener.open.return_value = response
        mock_build_opener.return_value = opener

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.fetch_jwks(self.TEST_URL)

        response.read.assert_not_called()

    @patch("urllib.request.build_opener")
    def test_oversized_http_response_rejected(self, mock_build_opener):
        response = self.make_response(
            content=b"x" * (handler_module.MAX_RESPONSE_BYTES + 1)
        )

        opener = MagicMock()
        opener.open.return_value = response
        mock_build_opener.return_value = opener

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.fetch_jwks(self.TEST_URL)

        response.read.assert_called_once_with(handler_module.MAX_RESPONSE_BYTES + 1)

    @patch("urllib.request.build_opener")
    def test_maximum_allowed_response_size_accepted(
        self,
        mock_build_opener,
    ):
        content = b"x" * handler_module.MAX_RESPONSE_BYTES

        response = self.make_response(content=content)
        opener = MagicMock()
        opener.open.return_value = response
        mock_build_opener.return_value = opener

        result = handler_module.fetch_jwks(self.TEST_URL)

        self.assertEqual(len(result), handler_module.MAX_RESPONSE_BYTES)

    @patch("urllib.request.build_opener")
    def test_http_error_converted_to_validation_error(
        self,
        mock_build_opener,
    ):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError(
            self.TEST_URL,
            503,
            "Service Unavailable",
            None,
            None,
        )
        mock_build_opener.return_value = opener

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.fetch_jwks(self.TEST_URL)

    @patch("urllib.request.build_opener")
    def test_redirect_rejected(self, mock_build_opener):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError(
            self.TEST_URL,
            302,
            "Found",
            None,
            None,
        )
        mock_build_opener.return_value = opener

        with self.assertRaises(handler_module.JWKSValidationError):
            handler_module.fetch_jwks(self.TEST_URL)

    @patch("urllib.request.build_opener")
    def test_timeout_propagates(self, mock_build_opener):
        opener = MagicMock()
        opener.open.side_effect = TimeoutError("Connection timed out")
        mock_build_opener.return_value = opener

        with self.assertRaises(TimeoutError):
            handler_module.fetch_jwks(self.TEST_URL)

    @patch("urllib.request.build_opener")
    def test_url_error_propagates(self, mock_build_opener):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.URLError("Temporary DNS failure")
        mock_build_opener.return_value = opener

        with self.assertRaises(urllib.error.URLError):
            handler_module.fetch_jwks(self.TEST_URL)

    def test_redirect_handler_does_not_follow_redirects(self):
        redirect_handler = handler_module.RejectRedirectHandler()

        result = redirect_handler.redirect_request(
            None,
            None,
            302,
            "Found",
            {},
            "https://evil.example/",
        )

        self.assertIsNone(result)


class TestJWKSStorage(unittest.TestCase):
    def test_changed_jwks_updates_s3(self):
        new_document = b'{"keys":[{"kid":"new-key"}]}'

        s3 = FakeS3(existing=b'{"keys":[{"kid":"old-key"}]}')

        changed = handler_module.publish_jwks(
            s3,
            "test-bucket",
            "security/jwks.json",
            new_document,
        )

        self.assertTrue(changed)
        self.assertEqual(len(s3.put_calls), 1)
        self.assertEqual(s3.put_calls[0]["Body"], new_document)

    def test_unchanged_jwks_refreshes_s3_snapshot(self):
        document = b'{"keys":[{"kid":"same-key"}]}'

        s3 = FakeS3(existing=document)

        changed = handler_module.publish_jwks(
            s3,
            "test-bucket",
            "security/jwks.json",
            document,
        )

        self.assertFalse(changed)
        self.assertEqual(len(s3.put_calls), 1)
        self.assertEqual(s3.put_calls[0]["Body"], document)

    def test_missing_object_creates_initial_jwks(self):
        document = b'{"keys":[{"kid":"initial-key"}]}'

        s3 = FakeS3()

        changed = handler_module.publish_jwks(
            s3,
            "test-bucket",
            "security/jwks.json",
            document,
        )

        self.assertTrue(changed)
        self.assertEqual(len(s3.put_calls), 1)

    def test_get_existing_object_returns_data_and_closes_body(self):
        data = b'{"keys":[]}'

        body = io.BytesIO(data)
        s3 = MagicMock()
        s3.get_object.return_value = {
            "Body": body,
            "ContentLength": len(data),
        }

        result = handler_module.get_existing_object(
            s3,
            "test-bucket",
            "security/jwks.json",
        )

        self.assertEqual(result, data)
        self.assertTrue(body.closed)

    def test_oversized_content_length_rejected_before_read(self):
        body = MagicMock()
        s3 = MagicMock()
        s3.get_object.return_value = {
            "Body": body,
            "ContentLength": handler_module.MAX_RESPONSE_BYTES + 1,
        }

        with self.assertRaises(ValueError):
            handler_module.get_existing_object(
                s3,
                "test-bucket",
                "security/jwks.json",
            )

        body.read.assert_not_called()
        body.close.assert_called_once()

    def test_oversized_actual_body_rejected(self):
        data = b"x" * (handler_module.MAX_RESPONSE_BYTES + 1)

        body = io.BytesIO(data)
        s3 = MagicMock()
        s3.get_object.return_value = {
            "Body": body,
            "ContentLength": handler_module.MAX_RESPONSE_BYTES,
        }

        with self.assertRaises(ValueError):
            handler_module.get_existing_object(
                s3,
                "test-bucket",
                "security/jwks.json",
            )

        self.assertTrue(body.closed)

    def test_content_length_body_mismatch_rejected(self):
        data = b'{"keys":[]}'

        body = io.BytesIO(data)
        s3 = MagicMock()
        s3.get_object.return_value = {
            "Body": body,
            "ContentLength": len(data) + 1,
        }

        with self.assertRaises(ValueError):
            handler_module.get_existing_object(
                s3,
                "test-bucket",
                "security/jwks.json",
            )

        self.assertTrue(body.closed)

    def test_missing_content_length_rejected(self):
        body = io.BytesIO(b'{"keys":[]}')
        s3 = MagicMock()
        s3.get_object.return_value = {
            "Body": body,
        }

        with self.assertRaises(ValueError):
            handler_module.get_existing_object(
                s3,
                "test-bucket",
                "security/jwks.json",
            )

        self.assertTrue(body.closed)

    def test_invalid_content_length_rejected(self):
        invalid_values = [
            True,
            -1,
            "11",
            1.5,
        ]

        for content_length in invalid_values:
            with self.subTest(content_length=content_length):
                body = io.BytesIO(b'{"keys":[]}')
                s3 = MagicMock()
                s3.get_object.return_value = {
                    "Body": body,
                    "ContentLength": content_length,
                }

                with self.assertRaises(ValueError):
                    handler_module.get_existing_object(
                        s3,
                        "test-bucket",
                        "security/jwks.json",
                    )

                self.assertTrue(body.closed)

    def test_unexpected_s3_error_propagates(self):
        s3 = MagicMock()
        s3.get_object.side_effect = ClientError(
            {
                "Error": {
                    "Code": "AccessDenied",
                    "Message": "Access denied",
                }
            },
            "GetObject",
        )

        with self.assertRaises(ClientError) as context:
            handler_module.get_existing_object(
                s3,
                "test-bucket",
                "security/jwks.json",
            )

        self.assertEqual(
            context.exception.response["Error"]["Code"],
            "AccessDenied",
        )


class TestLambdaHandler(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {
            "AWS_REGION": "ap-south-1",
            "USER_POOL_ID": "ap-south-1_AbCdEf123",
            "JWKS_BUCKET": "test-bucket",
            "METRIC_NAMESPACE": "CloudSec/JWKS",
        },
    )
    @patch.object(handler_module, "fetch_jwks")
    @patch.object(handler_module.boto3, "client")
    def test_successful_sync_emits_heartbeat(
        self,
        mock_client,
        mock_fetch,
    ):
        s3 = FakeS3()
        cloudwatch = MagicMock()

        def client_factory(service, **kwargs):
            if service == "s3":
                return s3
            if service == "cloudwatch":
                return cloudwatch
            raise ValueError(service)

        mock_client.side_effect = client_factory
        mock_fetch.return_value = json.dumps(VALID_JWKS).encode()

        result = handler_module.handler({}, None)

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["changed"])

        cloudwatch.put_metric_data.assert_called_once()

    @patch.dict(
        "os.environ",
        {
            "AWS_REGION": "ap-south-1",
            "USER_POOL_ID": "ap-south-1_AbCdEf123",
            "JWKS_BUCKET": "test-bucket",
            "METRIC_NAMESPACE": "CloudSec/JWKS",
        },
    )
    @patch.object(handler_module, "fetch_jwks")
    @patch.object(handler_module.boto3, "client")
    def test_failed_retrieval_does_not_emit_heartbeat(
        self,
        mock_client,
        mock_fetch,
    ):
        s3 = FakeS3()
        cloudwatch = MagicMock()

        def client_factory(service, **kwargs):
            if service == "s3":
                return s3
            if service == "cloudwatch":
                return cloudwatch
            raise ValueError(service)

        mock_client.side_effect = client_factory

        mock_fetch.side_effect = RuntimeError("Simulated Cognito endpoint failure")

        with self.assertRaises(RuntimeError):
            handler_module.handler({}, None)

        cloudwatch.put_metric_data.assert_not_called()
        self.assertEqual(len(s3.put_calls), 0)

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_environment_variable_fails(self):
        with self.assertRaises(KeyError):
            handler_module.handler({}, None)

    @patch.dict(
        "os.environ",
        {
            "AWS_REGION": "ap-south-1",
            "USER_POOL_ID": "ap-south-1_AbCdEf123",
            "JWKS_BUCKET": "test-bucket",
            "METRIC_NAMESPACE": "CloudSec/JWKS",
        },
    )
    @patch.object(handler_module, "fetch_jwks")
    @patch.object(handler_module.boto3, "client")
    def test_s3_read_failure_does_not_emit_heartbeat(
        self,
        mock_client,
        mock_fetch,
    ):
        s3 = FakeS3()
        s3.get_object = MagicMock(
            side_effect=ClientError(
                {
                    "Error": {
                        "Code": "AccessDenied",
                        "Message": "Access denied",
                    }
                },
                "GetObject",
            )
        )

        cloudwatch = MagicMock()

        def client_factory(service, **kwargs):
            if service == "s3":
                return s3
            if service == "cloudwatch":
                return cloudwatch
            raise ValueError(service)

        mock_client.side_effect = client_factory
        mock_fetch.return_value = json.dumps(VALID_JWKS).encode()

        with self.assertRaises(ClientError):
            handler_module.handler({}, None)

        cloudwatch.put_metric_data.assert_not_called()

    @patch.dict(
        "os.environ",
        {
            "AWS_REGION": "ap-south-1",
            "USER_POOL_ID": "ap-south-1_AbCdEf123",
            "JWKS_BUCKET": "test-bucket",
            "METRIC_NAMESPACE": "CloudSec/JWKS",
        },
    )
    @patch.object(handler_module, "fetch_jwks")
    @patch.object(handler_module.boto3, "client")
    def test_s3_write_failure_does_not_emit_heartbeat(
        self,
        mock_client,
        mock_fetch,
    ):
        s3 = FakeS3()
        s3.put_object = MagicMock(
            side_effect=ClientError(
                {
                    "Error": {
                        "Code": "AccessDenied",
                        "Message": "Access denied",
                    }
                },
                "PutObject",
            )
        )

        cloudwatch = MagicMock()

        def client_factory(service, **kwargs):
            if service == "s3":
                return s3
            if service == "cloudwatch":
                return cloudwatch
            raise ValueError(service)

        mock_client.side_effect = client_factory
        mock_fetch.return_value = json.dumps(VALID_JWKS).encode()

        with self.assertRaises(ClientError):
            handler_module.handler({}, None)

        cloudwatch.put_metric_data.assert_not_called()

    @patch.dict(
        "os.environ",
        {
            "AWS_REGION": "ap-south-1",
            "USER_POOL_ID": "ap-south-1_AbCdEf123",
            "JWKS_BUCKET": "test-bucket",
            "METRIC_NAMESPACE": "CloudSec/JWKS",
        },
    )
    @patch.object(handler_module, "fetch_jwks")
    @patch.object(handler_module.boto3, "client")
    def test_heartbeat_failure_propagates_after_publication(
        self,
        mock_client,
        mock_fetch,
    ):
        s3 = FakeS3()
        cloudwatch = MagicMock()

        cloudwatch.put_metric_data.side_effect = RuntimeError(
            "Simulated CloudWatch failure"
        )

        def client_factory(service, **kwargs):
            if service == "s3":
                return s3
            if service == "cloudwatch":
                return cloudwatch
            raise ValueError(service)

        mock_client.side_effect = client_factory
        mock_fetch.return_value = json.dumps(VALID_JWKS).encode()

        with self.assertRaisesRegex(
            RuntimeError,
            "Simulated CloudWatch failure",
        ):
            handler_module.handler({}, None)

        self.assertEqual(len(s3.put_calls), 1)
        cloudwatch.put_metric_data.assert_called_once()


if __name__ == "__main__":
    unittest.main()
