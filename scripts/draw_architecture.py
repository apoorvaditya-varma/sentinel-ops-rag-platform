"""Render docs/architecture.svg (platform architecture diagram): `python -m scripts.draw_architecture`.

Plain SVG so it displays everywhere (GitHub, VS Code, browsers, Word/PDF export)
without Mermaid support.
"""

from __future__ import annotations

from html import escape

from src.config import PROJECT_ROOT

W, H = 1280, 1010
STYLE = {
    "ui": ("#eef2ff", "#4f46e5"),
    "ingest": ("#e8f1fb", "#2563eb"),
    "query": ("#f3edfc", "#7c3aed"),
    "guard": ("#fdecec", "#dc2626"),
    "ok": ("#e7f6ec", "#16a34a"),
    "warn": ("#fff6e0", "#d97706"),
    "bad": ("#fdecec", "#dc2626"),
    "store": ("#f3f4f6", "#4b5563"),
    "ext": ("#e6f6f6", "#0d9488"),
}
parts: list[str] = []


def box(x, y, w, h, title, sub="", kind="ingest", title_size=14):
    fill, stroke = STYLE[kind]
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
    ty = y + (h / 2 + 5 if not sub else 19)
    parts.append(f'<text x="{x + w / 2}" y="{ty}" class="t" font-size="{title_size}">{escape(title)}</text>')
    if sub:
        parts.append(f'<text x="{x + w / 2}" y="{y + 36}" class="s">{escape(sub)}</text>')


def arrow(points, dashed=False, color="#374151", label="", label_at=None):
    d = " ".join(f"{'M' if i == 0 else 'L'}{x},{y}" for i, (x, y) in enumerate(points))
    dash = ' stroke-dasharray="5,4"' if dashed else ""
    parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.6"{dash} marker-end="url(#arrow)"/>')
    if label:
        lx, ly = label_at or points[len(points) // 2]
        parts.append(f'<text x="{lx}" y="{ly}" class="l">{escape(label)}</text>')


def down(x, y1, y2, **kw):
    arrow([(x, y1), (x, y2)], **kw)


# Frame, title, local-machine boundary
parts.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
parts.append(f'<text x="{W / 2}" y="34" class="t" font-size="22">Sentinel Ops RAG Platform — Architecture</text>')
parts.append('<rect x="20" y="52" width="1240" height="840" rx="12" fill="none" stroke="#9ca3af" stroke-dasharray="8,6"/>')
parts.append('<text x="36" y="72" class="hs">LOCAL MACHINE (no Docker, no servers)</text>')

# UI layer
box(40, 86, 150, 60, "User", "browser", "ui")
box(240, 86, 1000, 60, "Web UI + REST API  (FastAPI · Jinja · HTMX)", "Ask with history  ·  Documents  ·  Settings  ·  light / dark themes  ·  /api/* + OpenAPI docs", "ui")
arrow([(190, 116), (240, 116)])

# Column headers
parts.append('<text x="330" y="176" class="h">INGESTION PATH (Tasks 3-5, 9)</text>')
parts.append('<text x="950" y="176" class="h">QUERY PATH (Tasks 6-9)</text>')

# Ingestion path
L, LW = 50, 560
ing = [
    (190, "1  File-type guardrail", "allow-list · magic bytes · macro / zip-bomb / double-extension · size", "guard"),
    (256, "2  Quarantine staging", "data/uploads/.staging — nothing reaches the index unscreened", "ingest"),
    (322, "3  Parse (loaders)", "PDF · DOCX · TXT · MD · LOG · CSV · XLSX · JSON · YAML", "ingest"),
    (388, "4  Content scan", "secrets (keys, tokens, passwords) · prompt injection · duplicates", "guard"),
    (454, "5  Domain relevance", "local embedding margin vs off-topic  →  fast LLM only if borderline", "guard"),
]
for y, title, sub, kind in ing:
    box(L, y, LW, 46, title, sub, kind)
for (y1, *_), (y2, *_) in zip(ing, ing[1:]):
    down(L + LW / 2, y1 + 46, y2)
down(L + LW / 2, 500, 524)
box(50, 524, 176, 40, "Accepted", kind="ok")
box(242, 524, 176, 40, "Needs review", kind="warn")
box(434, 524, 176, 40, "Rejected + reason", kind="bad")
arrow([(330, 564), (330, 584), (138, 584), (138, 604)], label="", dashed=True, color="#d97706")
parts.append('<text x="250" y="580" class="l">"Ingest anyway"</text>')
down(138, 564, 604)
box(L, 604, LW, 46, "6  Chunk · redact secrets · tag untrusted text", "promoted to data/uploads/  →  recursive splitter, table row-groups", "ingest")
box(50, 670, 270, 46, "7  Embed", "dense bge-small + sparse BM25", "ingest")
box(340, 670, 270, 46, "7  Load tables", "CSV / Excel sheets → DuckDB", "ingest")
down(185, 650, 670)
down(520, 650, 670)

# Query path
R, RW = 670, 560
box(R, 190, RW, 46, "Input guard", "override / prompt-extraction attempts · secrets masked · length", "guard")
box(R, 256, RW, 46, "Supervisor agent  (fast LLM)", "intent · standalone question · plan of specialists (registry)", "query")
box(R, 322, 270, 46, "Document Researcher", "hybrid search tool → rerank → ID pinning", "query")
box(960, 322, 270, 46, "Data Analyst  (tool agent)", "list_tables · describe_table · run_sql", "query")
box(R, 388, 270, 46, "Grade passages  (fast LLM)", "is the evidence sufficient?", "query")
box(R, 454, 270, 46, "Rewrite query", "bounded retries", "query")
box(960, 388, 270, 46, "DuckDB sandbox", "SELECT-only · no file/network", "guard")
box(R, 524, RW, 46, "Answer Writer  (strong LLM)", "only from findings · cites [S#] passages and [T#] query results", "query")
box(R, 590, RW, 46, "Reviewer  (fast LLM)", "every claim grounded? send back once, else caveat", "guard")
box(R, 656, RW, 46, "Output guard", "secret masking · invalid citations removed · caveats", "guard")
down(R + RW / 2, 236, 256)
down(805, 302, 322)
down(1095, 302, 322)
parts.append('<text x="950" y="315" class="l">plan</text>')
down(805, 368, 388)
arrow([(805, 434), (805, 454)], label="")
parts.append('<text x="868" y="448" class="l">insufficient</text>')
arrow([(R, 477), (R - 14, 477), (R - 14, 345), (R, 345)], color="#7c3aed", label="")
arrow([(940, 335), (960, 335)], color="#7c3aed")
parts.append('<text x="950" y="378" class="l">findings</text>')
arrow([(940, 411), (948, 411), (948, 524)], label="")
parts.append('<text x="985" y="485" class="l">sufficient</text>')
down(1095, 368, 388)
down(1095, 434, 524)
down(R + RW / 2, 570, 590)
arrow([(1230, 613), (1248, 613), (1248, 547), (1230, 547)], color="#dc2626")
down(R + RW / 2, 636, 656)
# Answer back to the UI
arrow([(R + RW, 679), (1252, 679), (1252, 160), (1100, 160), (1100, 146)], color="#4f46e5")
parts.append('<text x="1168" y="155" class="l">answer + sources</text>')
arrow([(720, 146), (720, 190)], color="#4f46e5")
parts.append('<text x="726" y="172" class="ls">question</text>')
arrow([(560, 146), (560, 190)], color="#4f46e5")
parts.append('<text x="566" y="172" class="ls">upload</text>')

# Data + local models layer
parts.append('<text x="36" y="772" class="hs">LOCAL DATA &amp; MODELS</text>')
box(50, 784, 150, 56, "data/uploads/", "accepted files", "store", 13)
box(215, 784, 200, 56, "Qdrant (embedded)", "hybrid dense + BM25 index", "store", 13)
box(430, 784, 180, 56, "DuckDB", "tables.duckdb", "store", 13)
box(R, 784, 270, 56, "FastEmbed ONNX models", "bge-small · BM25 · MiniLM reranker", "store", 13)
box(960, 784, 270, 56, "LangSmith (optional)", "tracing of every agent step", "store", 13)
arrow([(185, 716), (185, 748), (300, 748), (300, 784)])
down(520, 716, 784)
parts.append('<text x="242" y="742" class="l">index</text>')
arrow([(400, 784), (400, 762), (642, 762), (642, 360), (R, 360)], dashed=True, color="#4b5563")
arrow([(560, 784), (560, 770), (652, 770), (652, 312), (1095, 312), (1095, 322)], dashed=True, color="#4b5563")
parts.append('<text x="604" y="758" class="l">read</text>')

# External LLM API
box(R, 926, RW, 56, "Google Gemini API", "gemini-3.8-flash (strong)  ·  gemini-3.5-flash-lite (fast)  ·  swappable via .env", "ext")
arrow([(950, 926), (950, 892)], color="#0d9488")
parts.append('<text x="960" y="914" class="ls">HTTPS: only prompts + excerpts leave</text>')

# Legend
lx = 50
for kind, label in [("guard", "Guardrail"), ("ingest", "Ingestion"), ("query", "Agent / query"), ("store", "Data / model"), ("ext", "External API")]:
    fill, stroke = STYLE[kind]
    parts.append(f'<rect x="{lx}" y="944" width="16" height="16" rx="3" fill="{fill}" stroke="{stroke}"/>')
    parts.append(f'<text x="{lx + 22}" y="957" class="ls">{label}</text>')
    lx += 118

svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif">
<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/>
  </marker>
  <style>
    .t {{ text-anchor: middle; font-weight: 600; fill: #111827; }}
    .s {{ text-anchor: middle; font-size: 12px; fill: #374151; }}
    .h {{ text-anchor: middle; font-size: 12px; font-weight: 700; letter-spacing: 1px; fill: #6b7280; }}
    .hs {{ text-anchor: start; font-size: 12px; font-weight: 700; letter-spacing: 1px; fill: #6b7280; }}
    .ls {{ text-anchor: start; font-size: 12px; fill: #374151; }}
    .l {{ text-anchor: middle; font-size: 11.5px; fill: #374151; font-style: italic; }}
  </style>
</defs>
{chr(10).join(parts)}
</svg>
"""

if __name__ == "__main__":
    out = PROJECT_ROOT / "docs" / "architecture.svg"
    out.write_text(svg)
    print(f"Wrote {out}")
