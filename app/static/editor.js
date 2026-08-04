(function () {
    const form = document.querySelector("[data-submission-form]");
    if (!form) return;
    const content = document.getElementById("content");
    const csrf = form.querySelector('[name="csrf_token"]').value;
    const status = form.querySelector("[data-autosave-status]");
    const submitStatus = form.querySelector("[data-submit-status]");
    const target = form.querySelector("[data-target-word-count]");
    let draftId = form.dataset.draftId || null;
    let revision = form.dataset.draftRevision ? Number(form.dataset.draftRevision) : null;
    let saveTimer;
    let savePending = false;
    let sequence = 0;
    let latestAcceptedSequence = 0;

    const updateCounts = () => {
        const words = content.value.trim() ? content.value.trim().split(/\s+/).length : 0;
        form.querySelector("[data-word-count]").textContent = `${words} word${words === 1 ? "" : "s"}`;
        form.querySelector("[data-character-count]").textContent = `${content.value.length} characters`;
        const goal = Number(target.value);
        form.querySelector("[data-target-progress]").textContent = goal ? `${Math.min(100, Math.round(words / goal * 100))}% of target` : "";
    };
    const setAutosaveStatus = (message, error = false) => {
        status.textContent = message;
        status.classList.toggle("text-red-700", error);
        status.classList.toggle("text-slate-500", !error);
    };
    const body = () => new URLSearchParams({
        csrf_token: csrf,
        draft_id: draftId || "",
        document_id: form.dataset.documentId || "",
        base_version_id: form.dataset.baseVersionId || "",
        expected_revision: revision === null ? "" : String(revision),
        title: form.querySelector('[name="title"]')?.value || "",
        content: content.value,
        doc_type: form.querySelector('[name="doc_type"]:checked')?.value || "essay",
        book_title: form.querySelector('[name="book_title"]')?.value || "",
        author: form.querySelector('[name="author"]')?.value || "",
        target_word_count: target.value || "",
    });
    async function saveNow() {
        if (savePending) return false;
        savePending = true;
        const requestSequence = ++sequence;
        setAutosaveStatus("Saving draft…");
        try {
            const response = await fetch("/drafts/autosave", {method: "POST", headers: {"Content-Type": "application/x-www-form-urlencoded"}, body: body()});
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || "Draft could not be saved.");
            if (requestSequence >= latestAcceptedSequence) {
                latestAcceptedSequence = requestSequence;
                draftId = String(data.id);
                revision = data.revision;
                form.querySelector("[data-draft-id-input]").value = draftId;
                setAutosaveStatus("Saved.");
            }
            return true;
        } catch (error) {
            setAutosaveStatus(`${error.message} Your changes are still in this page.`, true);
            return false;
        } finally { savePending = false; }
    }
    const queueSave = () => { clearTimeout(saveTimer); setAutosaveStatus("Changes not yet saved."); saveTimer = setTimeout(saveNow, 1200); };
    form.querySelectorAll("input, textarea").forEach((input) => input.addEventListener("input", () => { updateCounts(); queueSave(); }));
    form.querySelectorAll("[data-doc-type]").forEach((radio) => radio.addEventListener("change", () => {
        document.getElementById("book-fields").classList.toggle("hidden", radio.value !== "book_chapter"); queueSave();
    }));
    const selectedType = form.querySelector("[data-doc-type]:checked");
    if (selectedType) document.getElementById("book-fields").classList.toggle("hidden", selectedType.value !== "book_chapter");
    updateCounts();
    document.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveNow(); } });
    window.addEventListener("beforeunload", (event) => { if (savePending || saveTimer) { event.preventDefault(); event.returnValue = ""; } });
    form.addEventListener("submit", async (event) => {
        event.preventDefault(); clearTimeout(saveTimer); submitStatus.classList.remove("hidden"); submitStatus.textContent = "Saving draft…";
        if (!(await saveNow())) return;
        submitStatus.textContent = "Checking grammar…";
        const button = form.querySelector("[data-submit-button]"); button.disabled = true; button.querySelector("[data-submit-label]").textContent = "Getting AI feedback…";
        setTimeout(() => { if (button.disabled) submitStatus.textContent = "Preparing suggestions…"; }, 700);
        form.submit();
    });
    window.editorDraft = {get id() { return draftId; }, get revision() { return revision; }, saveNow, content, setState(data) { draftId = String(data.id); revision = data.revision; form.querySelector("[data-draft-id-input]").value = draftId; }};
})();

(function () {
    const dataEl = document.getElementById("essay-data"); if (!dataEl) return;
    const state = JSON.parse(dataEl.textContent); let corrections = state.corrections.filter((c) => !state.ignored_correction_ids.includes(c.id));
    const form = document.querySelector("[data-submission-form]"); const textarea = document.getElementById("content");
    const labels = {spelling: "Spelling", punctuation: "Punctuation", grammar: "Grammar", sentence_structure: "Sentence structure", vocab: "Vocabulary"};
    const escape = (text) => { const d = document.createElement("div"); d.textContent = text; return d.innerHTML; };
    const focus = (c) => { textarea.focus(); textarea.setSelectionRange(c.start_offset, c.end_offset); textarea.scrollIntoView({behavior: "smooth", block: "center"}); };
    function render() {
        const list = document.getElementById("correction-list"); const text = document.getElementById("highlighted-text");
        let html = "", cursor = 0;
        corrections.slice().sort((a,b) => a.start_offset-b.start_offset).forEach((c) => { if (c.start_offset >= cursor && c.end_offset <= state.content.length) { html += escape(state.content.slice(cursor,c.start_offset)); html += `<mark class="rounded px-0.5 bg-yellow-100 border-b-2 border-yellow-400">${escape(state.content.slice(c.start_offset,c.end_offset))}</mark>`; cursor=c.end_offset; }});
        text.innerHTML = html + escape(state.content.slice(cursor)) || "<em>No text.</em>";
        list.innerHTML = corrections.map((c) => `<article class="border border-slate-200 rounded p-3" data-correction-id="${c.id}"><p><strong>${labels[c.category] || c.category}</strong>: <span class="line-through">${escape(c.original_text)}</span> → <span class="font-medium">${escape(c.suggested_text)}</span></p><p class="text-slate-600 mt-1">${escape(c.explanation)}</p><div class="mt-2 flex gap-3"><button type="button" class="text-indigo-700 underline" data-focus>Review in editor</button><button type="button" class="text-emerald-700 underline" data-apply>Apply</button><button type="button" class="text-slate-600 underline" data-ignore>Ignore</button></div><p class="text-red-700 text-xs mt-1" role="status" data-error></p></article>`).join("") || '<p class="text-slate-500">No active suggestions.</p>';
        list.querySelectorAll("article").forEach((item) => { const c = corrections.find((v) => v.id === Number(item.dataset.correctionId)); item.querySelector("[data-focus]").onclick=()=>focus(c); item.querySelector("[data-apply]").onclick=()=>act(c,"apply",item); item.querySelector("[data-ignore]").onclick=()=>act(c,"ignore",item); });
    }
    async function act(c, action, item) {
        if (!(await window.editorDraft.saveNow())) return; const id=window.editorDraft.id, revision=window.editorDraft.revision;
        const response=await fetch(`/drafts/${id}/corrections/${c.id}/${action}`, {method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"}, body:new URLSearchParams({csrf_token: form.querySelector('[name="csrf_token"]').value, expected_revision: revision})}); const data=await response.json();
        if (!response.ok) { item.querySelector("[data-error]").textContent=data.detail; return; }
        window.editorDraft.setState(data); form.dataset.draftRevision=data.revision; textarea.value=data.content; corrections=corrections.filter((v)=>v.id!==c.id); state.content=data.content; render(); textarea.dispatchEvent(new Event("input"));
    }
    render();
})();
