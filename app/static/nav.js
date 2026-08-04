(function () {
    const toggle = document.querySelector("[data-nav-toggle]");
    const links = document.querySelector("[data-nav-links]");
    if (!toggle || !links) return;

    const setOpen = (open) => {
        toggle.setAttribute("aria-expanded", String(open));
        links.classList.toggle("hidden", !open);
        // "hidden" alone only clears the flex display added at the `sm:`
        // breakpoint (sm:flex) - below that breakpoint the container falls
        // back to the browser's default block display for a <div>, which
        // makes `flex-col` a no-op and lets the links wrap like plain text.
        // Toggling a bare `flex` class here keeps `flex-col` in effect on
        // small screens too.
        links.classList.toggle("flex", open);
    };

    toggle.addEventListener("click", () => {
        setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });

    links.querySelectorAll("a, button").forEach((el) => {
        el.addEventListener("click", () => setOpen(false));
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
            setOpen(false);
            toggle.focus();
        }
    });

    const mobileQuery = window.matchMedia("(min-width: 640px)");
    mobileQuery.addEventListener("change", (event) => {
        if (event.matches) setOpen(false);
    });
})();
