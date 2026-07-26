import shutil
from functools import lru_cache

import language_tool_python

JAVA_MISSING_MESSAGE = (
    "LanguageTool requires a local Java runtime (Java 17+), but no `java` "
    "executable was found on PATH. Install a JRE — e.g. "
    "https://adoptium.net/ — then restart the app."
)

_CATEGORY_MAP = {
    "TYPOS": "spelling",
    "PUNCTUATION": "punctuation",
}


class JavaNotFoundError(RuntimeError):
    pass


@lru_cache
def _get_tool() -> "language_tool_python.LanguageTool":
    if shutil.which("java") is None:
        raise JavaNotFoundError(JAVA_MISSING_MESSAGE)
    return language_tool_python.LanguageTool("en-US")


def check_text(text: str) -> list[dict]:
    """Run the local LanguageTool check and return findings shaped like the
    `corrections` table (minus `source`, which callers set to "local")."""
    tool = _get_tool()
    findings = []
    for match in tool.check(text):
        start = match.offset
        end = match.offset + match.error_length
        category = _CATEGORY_MAP.get(match.category, "grammar")
        suggested = match.replacements[0] if match.replacements else ""
        findings.append(
            {
                "category": category,
                "start_offset": start,
                "end_offset": end,
                "original_text": text[start:end],
                "suggested_text": suggested,
                "explanation": match.message,
            }
        )
    return findings
