from app.hkul import (
    is_hkul_access_allowed,
    parse_email_domains,
    parse_list,
    parse_provider_ids,
)
from app.settings import Settings


def test_empty_allowlist_allows():
    assert is_hkul_access_allowed(
        email="x@example.com", provider_id="1",
        allowed_emails=[], allowed_email_domains=[], allowed_provider_ids=[],
    )


def test_email_and_domain_and_sub():
    assert is_hkul_access_allowed(
        email="Ada@Example.COM", provider_id="nope",
        allowed_emails=["ada@example.com"], allowed_email_domains=[], allowed_provider_ids=[],
    )
    assert is_hkul_access_allowed(
        email="x@connect.example.com", provider_id="nope",
        allowed_emails=[], allowed_email_domains=["connect.example.com"], allowed_provider_ids=[],
    )
    assert is_hkul_access_allowed(
        email="z@x.com", provider_id="sub-9",
        allowed_emails=[], allowed_email_domains=[], allowed_provider_ids=["sub-9"],
    )
    assert not is_hkul_access_allowed(
        email="no@x.com", provider_id="x",
        allowed_emails=["ada@example.com"], allowed_email_domains=["example.com"], allowed_provider_ids=["s"],
    )


def test_provider_ids_keep_case():
    assert parse_provider_ids("Sub-ABC") == ["Sub-ABC"]
    assert parse_list("Sub-ABC") == ["sub-abc"]
    s = Settings.model_validate({"allowed_provider_ids": "Sub-ABC"})
    assert s.allowed_provider_ids == ["Sub-ABC"]
    assert is_hkul_access_allowed(
        email="z@x.com", provider_id="Sub-ABC",
        allowed_emails=[], allowed_email_domains=[], allowed_provider_ids=s.allowed_provider_ids,
    )
    assert not is_hkul_access_allowed(
        email="z@x.com", provider_id="sub-abc",
        allowed_emails=[], allowed_email_domains=[], allowed_provider_ids=s.allowed_provider_ids,
    )


def test_email_domains_strip_at():
    assert parse_email_domains("@Example.COM, connect.example.com") == ["example.com", "connect.example.com"]
    s = Settings.model_validate({"allowed_email_domains": "@Example.COM"})
    assert s.allowed_email_domains == ["example.com"]
    assert is_hkul_access_allowed(
        email="ada@example.com", provider_id="x",
        allowed_emails=[], allowed_email_domains=s.allowed_email_domains, allowed_provider_ids=[],
    )
