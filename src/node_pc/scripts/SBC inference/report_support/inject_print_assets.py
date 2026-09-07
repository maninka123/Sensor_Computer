"""Inject static chart fallbacks and print-only layout fixes into report HTML."""

from __future__ import annotations

import base64
from pathlib import Path


ROOT = Path(__file__).resolve().parent
HTML = ROOT / "ROCK5A_CPU_Optimization_Report.html"


def data_uri(name: str) -> str:
    encoded = base64.b64encode((ROOT / "charts" / name).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


html = HTML.read_text(encoding="utf-8")
marker = "</style>"
css = """
/* PDF report print assets: reproducible static charts and bounded audit tables. */
.report-static-chart{display:none;width:100%;height:auto;margin:4px 0 8px}
@media print{
  .report-static-chart{display:block!important;break-inside:avoid}
  [data-artifact-id=\"latency_chart\"]>.portable-table-scroll,
  [data-artifact-id=\"size_chart\"]>.portable-table-scroll{display:none!important}
  [data-artifact-id=\"change_table\"] .portable-table-scroll{overflow:visible!important}
  [data-artifact-id=\"change_table\"] table{width:100%!important;min-width:0!important;table-layout:fixed!important}
  [data-artifact-id=\"change_table\"] th,
  [data-artifact-id=\"change_table\"] td{padding:5px 7px 5px 0!important;font-size:9px!important;line-height:13px!important;white-space:normal!important;overflow:visible!important;text-overflow:clip!important;overflow-wrap:anywhere}
  [data-artifact-id=\"change_table\"] th:nth-child(1),
  [data-artifact-id=\"change_table\"] td:nth-child(1){width:5%}
  [data-artifact-id=\"change_table\"] th:nth-child(2),
  [data-artifact-id=\"change_table\"] td:nth-child(2){width:22%}
  [data-artifact-id=\"change_table\"] th:nth-child(3),
  [data-artifact-id=\"change_table\"] td:nth-child(3){width:25%}
  [data-artifact-id=\"change_table\"] th:nth-child(4),
  [data-artifact-id=\"change_table\"] td:nth-child(4){width:26%}
  [data-artifact-id=\"change_table\"] th:nth-child(5),
  [data-artifact-id=\"change_table\"] td:nth-child(5){width:22%}
}
"""
if css.strip() not in html:
    html = html.replace(marker, css + marker, 1)

charts = {
    "latency_chart": ("latency_by_threads.png", "Grouped bar chart of median latency by backend and thread count"),
    "size_chart": ("artifact_sizes.png", "Bar chart of original checkpoint, TorchScript, and ONNX file sizes"),
}
for chart_id, (filename, alt) in charts.items():
    anchor = f'data-chart-id="{chart_id}"'
    start = html.index(anchor)
    source_end = html.index("</div></div>", start) + len("</div></div>")
    tag = f'<img class="report-static-chart" src="{data_uri(filename)}" alt="{alt}">'
    if tag not in html:
        html = html[:source_end] + tag + html[source_end:]

# The generic formatter rounds the tiny absolute error to zero. Use ppm in the
# visible print fallback while retaining the exact value in the summary narrative.
error_card_start = html.index('Maximum output error</p>')
error_value_start = html.index('<span class="portable-source-value-text">', error_card_start)
error_value_end = html.index('</span>', error_value_start)
html = (
    html[:error_value_start]
    + '<span class="portable-source-value-text">0.417 ppm'
    + html[error_value_end:]
)
html = html.replace(
    'Maximum floating-point error</td><td>0</td>',
    'Maximum floating-point error</td><td>4.17 x 10^-7</td>',
    1,
)
html = html.replace(
    'Mean floating-point error</td><td>0</td>',
    'Mean floating-point error</td><td>3.91 x 10^-8</td>',
    1,
)
HTML.write_text(html, encoding="utf-8")
print(f"Updated print representation in {HTML}")
