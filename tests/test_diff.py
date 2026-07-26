from app.documents.diff import diff_paragraphs, split_paragraphs


def test_split_paragraphs_tracks_offsets():
    text = "First paragraph.\n\nSecond paragraph."
    paragraphs = split_paragraphs(text)
    assert [p["text"] for p in paragraphs] == ["First paragraph.", "Second paragraph."]
    assert text[paragraphs[0]["start"] : paragraphs[0]["end"]] == "First paragraph."
    assert text[paragraphs[1]["start"] : paragraphs[1]["end"]] == "Second paragraph."


def test_diff_paragraphs_no_changes():
    text = "One.\n\nTwo."
    changed_ranges, unchanged_pairs = diff_paragraphs(text, text)
    assert changed_ranges == []
    assert len(unchanged_pairs) == 2


def test_diff_paragraphs_detects_single_edited_paragraph():
    old = "First paragraph.\n\nSecond paragraph."
    new = "First paragraph.\n\nSecond paragraph, but edited."
    changed_ranges, unchanged_pairs = diff_paragraphs(old, new)

    assert len(unchanged_pairs) == 1
    assert unchanged_pairs[0][0]["text"] == "First paragraph."

    assert len(changed_ranges) == 1
    start, end = changed_ranges[0]
    assert new[start:end] == "Second paragraph, but edited."


def test_diff_paragraphs_shifts_offset_of_unchanged_later_paragraph():
    old = "Short.\n\nUnchanged paragraph."
    new = "Much longer first paragraph now.\n\nUnchanged paragraph."
    changed_ranges, unchanged_pairs = diff_paragraphs(old, new)

    assert len(unchanged_pairs) == 1
    old_p, new_p = unchanged_pairs[0]
    assert old_p["text"] == new_p["text"] == "Unchanged paragraph."
    assert new_p["start"] != old_p["start"]


def test_diff_paragraphs_paragraph_count_change_treats_whole_doc_as_changed():
    old = "One paragraph only."
    new = "One paragraph only.\n\nA newly added paragraph."
    changed_ranges, unchanged_pairs = diff_paragraphs(old, new)

    assert changed_ranges == [[0, len(new)]]
    assert unchanged_pairs == []
