from app.auth.security import hash_password


def _login(client, email, password):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    return client.post(
        "/login", data={"email": email, "password": password, "csrf_token": token}, follow_redirects=False
    )


def test_anonymous_visitor_sees_landing_page_at_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Write better essays" in response.text
    assert 'name="robots" content="noindex' not in response.text


def test_logged_in_user_still_sees_editor_at_root(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    response = client.get("/")

    assert response.status_code == 200
    assert "Write something new" in response.text


def test_private_pages_are_noindex(client, user):
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    for path in ["/history", "/progress", "/practice", "/goals", "/vocab", "/settings"]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert 'name="robots" content="noindex, nofollow"' in response.text, path


def test_public_pages_render_and_are_indexable():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anon_client:
        for path, heading in [
            ("/how-it-works", "How it works"),
            ("/methodology", "Feedback methodology"),
            ("/privacy", "Privacy and AI data use"),
            ("/help", "Help &amp; FAQ"),
            ("/example-feedback", "Sample feedback report"),
        ]:
            response = anon_client.get(path)
            assert response.status_code == 200, path
            assert heading in response.text, path
            assert 'name="robots" content="noindex' not in response.text, path
            assert '<link rel="canonical"' in response.text, path
            assert 'property="og:title"' in response.text, path


def test_example_feedback_page_is_labeled_fictional(client):
    response = client.get("/example-feedback")
    assert response.status_code == 200
    assert "fictional" in response.text.lower()
    assert "demonstration purposes only" in response.text.lower()


def test_robots_txt_disallows_private_paths_and_references_sitemap(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "Disallow: /settings" in response.text
    assert "Disallow: /history" in response.text
    assert "Sitemap:" in response.text
    assert "/sitemap.xml" in response.text


def test_sitemap_xml_lists_public_paths(client):
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "xml" in response.headers["content-type"]
    assert "<urlset" in response.text
    assert "/how-it-works</loc>" in response.text
    assert "/privacy</loc>" in response.text
    # private pages must never appear in the sitemap
    assert "/settings</loc>" not in response.text
    assert "/history</loc>" not in response.text


def test_manifest_and_favicon_are_served(client):
    manifest = client.get("/static/site.webmanifest")
    assert manifest.status_code == 200
    favicon = client.get("/static/favicon.svg")
    assert favicon.status_code == 200
