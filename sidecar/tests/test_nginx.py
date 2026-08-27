from pathlib import Path

CONF = Path(__file__).resolve().parents[2] / "nginx.conf"


def test_nginx_proxies_sql_and_models():
    text = CONF.read_text()
    assert "location /api/sql" in text
    assert "location /api/models" in text
    assert "location /api/e2e" in text
    assert "location /api/auth/guest" in text
    assert "/api/auth/hkul" not in text
    assert "$http_host" in text
    assert "proxy_set_header Host $host;" not in text
    assert "location /api/chat" in text
    assert "proxy_read_timeout 600s" in text
    assert "proxy_buffering off" in text
    assert "proxy_read_timeout 180s" in text
    assert "ensure-chat.js" in text
    assert "sub_filter" in text
    assert "location /api/upload" in text
