from difflib import SequenceMatcher

MAX_COMPARISON_CHARACTERS = 100_000


def compare_versions(before: str, after: str) -> list[dict]:
    """Return accessible word-level additions/removals without client-side diff work."""
    if len(before) + len(after) > MAX_COMPARISON_CHARACTERS:
        raise ValueError("These versions are too large to compare safely.")
    before_words = before.splitlines(keepends=True)
    after_words = after.splitlines(keepends=True)
    segments = []
    for tag, start_a, end_a, start_b, end_b in SequenceMatcher(None, before_words, after_words).get_opcodes():
        if tag in {"equal", "delete", "replace"} and before_words[start_a:end_a]:
            segments.append({"kind": "removed" if tag != "equal" else "unchanged", "text": "".join(before_words[start_a:end_a])})
        if tag in {"insert", "replace"} and after_words[start_b:end_b]:
            segments.append({"kind": "added", "text": "".join(after_words[start_b:end_b])})
    return segments
