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
