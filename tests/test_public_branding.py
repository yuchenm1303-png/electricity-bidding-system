"""Public homepage and privacy-policy routes required for OAuth branding."""
from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.web_server import app  # noqa: E402


def test_public_privacy_policy_is_independent_html(monkeypatch, tmp_path):
    from app import web_server
    policy = tmp_path / "privacy" / "index.html"
    policy.parent.mkdir()
    policy.write_text("<!doctype html><title>隐私政策 · PowerBid Studio</title>", encoding="utf8")
    monkeypatch.setattr(web_server, "DIST", tmp_path)
    with TestClient(app) as client:
        for path in ("/privacy", "/privacy/"):
            response = client.get(path)
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
            assert "隐私政策" in response.text
            assert "powerbid_session" not in response.headers.get("set-cookie", "")


def test_homepage_branding_and_privacy_link_exist():
    root = Path(__file__).resolve().parents[1]
    policy = (root / "frontend/public/privacy/index.html").read_text(encoding="utf8")
    homepage = (root / "frontend/src/LandingPage.tsx").read_text(encoding="utf8")
    entry = (root / "frontend/index.html").read_text(encoding="utf8")
    assert "PowerBid Studio" in policy
    assert 'href="/privacy"' in homepage
    assert "PowerBid Studio" in entry
