import re


def _parts(value: str | list | None) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value or not str(value).strip():
        return []
    return [item.strip() for item in re.split(r"[\s,]+", str(value)) if item.strip()]


def parse_list(value: str | list | None) -> list[str]:
    return [item.lower() for item in _parts(value)]


def parse_provider_ids(value: str | list | None) -> list[str]:
    return _parts(value)


def parse_email_domains(value: str | list | None) -> list[str]:
    out = []
    for item in _parts(value):
        domain = item.lower().removeprefix("@")
        if domain:
            out.append(domain)
    return out


def is_hkul_access_allowed(
    *,
    email: str,
    provider_id: str,
    allowed_emails: list[str],
    allowed_email_domains: list[str],
    allowed_provider_ids: list[str],
) -> bool:
    if not allowed_emails and not allowed_email_domains and not allowed_provider_ids:
        return True
    normalized = email.strip().lower()
    domain = normalized.split("@")[1] if "@" in normalized else ""
    if allowed_emails and normalized in allowed_emails:
        return True
    if domain and domain in allowed_email_domains:
        return True
    if allowed_provider_ids and provider_id.strip() in allowed_provider_ids:
        return True
    return False
