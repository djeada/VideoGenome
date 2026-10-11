"""Executed technical measurements and machine-checkable quality gates.

Only gates that declare a ``check`` with a supported metric are evaluated.
Everything else, including aesthetic and storytelling judgements, stays
``not_evaluated`` until a genuine human approval is recorded.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from videogenome.compiler import ProductionError
from videogenome.plugins import Analyzer

# Fixed, documented detector settings so measurements are comparable.
BLACK_FILTER = "blackdetect=d=0.1:pix_th=0.10:pic_th=0.98"
SILENCE_FILTER = "silencedetect=n=-50dB:d=0.25"
# A frame is "blank" when its luma range is this narrow: nothing is visible,
# whatever the background colour (blackdetect alone misreads dark designs).
BLANK_LUMA_RANGE = 12
BLANK_FILTER = ("signalstats,metadata=print:key=lavfi.signalstats.YMIN,"
                "metadata=print:key=lavfi.signalstats.YMAX")
SILENT_PROGRAMME_LUFS = -70.0
LOUDNESS_METRICS = {"integrated_lufs", "true_peak_dbtp"}


def _number(pattern: str, text: str) -> float | None:
    found = re.findall(pattern, text)
    if not found:
        return None
    # -inf (digital silence) has no JSON representation; report it as absent.
    return None if found[-1].lower() == "-inf" else float(found[-1])


def _blank_runs(log: str, fps: float) -> tuple[float, float]:
    lows = [int(v) for v in re.findall(r"lavfi\.signalstats\.YMIN=(\d+)", log)]
    highs = [int(v) for v in re.findall(r"lavfi\.signalstats\.YMAX=(\d+)", log)]
    total = longest = run = 0
    for low, high in zip(lows, highs):
        if high - low <= BLANK_LUMA_RANGE:
            total += 1
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return round(total / fps, 3), round(longest / fps, 3)


def measure(path: Path, duration: float, fps: float) -> dict:
    """Loudness (EBU R128), true peak, black and silent intervals of a file."""
    command = [
        "ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info", "-i", str(path),
        "-filter_complex",
        f"[0:a:0]ebur128=peak=true,{SILENCE_FILTER}[a];[0:v:0]{BLACK_FILTER},{BLANK_FILTER}[v]",
        "-map", "[a]", "-map", "[v]", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise ProductionError(f"Cannot run ffmpeg for measurement: {exc}") from exc
    if result.returncode:
        raise ProductionError(f"Measurement failed: {result.stderr[-800:]}")
    log = result.stderr
    summary = log[log.rfind("Summary:"):] if "Summary:" in log else ""
    integrated = _number(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", summary)
    true_peak = _number(r"Peak:\s+(-?[\d.]+|-inf)\s+dBFS", summary)
    loudness_range = _number(r"LRA:\s+(-?[\d.]+)\s+LU", summary)

    black = [float(d) for d in re.findall(r"black_duration:\s*([\d.]+)", log)]
    silences = [float(d) for d in re.findall(r"silence_duration:\s*([\d.]+)", log)]
    starts = [float(s) for s in re.findall(r"silence_start:\s*(-?[\d.]+)", log)]
    if len(starts) > len(silences):  # Silence still running at end of file.
        silences.append(max(0.0, duration - starts[-1]))
    blank, longest_blank = _blank_runs(log, fps)
    return {
        "integrated_lufs": integrated,
        "true_peak_dbtp": true_peak,
        "loudness_range_lu": loudness_range,
        "black_seconds": round(sum(black), 3),
        "blank_seconds": blank,
        "longest_blank_seconds": longest_blank,
        "longest_silence_seconds": round(max(silences, default=0.0), 3),
        "silent_programme": integrated is None or integrated <= SILENT_PROGRAMME_LUFS,
        "detectors": {"loudness": "ebur128 (EBU R128, true peak)",
                      "black": BLACK_FILTER, "silence": SILENCE_FILTER,
                      "blank": f"signalstats luma range <= {BLANK_LUMA_RANGE}"},
    }


class FFmpegAnalyzer(Analyzer):
    """Loudness, true peak, black/blank picture and silence via FFmpeg filters."""

    summary = "EBU R128 loudness, true peak, black/blank picture, silence (FFmpeg)"
    metrics = frozenset({"integrated_lufs", "true_peak_dbtp", "loudness_range_lu", "black_seconds",
                         "blank_seconds", "longest_blank_seconds", "longest_silence_seconds"})

    def measure(self, output: Path, plan: dict) -> dict:
        fps = plan["output"]["fps"]
        values = measure(output, plan["total_frames"] / fps, fps)
        details = {"detectors": values.pop("detectors"), "silent_programme": values.pop("silent_programme")}
        not_applicable = {}
        if details["silent_programme"]:
            not_applicable = {metric: "programme audio is silent"
                              for metric in ("integrated_lufs", "true_peak_dbtp", "loudness_range_lu")}
        return {"metrics": values, "not_applicable": not_applicable, "details": details}


def evaluate_gates(gates: list[dict], measurements: dict) -> list[dict]:
    """Apply machine checks; ``measurements`` is the merged analyzer report:
    ``{"metrics": {...}, "not_applicable": {...}, "sources": {...}}``."""
    metrics = measurements.get("metrics", {})
    not_applicable = measurements.get("not_applicable", {})
    evaluated = []
    for gate in gates:
        check = gate.get("check")
        if not check or gate["status"] == "self_attested_approved":
            evaluated.append(gate)
            continue
        metric = check["metric"]
        if metric in not_applicable:
            evaluated.append({**gate, "status": "not_applicable",
                              "evidence": {"metric": metric, "reason": not_applicable[metric]}})
            continue
        if metric not in metrics:
            evaluated.append({**gate, "status": "not_evaluated",
                              "evidence": {"metric": metric,
                                           "reason": "no configured analyzer reports this metric"}})
            continue
        value = metrics[metric]
        passed = isinstance(value, (int, float)) and not isinstance(value, bool) and (
            ("min" not in check or value >= check["min"]) and
            ("max" not in check or value <= check["max"])
        )
        evaluated.append({**gate, "status": "passed" if passed else "failed",
                          "evidence": {"metric": metric, "value": value,
                                       "source": measurements.get("sources", {}).get(metric),
                                       **{k: check[k] for k in ("min", "max") if k in check}}})
    return evaluated
