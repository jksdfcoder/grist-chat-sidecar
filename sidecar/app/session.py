from itsdangerous import BadSignature, URLSafeTimedSerializer

_MAX_AGE = 12 * 60 * 60


def dump_session(payload: dict, secret: str) -> str:
    return URLSafeTimedSerializer(secret).dumps(payload)


def load_session(token: str, secret: str) -> dict | None:
    try:
        return URLSafeTimedSerializer(secret).loads(token, max_age=_MAX_AGE)
    except BadSignature:
        return None
