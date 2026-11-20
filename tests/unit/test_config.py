import pytest

from app.core.config import Settings


def valid_cognito_settings(**overrides) -> Settings:
    values = {
        "cognito_region": "ap-south-1",
        "cognito_user_pool_id": "ap-south-1_AbCdEf123",
        "cognito_api_client_id": "abcdefghijklmnopqrstuvwxyz123456",
    }
    values.update(overrides)

    return Settings(**values)


def test_valid_cognito_configuration():
    settings = valid_cognito_settings()

    settings.validate_cognito_configuration()

    assert settings.cognito_issuer == (
        "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_AbCdEf123"
    )


def test_missing_cognito_configuration_is_rejected():
    settings = Settings()

    with pytest.raises(ValueError, match="incomplete"):
        settings.validate_cognito_configuration()


def test_invalid_cognito_region_is_rejected():
    settings = valid_cognito_settings(cognito_region="invalid-region")

    with pytest.raises(ValueError, match="region is invalid"):
        settings.validate_cognito_configuration()


def test_user_pool_region_mismatch_is_rejected():
    settings = valid_cognito_settings(
        cognito_region="ap-south-1",
        cognito_user_pool_id="us-east-1_AbCdEf123",
    )

    with pytest.raises(ValueError, match="user pool ID is invalid"):
        settings.validate_cognito_configuration()


def test_invalid_user_pool_suffix_is_rejected():
    settings = valid_cognito_settings(
        cognito_user_pool_id="ap-south-1_invalid_suffix!",
    )

    with pytest.raises(ValueError, match="user pool ID is invalid"):
        settings.validate_cognito_configuration()


def test_invalid_client_id_is_rejected():
    settings = valid_cognito_settings(
        cognito_api_client_id="invalid-client-id!",
    )

    with pytest.raises(ValueError, match="app client ID is invalid"):
        settings.validate_cognito_configuration()


def test_oversized_client_id_is_rejected():
    settings = valid_cognito_settings(
        cognito_api_client_id="a" * 129,
    )

    with pytest.raises(ValueError, match="app client ID is invalid"):
        settings.validate_cognito_configuration()


def test_development_allows_missing_cognito_configuration():
    settings = Settings(environment="development")

    assert settings.environment == "development"
    assert settings.cognito_region is None
