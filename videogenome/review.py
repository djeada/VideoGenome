"""A self-contained HTML review page written next to the programme.

It puts what a reviewer needs on one page: the video, the poster and contact
sheet, every gate with its evidence, the human gates still waiting for a
decision, where each asset came from, and (for ``create``) the brief and the
writer that proposed the copy. All job text is escaped; the page loads
nothing from the network and links only to sidecars in its own directory.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from videogenome.deliverables import _guard
from videogenome.plugins import Exporter

STATUS_TONE = {"passed": "good", "failed": "bad", "self_attested_approved": "good",
               "not_evaluated": "wait", "not_applicable": "muted"}

CSS = """
:root{--bg:#f6f5f2;--panel:#fff;--ink:#17181b;--soft:#5d6068;--line:#e3e1dc;--good:#1f7a4d;--bad:#b3261e;
--wait:#8a5a00;--muted:#6b6f78;--accent:#ff5a36;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0f1012;--panel:#17191c;--ink:#ecebe7;--soft:#a3a6ad;
--line:#2a2d32;--good:#5fd49a;--bad:#ff8a80;--wait:#f0b44c;--muted:#8d9199}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}h2{font-size:17px;margin:0 0 12px}
.sub{color:var(--soft);margin:0 0 20px}.banner{border-radius:10px;padding:12px 16px;margin:0 0 20px;
font-weight:600;border:1px solid var(--line);background:var(--panel)}
.banner.bad{border-color:var(--bad);color:var(--bad)}.banner.wait{border-color:var(--wait);color:var(--wait)}
.banner.good{border-color:var(--good);color:var(--good)}
.grid{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:20px}
@media (max-width:820px){.grid{grid-template-columns:1fr}}
section{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin:0 0 20px}
video,img{width:100%;border-radius:8px;background:#000;display:block}
video{max-height:70vh}.facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:0}
.facts div{border:1px solid var(--line);border-radius:8px;padding:10px}.facts dt{color:var(--soft);font-size:12px}
.facts dd{margin:2px 0 0;font-weight:600;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:8px 6px;
border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--soft);font-weight:500;font-size:12px}
.pill{display:inline-block;border-radius:99px;padding:1px 9px;font-size:12px;font-weight:600;
border:1px solid currentColor;white-space:nowrap}.good{color:var(--good)}.bad{color:var(--bad)}
.wait{color:var(--wait)}.muted{color:var(--muted)}code,pre{font:12.5px/1.45 ui-monospace,Menlo,Consolas,monospace}
pre{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;margin:0}
ul{margin:0;padding-left:20px}li{margin:4px 0}.wrap{overflow-x:auto}.hash{color:var(--soft)}
"""


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _pill(status: str) -> str:
    return f'<span class="pill {STATUS_TONE.get(status, "muted")}">{_e(status.replace("_", " "))}</span>'


def _local(path: str | None, page: Path) -> str | None:
    """Link only to files beside the page (sidecars share its directory)."""
    if not path:
        return None
    candidate = Path(path)
    return candidate.name if candidate.parent.resolve() == page.parent.resolve() else None


def review_html(receipt: dict, page: Path) -> str:
    gates = receipt.get("quality_gates", [])
    failed = [g for g in gates if g["status"] == "failed"]
    waiting = [g for g in gates if g["mode"] == "human" and g["status"] == "not_evaluated"]
    if failed:
        banner = ("bad", f"Automated gate failed: {', '.join(g['id'] for g in failed)}. Not ready to publish.")
    elif receipt.get("contains_placeholder_media"):
        banner = ("bad", "Contains placeholder media: an animatic for timing review, not for publication.")
    elif waiting:
        banner = ("wait", f"Technical checks passed. {len(waiting)} human review gate(s) still need an "
                          "authorized decision.")
    else:
        banner = ("good", "Technical checks passed and every human gate has a recorded approval.")
    video = _local(receipt.get("output_path"), page)
    deliverables = receipt.get("deliverables", {})
    poster = _local(deliverables.get("poster", {}).get("path"), page)
    contact = _local(deliverables.get("contact_sheet", {}).get("path"), page)
    measured = receipt.get("measurements", {})
    loudness = measured.get("integrated_lufs")
    peak = measured.get("true_peak_dbtp")
    facts = [
        ("Duration", f"{receipt.get('duration_observed_seconds', 0):.2f} s"),
        ("Frames", f"{receipt.get('frames_observed')} of {receipt.get('frames_planned')} planned"),
        ("Loudness", f"{loudness:.1f} LUFS" if isinstance(loudness, (int, float)) else "silent / not measured"),
        ("True peak", f"{peak:.1f} dBTP" if isinstance(peak, (int, float)) else "n/a"),
        ("Pipeline", (receipt.get("pipeline") or {}).get("id", "default")),
        ("Font", (receipt.get("font") or {}).get("resolved_family") or "n/a"),
    ]
    out = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        f"<title>Review {_e(receipt.get('job_id', ''))}</title><style>{CSS}</style></head><body><main>",
        f"<h1>{_e(receipt.get('job_id', 'Programme'))}</h1>",
        f"<p class=\"sub\">Template <code>{_e(receipt.get('template_id'))}</code> "
        f"v{_e(receipt.get('template_version'))}. Review page generated from the render receipt.</p>",
        f"<div class=\"banner {banner[0]}\">{_e(banner[1])}</div>",
        "<div class=\"grid\"><div>",
    ]
    if video:
        poster_attr = f' poster="{_e(poster)}"' if poster else ""
        out.append(f"<section><video controls preload=\"metadata\" src=\"{_e(video)}\"{poster_attr}></video></section>")
    if contact:
        out.append(f"<section><h2>Contact sheet</h2><img src=\"{_e(contact)}\" alt=\"One frame per shot\"></section>")
    out.append("</div><div>")
    out.append("<section><h2>Measured</h2><dl class=\"facts\">"
               + "".join(f"<div><dt>{_e(k)}</dt><dd>{_e(v)}</dd></div>" for k, v in facts) + "</dl></section>")
    if waiting:
        items = "".join(f"<li><strong>{_e(g['id'])}</strong>: {_e(g.get('description', ''))}</li>" for g in waiting)
        out.append("<section><h2>Waiting for a human decision</h2><ul>" + items + "</ul>"
                   "<p class=\"sub\" style=\"margin:10px 0 0\">After an authorized reviewer checks a gate, add its id "
                   "to <code>approved_gates</code> in the job and render again. Nothing here approves it.</p></section>")
    out.append("</div></div>")

    rows = []
    for gate in gates:
        evidence = gate.get("evidence") or {}
        detail = (f"{evidence.get('metric')} = {evidence.get('value')}" if "value" in evidence
                  else evidence.get("reason", ""))
        rows.append(f"<tr><td><code>{_e(gate['id'])}</code></td><td>{_e(gate['mode'])}</td>"
                    f"<td>{_pill(gate['status'])}</td><td>{_e(gate.get('description', ''))}"
                    + (f"<br><span class=\"hash\">{_e(detail)}</span>" if detail else "") + "</td></tr>")
    out.append("<section><h2>Quality gates</h2><div class=\"wrap\"><table><tr><th>Gate</th><th>Mode</th>"
               "<th>Status</th><th>What it checks</th></tr>" + "".join(rows) + "</table></div></section>")

    fill = receipt.get("fill")
    if fill:
        writer = fill.get("writer") or {}
        model = (writer.get("model") or {}).get("name") or writer.get("name")
        out.append(
            "<section><h2>Copy</h2>"
            f"<p>Written by <strong>{_e(model)}</strong> ({_e(writer.get('type'))}) in "
            f"{_e(fill.get('attempts'))} attempt(s). Slots it wrote: "
            f"{_e(', '.join(fill.get('written_inputs', [])) or 'none')}.</p>"
            f"<p class=\"sub\">{_e(fill.get('caveat', ''))}</p>"
            f"<pre>{_e(fill.get('brief', ''))}</pre></section>")

    asset_rows = []
    for asset_id, asset in sorted((receipt.get("assets") or {}).items()):
        generation = asset.get("generation") or {}
        made = ("placeholder" if generation.get("placeholder")
                else " -> ".join(generation.get("providers", [])) or "supplied")
        asset_rows.append(
            f"<tr><td><code>{_e(asset_id)}</code></td><td>{_e(asset.get('kind'))}</td>"
            f"<td>{_e(asset.get('origin', {}).get('type'))}<br><span class=\"hash\">"
            f"{_e(asset.get('origin', {}).get('description', ''))}</span></td>"
            f"<td>{_e(asset.get('rights', {}).get('license', ''))}</td><td>{_e(made)}</td>"
            f"<td class=\"hash\"><code>{_e(str(asset.get('sha256', ''))[:12])}</code></td></tr>")
    if asset_rows:
        out.append("<section><h2>Assets and provenance</h2><div class=\"wrap\"><table><tr><th>Asset</th>"
                   "<th>Kind</th><th>Origin</th><th>Licence</th><th>Made by</th><th>SHA-256</th></tr>"
                   + "".join(asset_rows) + "</table></div></section>")
    out.append("<section><h2>Caveats</h2><ul>"
               + "".join(f"<li>{_e(c)}</li>" for c in receipt.get("caveats", [])) + "</ul></section>")
    renderer = receipt.get("renderer") or {}
    out.append(
        "<section><h2>Fingerprints</h2><table>"
        f"<tr><th>Output</th><td class=\"hash\"><code>{_e(receipt.get('output_sha256'))}</code></td></tr>"
        f"<tr><th>Template</th><td class=\"hash\"><code>{_e(receipt.get('template_sha256'))}</code></td></tr>"
        f"<tr><th>Job</th><td class=\"hash\"><code>{_e(receipt.get('job_sha256'))}</code></td></tr>"
        f"<tr><th>Renderer</th><td>{_e(renderer.get('name'))} {_e(renderer.get('version'))}"
        f"<br><span class=\"hash\">{_e(renderer.get('ffmpeg', ''))}</span></td></tr></table></section>")
    out.append("<script type=\"application/json\" id=\"receipt-summary\">"
               + json.dumps({"job_id": receipt.get("job_id"), "gates": {g["id"]: g["status"] for g in gates}})
               .replace("<", "\\u003c") + "</script>")
    out.append("</main></body></html>")
    return "\n".join(out)


class ReviewPageExporter(Exporter):
    """Static HTML page: video, gates, human decisions pending, provenance and copy origin."""

    summary = "Self-contained HTML review page (video, gates, provenance, brief and writer)"

    def export(self, plan: dict, output: Path, protected: set[Path]) -> dict[str, Path]:
        return {}  # Written in finalize(), once gates and measurements exist.

    def finalize(self, receipt: dict, output: Path, protected: set[Path]) -> dict[str, Path]:
        page = Path(f"{output.with_suffix('')}.review.html")
        _guard([page], protected)
        page.write_text(review_html(receipt, page), encoding="utf-8")
        return {"review_page": page}
