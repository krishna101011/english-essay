from app.config import is_production


def test_is_production_true_for_production():
    assert is_production("production") is True
    assert is_production("Production") is True
    assert is_production("  production  ") is True


def test_is_production_false_for_development_and_unknown():
    assert is_production("development") is False
    assert is_production("") is False
    assert is_production("staging") is False
