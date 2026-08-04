(function () {
    const dialog = document.getElementById("confirm-dialog");
    if (!dialog || typeof dialog.showModal !== "function") return;

    const titleEl = document.getElementById("confirm-dialog-title");
    const messageEl = document.getElementById("confirm-dialog-message");
    const acceptBtn = dialog.querySelector("[data-confirm-accept]");
    const cancelBtn = dialog.querySelector("[data-confirm-cancel]");

    function ask(title, message, acceptLabel) {
        return new Promise((resolve) => {
            titleEl.textContent = title || "Are you sure?";
            messageEl.textContent = message || "";
            acceptBtn.textContent = acceptLabel || "Delete";

            function onAccept() {
                cleanup();
                resolve(true);
            }
            function onCancel() {
                cleanup();
                resolve(false);
            }
            function onCancelEvent() {
                cleanup();
                resolve(false);
            }
            function cleanup() {
                acceptBtn.removeEventListener("click", onAccept);
                cancelBtn.removeEventListener("click", onCancel);
                dialog.removeEventListener("cancel", onCancelEvent);
                dialog.close();
            }

            acceptBtn.addEventListener("click", onAccept);
            cancelBtn.addEventListener("click", onCancel);
            dialog.addEventListener("cancel", onCancelEvent);
            dialog.showModal();
        });
    }

    document.querySelectorAll("form[data-confirm-title]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (form.dataset.confirmed === "true") return; // already confirmed - let it proceed
            event.preventDefault();
            ask(form.dataset.confirmTitle, form.dataset.confirmMessage, form.dataset.confirmAccept).then((confirmed) => {
                if (!confirmed) return;
                form.dataset.confirmed = "true";
                if (form.requestSubmit) form.requestSubmit();
                else form.submit();
            });
        });
    });
})();
