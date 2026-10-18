"""Smoke-test an installed wheel from outside the source checkout.

    cd /tmp && python /path/to/VideoGenome/tools/check_install.py

CI runs this after installing the wheel so source-only resources cannot mask
missing package data. No browser, model or media generation is needed.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from videogenome.compiler import compile_job, read_json
from videogenome.profile import Profile
from videogenome.resources import DATA_ROOT, PACKAGE
from videogenome.service import Service, Workspace
from videogenome.studio import STATIC, Studio


def main() -> None:
    if DATA_ROOT != PACKAGE / "_data":
        raise RuntimeError("This check must import the installed wheel, outside the source checkout")
    for name in ("index.html", "app.js", "app.css"):
        if not (STATIC / name).is_file():
            raise RuntimeError(f"Missing installed Studio asset: {name}")
    with tempfile.TemporaryDirectory(prefix="vg-installed-") as directory:
        service = Service(Profile.load(), Workspace(Path(directory)))
        samples = service.sample_jobs()
        if not samples:
            raise RuntimeError("The installed wheel has no sample jobs for Studio previews")
        checked = 0
        for template_id, path in samples.items():
            job = read_json(path)
            if any(not (path.parent / a["path"]).is_file() for a in job.get("assets", {}).values()):
                continue  # Some sample media is made by authoring tools at render time.
            plan = compile_job(path, allow_pending=True)
            if plan["template_id"] != template_id or plan["total_frames"] <= 0:
                raise RuntimeError(f"Unusable installed sample: {path}")
            checked += 1
        studio = Studio(service)
        try:
            status, template = studio.api("GET", "/api/template/educational.title-card-sequence", {})
            if status != 200 or not template["sample_inputs"]:
                raise RuntimeError("Installed Studio cannot load its title-card sample")
            if not service.check_inputs("educational.title-card-sequence", template["sample_inputs"])["ok"]:
                raise RuntimeError("Installed Studio's title-card sample fails its copy contracts")
        finally:
            studio.jobs.pool.shutdown(wait=True)
        print(f"Verified installed Studio assets, {len(samples)} sample jobs and {checked} render plans")


if __name__ == "__main__":
    main()
