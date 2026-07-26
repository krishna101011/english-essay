import re

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def split_paragraphs(text: str) -> list[dict]:
    """Split text into paragraphs, tracking each paragraph's [start, end) offset."""
    paragraphs = []
    pos = 0
    for chunk in _PARAGRAPH_SPLIT.split(text):
        start = text.index(chunk, pos) if chunk else pos
        end = start + len(chunk)
        paragraphs.append({"start": start, "end": end, "text": chunk})
        pos = end
    return paragraphs


def diff_paragraphs(previous_text: str, current_text: str) -> tuple[list[list[int]], list[tuple[dict, dict]]]:
    """Compare paragraph-by-paragraph against the previous version.

    Returns (changed_ranges, unchanged_pairs):
      - changed_ranges: [start, end) offsets in current_text of paragraphs
        that differ from the previous version (or are new).
      - unchanged_pairs: (old_paragraph, new_paragraph) dicts for paragraphs
        with identical text, so callers can carry forward old corrections
        and remap their offsets if the paragraph moved.

    If the paragraph count changed, alignment is ambiguous, so the whole
    document is treated as changed and nothing is carried forward.
    """
    old_paragraphs = split_paragraphs(previous_text)
    new_paragraphs = split_paragraphs(current_text)

    if len(old_paragraphs) != len(new_paragraphs):
        return [[0, len(current_text)]], []

    changed_ranges = []
    unchanged_pairs = []
    for old_p, new_p in zip(old_paragraphs, new_paragraphs):
        if old_p["text"] != new_p["text"]:
            changed_ranges.append([new_p["start"], new_p["end"]])
        else:
            unchanged_pairs.append((old_p, new_p))
    return changed_ranges, unchanged_pairs
