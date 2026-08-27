from typing import Literal


def role_for(
    email: str, maintainers: list[str], managers: list[str]
) -> Literal["manager", "maintainer"] | None:
    needle = email.strip().lower()
    if needle in (m.strip().lower() for m in managers):
        return "manager"
    if needle in (m.strip().lower() for m in maintainers):
        return "maintainer"
    return None
