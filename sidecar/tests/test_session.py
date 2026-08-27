from app.session import dump_session, load_session

def test_roundtrip():
    token = dump_session({"email": "a@hku.hk", "role": "manager"}, "secret-secret-secret-secret")
    assert load_session(token, "secret-secret-secret-secret")["email"] == "a@hku.hk"
    assert load_session(token, "wrong-wrong-wrong-wrong-wrong") is None
    assert load_session("garbage", "secret-secret-secret-secret") is None
