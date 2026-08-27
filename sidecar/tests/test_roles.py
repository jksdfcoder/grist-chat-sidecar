from app.roles import role_for
from app.settings import Settings

def test_manager_wins_if_in_both():
    assert role_for("a@hku.hk", ["a@hku.hk"], ["a@hku.hk"]) == "manager"

def test_maintainer_and_unknown():
    assert role_for("b@hku.hk", ["b@hku.hk"], ["c@hku.hk"]) == "maintainer"
    assert role_for("z@hku.hk", ["b@hku.hk"], ["c@hku.hk"]) is None

def test_blank_e2e_is_false():
    assert Settings.model_validate({"e2e": ""}).e2e is False
    assert Settings.model_validate({"require_roles": ""}).require_roles is False

def test_require_roles_refuses_empty_managers():
    s = Settings.model_validate({
        "secret_key": "k" * 32,
        "require_roles": True,
        "managers": [],
        "maintainers": ["a@hku.hk"],
    })
    try:
        s.validate_roles()
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass

def test_require_roles_refuses_default_secret():
    s = Settings.model_validate({
        "secret_key": "dev-secret-change-me-32chars!!",
        "require_roles": True,
        "managers": ["a@hku.hk"],
        "allowed_email_domains": ["hku.hk"],
    })
    try:
        s.validate_roles()
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass

def test_require_roles_refuses_empty_allowlist():
    s = Settings.model_validate({
        "secret_key": "k" * 32,
        "require_roles": True,
        "managers": ["a@hku.hk"],
    })
    try:
        s.validate_roles()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "ALLOWED" in str(e)

