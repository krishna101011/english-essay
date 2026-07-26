(function () {
    const dataEl = document.getElementById("score-chart-data");
    const container = document.getElementById("score-chart");
    if (!dataEl || !container) return;

    const points = JSON.parse(dataEl.textContent);
    if (points.length < 2) return;

    const width = container.clientWidth || 600;
    const height = 220;
    const padding = { top: 16, right: 16, bottom: 28, left: 32 };
    const plotW = width - padding.left - padding.right;
    const plotH = height - padding.top - padding.bottom;

    const xFor = (i) => padding.left + (i / (points.length - 1)) * plotW;
    const yFor = (score) => padding.top + (1 - score / 100) * plotH;

    const linePath = points
        .map((p, i) => `${i === 0 ? "M" : "L"} ${xFor(i).toFixed(1)} ${yFor(p.score).toFixed(1)}`)
        .join(" ");

    const gridLines = [0, 25, 50, 75, 100]
        .map(
            (v) => `
        <line x1="${padding.left}" y1="${yFor(v).toFixed(1)}" x2="${width - padding.right}" y2="${yFor(v).toFixed(1)}"
              stroke="#e2e8f0" stroke-width="1" />
        <text x="${padding.left - 8}" y="${yFor(v).toFixed(1) + 4}" text-anchor="end" font-size="10" fill="#94a3b8">${v}</text>`
        )
        .join("");

    const dots = points
        .map((p, i) => {
            const cx = xFor(i).toFixed(1);
            const cy = yFor(p.score).toFixed(1);
            const title = p.title.replace(/"/g, "&quot;");
            return `<g class="score-dot" data-title="${title}" data-date="${p.date}" data-score="${p.score}">
                        <circle cx="${cx}" cy="${cy}" r="10" fill="transparent" />
                        <circle cx="${cx}" cy="${cy}" r="4" fill="#4f46e5" stroke="white" stroke-width="1.5" />
                    </g>`;
        })
        .join("");

    const last = points[points.length - 1];
    const lastLabel = `<text x="${xFor(points.length - 1).toFixed(1)}" y="${(yFor(last.score) - 10).toFixed(1)}"
                            text-anchor="end" font-size="12" font-weight="600" fill="#4338ca">${Math.round(last.score)}</text>`;

    container.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" class="w-full" role="img" aria-label="Overall score over time">
            ${gridLines}
            <path d="${linePath}" fill="none" stroke="#4f46e5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
            ${dots}
            ${lastLabel}
        </svg>
        <div id="score-chart-tooltip" class="hidden whitespace-nowrap text-xs bg-slate-800 text-white rounded px-2 py-1 absolute pointer-events-none"></div>
    `;

    const tooltip = container.querySelector("#score-chart-tooltip");
    container.style.position = "relative";
    container.querySelectorAll(".score-dot").forEach((dot) => {
        dot.addEventListener("mouseenter", (e) => {
            tooltip.textContent = `${dot.dataset.title} — ${dot.dataset.date}: ${Math.round(dot.dataset.score)}`;
            tooltip.classList.remove("hidden");
        });
        dot.addEventListener("mousemove", (e) => {
            const rect = container.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const flip = x + 12 + tooltip.offsetWidth > rect.width;
            tooltip.style.left = flip ? `${x - tooltip.offsetWidth - 12}px` : `${x + 12}px`;
            tooltip.style.top = `${y + 12}px`;
        });
        dot.addEventListener("mouseleave", () => tooltip.classList.add("hidden"));
    });
})();
