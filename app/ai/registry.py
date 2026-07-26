PROVIDER_REGISTRY = {
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "example_model": "gemini-2.5-flash",
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
    "ollama": {
        "label": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "example_model": "whatever you have pulled",
    },
    "custom": {
        "label": "Custom",
        "base_url": None,
        "example_model": None,
    },
}
