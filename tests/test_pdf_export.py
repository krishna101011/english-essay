from app.auth.security import hash_password
from app.db import models
from app.documents.pdf_export import build_essay_pdf


def _login(client, email, password):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    return client.post(
        "/login", data={"email": email, "password": password, "csrf_token": token}, follow_redirects=False
    )


def _version_with_score(db_session, document):
    version = models.DocumentVersion(document_id=document.id, content="Line one.\nLine two.", version_number=1)
    db_session.add(version)
    db_session.commit()
    db_session.add(
        models.Score(
            version_id=version.id,
            overall_score=80,
            grammar_score=80,
            vocab_score=80,
            structure_score=80,
            clarity_score=80,
            feedback_summary="Nice job.",
        )
    )
    db_session.commit()
    db_session.refresh(version)
    return version


def test_build_essay_pdf_produces_valid_pdf_bytes(db_session, document):
    version = _version_with_score(db_session, document)
    pdf_bytes = build_essay_pdf(document, version)
    assert pdf_bytes.startswith(b"%PDF")


def test_export_route_requires_login(client, db_session, document):
    version = _version_with_score(db_session, document)
    response = client.get(f"/documents/{document.id}/versions/{version.id}/export.pdf", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_export_route_is_owner_scoped(client, db_session, document):
    other = models.User(email="other-pdf@example.com", password_hash=hash_password("z"), email_verified=True)
    db_session.add(other)
    db_session.commit()
    version = _version_with_score(db_session, document)  # belongs to the `document` fixture's owner, not `other`

    _login(client, other.email, "z")
    response = client.get(f"/documents/{document.id}/versions/{version.id}/export.pdf", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/history"


def test_export_route_returns_pdf_for_owner(client, db_session, user, document):
    version = _version_with_score(db_session, document)
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    response = client.get(f"/documents/{document.id}/versions/{version.id}/export.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
