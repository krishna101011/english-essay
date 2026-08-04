(function () {
    const providerSelect = document.getElementById("provider");
    const modelInput = document.getElementById("model_name");
    if (!providerSelect || !modelInput) return;

    function updatePlaceholder() {
        const selected = providerSelect.options[providerSelect.selectedIndex];
        const exampleModel = selected ? selected.dataset.exampleModel : "";
        modelInput.placeholder = exampleModel ? `e.g. ${exampleModel}` : "e.g. your model";
    }

    providerSelect.addEventListener("change", updatePlaceholder);
})();

(function () {
    const form = document.querySelector("[data-delete-account-form]");
    if (!form) return;
    const input = form.querySelector("[data-delete-confirm-input]");
    const submitBtn = form.querySelector("[data-delete-submit]");
    const hint = document.getElementById("delete-confirm-hint");
    const expected = (form.dataset.confirmEmail || "").trim().toLowerCase();

    function update() {
        const matches = input.value.trim().toLowerCase() === expected && expected !== "";
        submitBtn.disabled = !matches;
        hint.textContent = matches ? "Looks good." : "Must exactly match your account email.";
    }

    input.addEventListener("input", update);
    update();
})();
