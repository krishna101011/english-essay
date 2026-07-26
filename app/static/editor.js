(function () {
    const dataEl = document.getElementById("essay-data");
    if (!dataEl) return;

    const { content, corrections } = JSON.parse(dataEl.textContent);

    const CATEGORY_STYLES = {
        spelling: "bg-red-100 border-b-2 border-red-400",
        punctuation: "bg-orange-100 border-b-2 border-orange-400",
        grammar: "bg-yellow-100 border-b-2 border-yellow-400",
        sentence_structure: "bg-blue-100 border-b-2 border-blue-400",
        vocab: "bg-purple-100 border-b-2 border-purple-400",
    };

    const CATEGORY_LABELS = {
        spelling: "Spelling",
        punctuation: "Punctuation",
        grammar: "Grammar",
        sentence_structure: "Sentence structure",
        vocab: "Vocabulary",
    };

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    function renderHighlightedText() {
        const container = document.getElementById("highlighted-text");
        const sorted = [...corrections].sort((a, b) => a.start_offset - b.start_offset);

        let html = "";
        let cursor = 0;
        for (const c of sorted) {
            if (c.start_offset < cursor || c.start_offset >= c.end_offset || c.end_offset > content.length) {
                continue; // skip overlapping/out-of-range corrections defensively
            }
            html += escapeHtml(content.slice(cursor, c.start_offset));
            const cls = CATEGORY_STYLES[c.category] || "bg-slate-200";
            const title = escapeHtml(`${CATEGORY_LABELS[c.category] || c.category}: ${c.explanation}`);
            html += `<mark class="${cls} rounded px-0.5" title="${title}">${escapeHtml(content.slice(c.start_offset, c.end_offset))}</mark>`;
            cursor = c.end_offset;
        }
        html += escapeHtml(content.slice(cursor));
        container.innerHTML = html || "<em>No text.</em>";
    }

    function renderCorrectionList() {
        const list = document.getElementById("correction-list");
        if (corrections.length === 0) {
            list.innerHTML = '<li class="text-slate-500">No issues found.</li>';
            return;
        }
        list.innerHTML = corrections
            .map((c) => {
                const cls = CATEGORY_STYLES[c.category] || "bg-slate-200";
                const label = CATEGORY_LABELS[c.category] || c.category;
                const suggestion = c.suggested_text
                    ? `<span class="text-slate-400">→</span> <span class="font-medium">${escapeHtml(c.suggested_text)}</span>`
                    : "";
                return `<li class="border border-slate-200 rounded p-2">
                    <span class="inline-block text-xs font-medium px-2 py-0.5 rounded ${cls} mr-2">${label}</span>
                    <span class="line-through text-slate-500">${escapeHtml(c.original_text)}</span>
                    ${suggestion}
                    <p class="text-slate-600 mt-1">${escapeHtml(c.explanation)}</p>
                </li>`;
            })
            .join("");
    }

    renderHighlightedText();
    renderCorrectionList();
})();
