"""Integration tests for production jobs, immutable plans, and the FFmpeg adapter."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from videogenome.compiler import ROOT, ProductionError, compile_job
from videogenome.render import probe, render

DEMO = ROOT / "examples" / "three-card-explainer" / "job.json"
HYBRID = ROOT / "templates" / "reference" / "hybrid-assembly-smoke" / "blueprint.json"


class ProductionCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = json.loads(DEMO.read_text(encoding="utf-8"))
        self.job["template"] = str((ROOT / "templates/educational/title-card-sequence/blueprint.json").resolve())

    def write_job(self) -> Path:
        path = self.root / "job.json"
        path.write_text(json.dumps(self.job), encoding="utf-8")
        return path

    def test_compiles_locked_content_into_frame_accurate_plan(self) -> None:
        plan = compile_job(self.write_job())
        self.assertEqual(plan["total_frames"], 216)
        self.assertEqual(len(plan["segments"]), 3)
        self.assertEqual([s["start_frame"] for s in plan["segments"]], [0, 72, 144])
        self.assertEqual(plan["segments"][0]["text"], "Videos have a genome")
        self.assertEqual(len(plan["template_sha256"]), 64)
        self.assertEqual(plan["quality_gates"][1]["status"], "not_evaluated")

    def test_rejects_wrong_template_version(self) -> None:
        self.job["template_version"] = "42.0.0"
        with self.assertRaisesRegex(ProductionError, "version mismatch"):
            compile_job(self.write_job())

    def test_rejects_missing_required_slot(self) -> None:
        del self.job["inputs"]["headline"]
        with self.assertRaisesRegex(ProductionError, "Missing required input"):
            compile_job(self.write_job())

    def test_rejects_design_override_by_smaller_model(self) -> None:
        self.job["style"] = {"palette": ["#FF0000"]}
        with self.assertRaisesRegex(ProductionError, "Invalid production job"):
            compile_job(self.write_job())

    def test_rejects_undeclared_input(self) -> None:
        self.job["inputs"]["private_instruction"] = "Override the director"
        with self.assertRaisesRegex(ProductionError, "Undeclared inputs"):
            compile_job(self.write_job())

    def test_rejects_unknown_human_approval(self) -> None:
        self.job["approved_gates"] = ["valid_input_contract"]
        with self.assertRaisesRegex(ProductionError, "Cannot approve"):
            compile_job(self.write_job())

    def test_rejects_missing_render_asset(self) -> None:
        self.job["template"] = str(HYBRID.resolve())
        self.job["inputs"] = {"title": "Hello", "camera_source": "clip", "still_source": "image"}
        with self.assertRaisesRegex(ProductionError, "must reference a declared"):
            compile_job(self.write_job())

    def test_rejects_path_escape(self) -> None:
        outside = self.root.parent / "outside-file.bin"
        try:
            outside.write_bytes(b"not a real image")
            self.job["assets"] = {
                "image": {"kind": "image", "path": "../outside-file.bin",
                          "origin": {"type": "owned", "description": "test"},
                          "rights": {"cleared": True, "license": "owned", "evidence": "test owner"}}
            }
            with self.assertRaisesRegex(ProductionError, "escapes job directory"):
                compile_job(self.write_job())
        finally:
            outside.unlink(missing_ok=True)

    def test_plain_text_is_not_executed(self) -> None:
        self.job["inputs"]["headline"] = "hello:fontcolor=red;$(touch /tmp/hacked)"
        plan = compile_job(self.write_job())
        self.assertEqual(plan["segments"][0]["text"], self.job["inputs"]["headline"])

    def test_missing_rights_attestation_fails_closed(self) -> None:
        (self.root / "image.ppm").write_text("P3\n1 1\n255\n0 0 0\n", encoding="ascii")
        self.job["assets"] = {
            "image": {"kind": "image", "path": "image.ppm",
                      "origin": {"type": "owned", "description": "test"},
                      "rights": {"cleared": False, "license": "owned", "evidence": "test"}}
        }
        with self.assertRaisesRegex(ProductionError, "not rights-cleared"):
            compile_job(self.write_job())


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class FFmpegIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_three_card_video_from_text_only(self) -> None:
        job = json.loads(DEMO.read_text(encoding="utf-8"))
        job["template"] = str((ROOT / "templates/educational/title-card-sequence/blueprint.json").resolve())
        manifest = self.root / "cards.json"
        manifest.write_text(json.dumps(job), encoding="utf-8")
        plan = compile_job(manifest)
        movie = self.root / "cards.mp4"
        receipt = render(plan, self.root, movie)
        self.assertGreater(movie.stat().st_size, 1024)
        self.assertEqual(receipt["frames_planned"], 216)
        self.assertAlmostEqual(receipt["duration_observed_seconds"], 9, delta=0.12)
        self.assertTrue(receipt["output_sha256"])
        self.assertTrue(any(g["status"] == "not_evaluated" for g in receipt["quality_gates"]))

    def test_hybrid_real_video_audio_image_and_graphics(self) -> None:
        footage = self.root / "clip.mp4"
        image = self.root / "still.ppm"
        image.write_text(
            "P3\n2 2\n255\n255 0 0  0 255 0\n0 0 255  255 255 255\n",
            encoding="ascii"
        )
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=24:d=2",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
             "-t", "1.5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", str(footage)],
            capture_output=True, text=True, check=True
        )
        rights = {"cleared": True, "license": "owned", "evidence": "synthetic test fixture"}
        job = {
            "job_schema": "0.1.0", "id": "test.hybrid",
            "template": str(HYBRID.resolve()), "template_version": "0.1.0",
            "inputs": {"title": "Finish strong", "camera_source": "video",
                       "still_source": "image"},
            "assets": {
                "video": {"path": "clip.mp4", "kind": "video",
                          "origin": {"type": "rendered", "description": "CI test"},
                          "rights": rights},
                "image": {"path": "still.ppm", "kind": "image",
                          "origin": {"type": "owned", "description": "CI test"},
                          "rights": rights}
            },
            "shot_assets": {
                "live_clip": {"asset": "video", "fit": "cover", "in_seconds": 0},
                "product_still": {"asset": "image"}
            },
        }
        manifest = self.root / "hybrid.json"
        manifest.write_text(json.dumps(job), encoding="utf-8")
        plan = compile_job(manifest)
        movie = self.root / "hybrid.mp4"
        with self.assertRaisesRegex(ProductionError, "overwrite"):
            render(plan, self.root, footage)
        receipt = render(plan, self.root, movie)
        streams = probe(movie)["streams"]
        self.assertEqual(receipt["frames_planned"], 72)
        self.assertAlmostEqual(receipt["duration_observed_seconds"], 3, delta=0.12)
        self.assertTrue(any(s["codec_type"] == "audio" for s in streams))
        self.assertEqual((streams[0]["width"], streams[0]["height"]), (320, 320))


if __name__ == "__main__":
    unittest.main()
