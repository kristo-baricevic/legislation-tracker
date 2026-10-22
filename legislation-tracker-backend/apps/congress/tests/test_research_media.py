import io
from types import SimpleNamespace
import pytest
from apps.congress.models import Representative

pytestmark = pytest.mark.django_db


def test_source_fetch_rejects_private_dns_and_redirects(monkeypatch):
    from apps.research.sources import fetch_bytes, SourceUnavailable
    monkeypatch.setattr("apps.research.sources.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(SourceUnavailable, match="private_destination"):
        fetch_bytes("https://member.house.gov/about", "member.house.gov", 1000)
    with pytest.raises(SourceUnavailable, match="invalid_source"):
        fetch_bytes("https://member.house.gov@evil.test/about", "member.house.gov", 1000)
    monkeypatch.setattr("apps.research.sources.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    class Pool:
        def __init__(self, host, **kw):
            assert host == "8.8.8.8" and kw["server_hostname"] == "member.house.gov"
        def request(self, *a, **kw):
            return SimpleNamespace(status=302, headers={"Location": "http://127.0.0.1"}, close=lambda: None)
        def close(self): pass
    monkeypatch.setattr("apps.research.sources.HTTPSConnectionPool", Pool)
    with pytest.raises(SourceUnavailable, match="source_status"):
        fetch_bytes("https://member.house.gov/about", "member.house.gov", 1000)


def test_approved_html_is_identity_bound_and_strips_navigation(monkeypatch):
    from apps.research.sources import parse_biography, SourceUnavailable
    text = parse_biography(b'<nav>Donate now</nav><main id="bio"><script>bad()</script><p>Jane Doe represents New York.</p><p>She previously served in the state senate.</p></main>', "bio", "Jane Doe")
    assert text == "Jane Doe represents New York. She previously served in the state senate."
    with pytest.raises(SourceUnavailable, match="identity_mismatch"):
        parse_biography(b'<main id="bio">Other Person serves in Congress.</main>', "bio", "Jane Doe")
    with pytest.raises(SourceUnavailable, match="biography_unavailable"):
        parse_biography(b'<main id="changed">Jane Doe serves.</main>', "bio", "Jane Doe")


def test_portrait_is_sanitized_and_persisted_only_with_reuse_approval(tmp_path, settings):
    from PIL import Image
    from django.core.files.storage import default_storage
    from apps.research.portraits import sanitize_portrait, save_portrait
    from apps.research.models import ResearchSourcePolicy
    settings.STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": str(tmp_path)}}}
    rep = Representative.objects.create(bioguide_id="T000041", name="Jane Doe", chamber="house", state="NY")
    url = "https://www.congress.gov/img/member/t000041.jpg"
    buf = io.BytesIO(); Image.new("RGB", (50, 70), "blue").save(buf, format="PNG")
    prepared = sanitize_portrait(buf.getvalue())
    assert prepared[1:] == (50, 70)
    with pytest.raises(ValueError): sanitize_portrait(b'<svg onload="alert(1)"></svg>')
    policy = ResearchSourcePolicy.objects.create(representative=rep, kind="portrait", url=url, attribution="Official portrait", license="Permission recorded", approved=False)
    original = save_portrait(rep, {"imageUrl": url}, prepared=prepared, policy=policy)
    assert not original.object_key
    policy.approved = True; policy.save()
    stored = save_portrait(rep, {"imageUrl": url}, prepared=prepared, policy=policy)
    assert default_storage.exists(stored.object_key)
    assert stored.width == 50 and stored.height == 70 and stored.mime_type == "image/png"
    assert save_portrait(rep, {"imageUrl": url}, prepared=prepared, policy=policy).pk == stored.pk
    from rest_framework.test import APIClient
    response = APIClient().get(f"/api/representatives/{rep.pk}/portraits/{stored.pk}/")
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert b"".join(response.streaming_content).startswith(b"\x89PNG")
    assert APIClient().get(f"/api/representatives/{rep.pk+1}/portraits/{stored.pk}/").status_code == 404
    policy.approved = False
    policy.save()
    assert APIClient().get(f"/api/representatives/{rep.pk}/portraits/{stored.pk}/").status_code == 404
    saved = APIClient().get(f"/api/representatives/{rep.pk}/research/?period=2026")
    assert saved.data["portrait"]["url"] == url


@pytest.mark.parametrize("headers,body", [({"Content-Encoding": "gzip"}, b"compressed"), ({"Content-Type": "text/plain"}, b"x" * 1001)])
def test_source_fetch_rejects_compression_and_overflow(monkeypatch, headers, body):
    from apps.research.sources import fetch_bytes, SourceUnavailable
    monkeypatch.setattr("apps.research.sources.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    stream = io.BytesIO(body)
    class Pool:
        def __init__(self, *a, **kw): pass
        def request(self, *a, **kw): return SimpleNamespace(status=200, headers=headers, read=lambda *a, **kw: stream.read(a[0]), close=lambda: None)
        def close(self): pass
    monkeypatch.setattr("apps.research.sources.HTTPSConnectionPool", Pool)
    with pytest.raises(SourceUnavailable): fetch_bytes("https://member.house.gov/a", "member.house.gov", 1000)
