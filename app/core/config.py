import re
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AWS_REGION_PATTERN = re.compile(r"^[a-z]{2}(?:-[a-z0-9]+)+-\d$")
COGNITO_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9]+$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    app_name: str = "Secure Multi-Tenant Document Exchange Platform"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = Field(default="INFO")
    api_gateway_stage_prefix: str = ""

    max_documents_per_submission: int = Field(default=10, gt=0)
    max_submission_bytes: int = Field(default=50 * 1024 * 1024, gt=0)

    aws_region: str = "ap-south-1"
    dynamodb_endpoint_url: str | None = None

    submissions_table_name: str = "cloudsec-submissions-dev"
    memberships_table_name: str = "cloudsec-tenant-memberships-dev"
    audit_events_table_name: str = "cloudsec-audit-events-dev"

    documents_bucket_name: str | None = None
    documents_kms_key_arn: str | None = None

    cognito_region: str | None = None
    cognito_user_pool_id: str | None = None
    cognito_api_client_id: str | None = None

    # Added JWKS configuration fields
    jwks_bucket_name: str | None = None
    jwks_object_key: str = "security/jwks.json"

    def validate_cognito_configuration(self) -> None:
        """Validate the complete Cognito configuration."""

        region = self.cognito_region
        user_pool_id = self.cognito_user_pool_id
        client_id = self.cognito_api_client_id

        if not region or not user_pool_id or not client_id:
            raise ValueError("Cognito configuration is incomplete")

        if not AWS_REGION_PATTERN.fullmatch(region):
            raise ValueError("Cognito region is invalid")

        if len(user_pool_id) > 128 or "_" not in user_pool_id:
            raise ValueError("Cognito user pool ID is invalid")

        pool_region, pool_suffix = user_pool_id.split("_", 1)

        if pool_region != region or not COGNITO_IDENTIFIER_PATTERN.fullmatch(
            pool_suffix
        ):
            raise ValueError("Cognito user pool ID is invalid")

        if len(client_id) > 128 or not COGNITO_IDENTIFIER_PATTERN.fullmatch(client_id):
            raise ValueError("Cognito app client ID is invalid")

    @property
    def cognito_issuer(self) -> str:
        region = self.cognito_region
        user_pool_id = self.cognito_user_pool_id

        if not region or not user_pool_id:
            raise ValueError("Cognito user pool configuration is missing")

        if not AWS_REGION_PATTERN.fullmatch(region):
            raise ValueError("Cognito region is invalid")

        if len(user_pool_id) > 128 or "_" not in user_pool_id:
            raise ValueError("Cognito user pool ID is invalid")

        pool_region, pool_suffix = user_pool_id.split("_", 1)

        if pool_region != region or not COGNITO_IDENTIFIER_PATTERN.fullmatch(
            pool_suffix
        ):
            raise ValueError("Cognito user pool ID is invalid")

        return f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"

    @property
    def cognito_jwks_url(self) -> str:
        return f"{self.cognito_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
