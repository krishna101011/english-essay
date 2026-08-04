import pytest

from app.ai.crypto import encrypt_api_key, mask_api_key
from app.ai.registry import PROVIDER_REGISTRY
from app.auth.security import hash_password
from app.db import models

# Providers with one canonical hosted default model - a blank or placeholder
# example_model here means the Settings page has nothing real to suggest.
# OpenRouter ("pick any free model") and Ollama (whatever the user has
# pulled locally) don't have a single correct default by design, and
# "custom" is the deliberate bring-your-own-everything fallback - none of
# those three are expected to carry a concrete model id.
PROVIDERS_WITH_A_CANONICAL_DEFAULT_MODEL = ["gemini", "groq"]

# Generic phrases that read as instructions rather than a real, pasteable
# model id - catches a preset shipping descriptive text instead of a model.
PLACEHOLDER_PHRASES = ["default", "example", "whatever", "any ", "your model", "model name"]


@pytest.mark.parametrize("provider_key", PROVIDERS_WITH_A_CANONICAL_DEFAULT_MODEL)
def test_provider_has_a_concrete_non_placeholder_default_model(provider_key):
    example_model = PROVIDER_REGISTRY[provider_key]["example_model"]

    assert example_model, f"{provider_key} has no default model set"
    assert " " not in example_model, (
        f"{provider_key}'s default model {example_model!r} looks like a descriptive phrase, not a real model id"
    )
    lowered = example_model.lower()
    for phrase in PLACEHOLDER_PHRASES:
        assert phrase not in lowered, f"{provider_key}'s default model {example_model!r} looks like a placeholder"


def test_gemini_default_model_is_the_current_one():
    # Regression guard for the actual bug this repo has shipped twice now:
    # a stale/placeholder model string sitting uncaught in the registry.
    assert PROVIDER_REGISTRY["gemini"]["example_model"] == "gemini-3.6-flash"


def test_groq_default_model_and_base_url():
    assert PROVIDER_REGISTRY["groq"]["example_model"] == "llama-3.3-70b-versatile"
    assert PROVIDER_REGISTRY["groq"]["base_url"] == "https://api.groq.com/openai/v1"


def _login(client, email, password):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def test_settings_page_placeholder_matches_registry_for_default_provider(client, user):
    # A brand-new user has no AISettings row yet, so the provider <select>
    # falls back to whichever provider is first in the registry (gemini).
    # Regression guard for the actual bug: the placeholder used to be a
    # string hardcoded directly in settings.html, disconnected from
    # PROVIDER_REGISTRY - this asserts against the registry value itself,
    # not a literal, so it fails the moment the two drift apart again.
    user.password_hash = hash_password("correct-horse-battery-staple")
    _login(client, user.email, "correct-horse-battery-staple")

    response = client.get("/settings")

    assert response.status_code == 200
    expected = PROVIDER_REGISTRY["gemini"]["example_model"]
    assert f'placeholder="e.g. {expected}"' in response.text


def test_settings_page_lists_existing_provider_and_add_form_stays_registry_default(client, db_session, user):
    # The "add another provider" form is always a blank, provider-agnostic
    # form now (settings support a prioritized list, not a single
    # save/overwrite row) - it should keep defaulting to the registry's
    # first provider regardless of what's already configured. What actually
    # needs to reflect an existing groq row is the providers list below it.
    user.password_hash = hash_password("correct-horse-battery-staple")
    ai_settings = models.AISettings(
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("sk-fake-key"),
        model_name="llama-3.3-70b-versatile",
        base_url=PROVIDER_REGISTRY["groq"]["base_url"],
    )
    db_session.add(ai_settings)
    db_session.commit()

    _login(client, user.email, "correct-horse-battery-staple")

    response = client.get("/settings")

    assert response.status_code == 200
    assert "llama-3.3-70b-versatile" in response.text
    assert mask_api_key("sk-fake-key") in response.text

    default_expected = PROVIDER_REGISTRY["gemini"]["example_model"]
    assert f'placeholder="e.g. {default_expected}"' in response.text
    # Every <option> in the add-provider select should still carry its own
    # model as a data attribute - this is what settings.js reads on
    # provider change, so the dynamic (JS-driven) placeholder update stays
    # sourced from the same registry value too, not a second hardcoded copy.
    groq_expected = PROVIDER_REGISTRY["groq"]["example_model"]
    assert f'data-example-model="{groq_expected}"' in response.text
