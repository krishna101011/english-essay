(function () {
    const dataEl = document.getElementById("trend-chart-data");
    const container = document.getElementById("score-chart");
    if (!dataEl || !container) return;

    const points = JSON.parse(dataEl.textContent);
    if (points.length < 1) return;

    const width = container.clientWidth || 600;
    const height = 220;
    const padding = { top: 16, right: 16, bottom: 36, left: 32 };
    const plotW = width - padding.left - padding.right;
    const plotH = height - padding.top - padding.bottom;
    const barGap = 8;
    const barWidth = points.length > 0 ? Math.max(8, plotW / points.length - barGap) : 0;

    const xFor = (i) => padding.left + (i / Math.max(points.length, 1)) * plotW;
    const yFor = (score) => padding.top + (1 - score / 100) * plotH;

    const gridLines = [0, 25, 50, 75, 100]
        .map(
            (v) => `
        <line x1="${padding.left}" y1="${yFor(v).toFixed(1)}" x2="${width - padding.right}" y2="${yFor(v).toFixed(1)}"
              stroke="#e2e8f0" stroke-width="1" />
        <text x="${padding.left - 8}" y="${(yFor(v) + 4).toFixed(1)}" text-anchor="end" font-size="10" fill="#94a3b8">${v}</text>`
        )
        .join("");

    const bars = points
        .map((p, i) => {
            const x = xFor(i).toFixed(1);
            const y = yFor(p.avg_score).toFixed(1);
            const h = (padding.top + plotH - yFor(p.avg_score)).toFixed(1);
            const label = p.week_start.replace(/"/g, "&quot;");
            return `<g>
                <rect x="${x}" y="${y}" width="${barWidth.toFixed(1)}" height="${h}" rx="3" fill="#4f46e5" />
                <text x="${(parseFloat(x) + barWidth / 2).toFixed(1)}" y="${(parseFloat(y) - 6).toFixed(1)}"
                      text-anchor="middle" font-size="11" font-weight="600" fill="#4338ca">${Math.round(p.avg_score)}</text>
                <text x="${(parseFloat(x) + barWidth / 2).toFixed(1)}" y="${(padding.top + plotH + 16).toFixed(1)}"
                      text-anchor="middle" font-size="9" fill="#94a3b8">${label.slice(5)}</text>
            </g>`;
        })
        .join("");

    container.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" class="w-full" role="img" aria-label="Weekly average score bar chart">
            ${gridLines}
            ${bars}
        </svg>
    `;
})();
