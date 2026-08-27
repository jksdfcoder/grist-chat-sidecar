from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.hkul import parse_email_domains, parse_list, parse_provider_ids

_DEV_SECRET = "dev-secret-change-me-32chars!!"


def _alias(*names: str) -> AliasChoices:
    return AliasChoices(*names)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    require_roles: bool = Field(default=False, validation_alias=_alias("SIH_REQUIRE_ROLES", "require_roles"))
    managers: Annotated[list[str], NoDecode] = Field(
        default=[], validation_alias=_alias("SIH_MANAGERS", "managers")
    )
    maintainers: Annotated[list[str], NoDecode] = Field(
        default=[], validation_alias=_alias("SIH_MAINTAINERS", "maintainers")
    )
    secret_key: str = Field(default=_DEV_SECRET, validation_alias=_alias("SIH_SECRET_KEY", "secret_key"))
    e2e: bool = Field(default=False, validation_alias=_alias("SIH_E2E", "e2e"))
    cookie_secure: bool = Field(
        default=False, validation_alias=_alias("BACKEND_SESSION_COOKIE_SECURE", "cookie_secure")
    )
    openrouter_api_key: str = Field(
        default="", validation_alias=_alias("OPENROUTER_API_KEY", "openrouter_api_key")
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias=_alias("OPENROUTER_BASE_URL", "openrouter_base_url"),
    )
    openrouter_model: str = Field(
        default="openrouter/free", validation_alias=_alias("OPENROUTER_MODEL", "openrouter_model")
    )
    openrouter_stub: str = Field(default="", validation_alias=_alias("OPENROUTER_STUB", "openrouter_stub"))
    openai_base_url: str = Field(default="", validation_alias=_alias("OPENAI_BASE_URL", "openai_base_url"))
    openai_api_key: str = Field(default="", validation_alias=_alias("OPENAI_API_KEY", "openai_api_key"))
    sqlite_path: str = Field(
        default=":memory:", validation_alias=_alias("SIH_SQLITE_PATH", "sqlite_path")
    )
    allowed_emails: Annotated[list[str], NoDecode] = Field(
        default=[], validation_alias=_alias("SIH_AUTH_ALLOWED_EMAILS", "allowed_emails")
    )
    allowed_email_domains: Annotated[list[str], NoDecode] = Field(
        default=[], validation_alias=_alias("SIH_AUTH_ALLOWED_EMAIL_DOMAINS", "allowed_email_domains")
    )
    allowed_provider_ids: Annotated[list[str], NoDecode] = Field(
        default=[], validation_alias=_alias("SIH_AUTH_ALLOWED_PROVIDER_IDS", "allowed_provider_ids")
    )
    upstream_db_host: str = Field(default="", validation_alias=_alias("UPSTREAM_DB_HOST", "upstream_db_host"))
    upstream_db_port: int = Field(default=6432, validation_alias=_alias("UPSTREAM_DB_PORT", "upstream_db_port"))
    upstream_connect_timeout: int = Field(
        default=90, validation_alias=_alias("UPSTREAM_CONNECT_TIMEOUT", "upstream_connect_timeout")
    )
    upstream_hub_dbname: str = Field(
        default="hub", validation_alias=_alias("UPSTREAM_HUB_DBNAME", "upstream_hub_dbname")
    )
    upstream_hub_user: str = Field(default="", validation_alias=_alias("UPSTREAM_HUB_USER", "upstream_hub_user"))
    upstream_hub_password: str = Field(
        default="", validation_alias=_alias("UPSTREAM_HUB_PASSWORD", "upstream_hub_password")
    )
    upstream_dspace_dbname: str = Field(
        default="dspace", validation_alias=_alias("UPSTREAM_DSPACE_DBNAME", "upstream_dspace_dbname")
    )
    upstream_dspace_user: str = Field(
        default="", validation_alias=_alias("UPSTREAM_DSPACE_USER", "upstream_dspace_user")
    )
    upstream_dspace_password: str = Field(
        default="", validation_alias=_alias("UPSTREAM_DSPACE_PASSWORD", "upstream_dspace_password")
    )

    @field_validator("e2e", "require_roles", "cookie_secure", mode="before")
    @classmethod
    def _blank_bool_false(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return False
        return value

    @field_validator("managers", "maintainers", "allowed_emails", mode="before")
    @classmethod
    def _parse_emails(cls, value):
        return parse_list(value)

    @field_validator("allowed_email_domains", mode="before")
    @classmethod
    def _parse_domains(cls, value):
        return parse_email_domains(value)

    @field_validator("allowed_provider_ids", mode="before")
    @classmethod
    def _parse_provider_ids(cls, value):
        return parse_provider_ids(value)

    def validate_roles(self) -> None:
        if not self.require_roles:
            return
        if not self.managers:
            raise RuntimeError("SIH_MANAGERS is empty")
        if self.secret_key == _DEV_SECRET:
            raise RuntimeError("SIH_SECRET_KEY is the default")
        if not (self.allowed_emails or self.allowed_email_domains or self.allowed_provider_ids):
            raise RuntimeError("SIH_AUTH_ALLOWED_* is empty")
