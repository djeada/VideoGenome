"""Compose a render: renderer -> analyzers -> machine gates -> exporters -> receipt.

Every stage comes from the pipeline profile, so a different renderer, extra
analyzers (e.g. transcription accuracy) or new sidecar formats need no change
here. Stages that are absent are reported as absent, never assumed.
"""
from __future__ import annotations

from pathlib import Path

from videogenome.compiler import ProductionError, confined_file, sha256_file
from videogenome.plugins import PluginError
from videogenome.profile import Profile
from videogenome.qa import evaluate_gates

BASE_CAVEATS = [
    "Asset rights, consent and external origin are self-attested, not independently verified.",
    "Human gates are not assessed by any renderer or analyzer.",
    "Automated gates without a machine check (or without an analyzer for their metric) are not executed; "
    "aesthetic quality is not measured.",
    "Caption line and reading-speed limits do not certify accessibility or font coverage.",
]


def run_render(plan: dict, job_directory: Path, output: Path, profile: Profile, *,
               write_deliverables: bool = True, context: dict | None = None) -> dict:
    """Render, measure, gate and export; ``context`` (e.g. a fill record) joins the receipt."""
    if plan.get("pending_inputs"):
        raise ProductionError("Plan still has inputs to produce: " + ", ".join(plan["pending_inputs"]))
    root = job_directory.resolve()
    output = output.resolve()
    protected = {confined_file(root, asset["path"]) for asset in plan["assets"].values()}
    if output in protected:
        raise ProductionError("Output would overwrite a source asset")

    renderer = profile.renderer()
    unsupported = renderer.unsupported(plan)
    if unsupported:
        raise PluginError(f"Renderer {profile.data['renderer']['type']!r} cannot honour: "
                          + "; ".join(unsupported))
    report = renderer.render(plan, root, output)

    measurements: dict = {"metrics": {}, "not_applicable": {}, "sources": {}, "details": {}}
    for analyzer in profile.analyzers():
        label = type(analyzer).__name__
        result = analyzer.measure(output, plan)
        for metric, value in result.get("metrics", {}).items():
            if metric not in measurements["metrics"]:  # First analyzer wins; order is the profile's.
                measurements["metrics"][metric] = value
                measurements["sources"][metric] = label
        for metric, reason in result.get("not_applicable", {}).items():
            measurements["not_applicable"].setdefault(metric, reason)
        measurements["details"][label] = result.get("details", {})
    gates = evaluate_gates(plan["quality_gates"], measurements)

    sidecars = {}
    exporters = profile.exporters() if write_deliverables else []
    for exporter in exporters:
        for kind, path in exporter.export(plan, output, protected).items():
            sidecars[kind] = {"path": str(path), "sha256": sha256_file(path)}

    placeholders = sorted(asset_id for asset_id, asset in plan["assets"].items()
                          if (asset.get("generation") or {}).get("placeholder"))
    caveats = list(BASE_CAVEATS)
    if placeholders:
        caveats.insert(0, f"Contains placeholder media ({', '.join(placeholders)}): animatic only, "
                          "not for publication.")
    executed = any(g["status"] in ("passed", "failed") for g in gates)
    receipt = {
        "job_id": plan["job_id"], "template_id": plan["template_id"],
        "template_version": plan["template_version"],
        "template_sha256": plan["template_sha256"], "job_sha256": plan["job_sha256"],
        **report,
        "pipeline": profile.describe(),
        "output_path": str(output), "output_sha256": sha256_file(output),
        "frames_planned": plan["total_frames"],
        "verified": [*report.get("verified", []),
                     *(["technical_measurements"] if measurements["metrics"] else []),
                     *(["automated_gate_checks"] if executed else [])],
        "measurements": {**measurements["metrics"], "not_applicable": measurements["not_applicable"],
                         "sources": measurements["sources"], "details": measurements["details"]},
        "contains_placeholder_media": bool(placeholders),
        "picture": plan.get("picture"),
        "assets": plan["assets"],
        "timeline": plan.get("timeline"),
        "quality_gates": gates,
        "deliverables": sidecars,
        "caveats": caveats,
        **(context or {}),
    }
    for exporter in exporters:  # Second pass: sidecars that summarise the finished receipt.
        for kind, path in exporter.finalize(receipt, output, protected).items():
            sidecars[kind] = {"path": str(path), "sha256": sha256_file(path)}
    return receipt
