import ipaddress
import socket
from urllib.parse import urlsplit

from app.config import ALLOW_CUSTOM_AI_ENDPOINTS

# Bring-your-own-key failover: a user can configure several providers and
# have requests automatically move on to the next one when one is
# rate-limited or otherwise unavailable (see app/ai/failover.py). Capped so
# the failover loop and the settings page both stay bounded.
MAX_AI_PROVIDERS_PER_USER = 5


PROVIDER_REGISTRY = {
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "example_model": "gemini-3.6-flash",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "example_model": "llama-3.3-70b-versatile",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "example_model": "any *:free model",
    },
}


def available_providers() -> dict:
    providers = dict(PROVIDER_REGISTRY)
    if ALLOW_CUSTOM_AI_ENDPOINTS:
        providers["custom"] = {
            "label": "Custom HTTPS endpoint",
            "base_url": None,
            "example_model": None,
        }
    return providers


def validate_custom_base_url(value: str) -> str:
    """Permit custom endpoints only on explicit trusted deployments.

    DNS is resolved before accepting the URL to prevent obvious SSRF targets.
    The runtime validates the value again before every call; custom endpoints
    remain opt-in because a complete DNS-rebinding defence needs egress policy.
    """
    if not ALLOW_CUSTOM_AI_ENDPOINTS:
        raise ValueError("Custom AI endpoints are disabled on this deployment.")
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise ValueError("Enter a valid HTTPS API URL.") from exc
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Custom AI endpoints must use a public HTTPS URL without embedded credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("Custom AI endpoint URLs cannot include query strings or fragments.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError("The custom AI endpoint hostname could not be resolved.") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Custom AI endpoints must resolve only to public internet addresses.")
    return value.strip().rstrip("/")


def resolve_provider_base_url(provider: str, supplied_base_url: str) -> str:
    if provider in PROVIDER_REGISTRY:
        # Approved endpoints are fixed by the server. Ignore form tampering.
        return PROVIDER_REGISTRY[provider]["base_url"]
    if provider == "custom":
        return validate_custom_base_url(supplied_base_url)
    raise ValueError("Choose one of the supported AI providers.")
