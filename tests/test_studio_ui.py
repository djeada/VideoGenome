"""Studio user journeys, responsive screenshots, and editing saved render copy."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from tests.test_cockpits import service
from tests.test_plugins import write
from videogenome.compiler import ProductionError
from videogenome.profile import Profile
from videogenome.service import Service, Workspace
from videogenome.studio import Studio

HAS_BROWSER = bool(importlib.util.find_spec("playwright"))


class StudioEditingTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.service = service(self.root)

    def test_original_copy_and_brief_are_restored_without_media_bindings(self) -> None:
        run = self.service.workspace.new_run("saved-card")
        write(run / "job.json", {"template": "test.card", "inputs": {"title": "The original story", "unknown_media": "asset"}})
        write(run / "receipt.json", {"fill": {"brief": "A brief about the original story"}})
        before = (run / "job.json").read_bytes()
        result = self.service.edit_run(run.name)
        self.assertEqual(result, {"template": "test.card", "inputs": {"title": "The original story"},
                                  "brief": "A brief about the original story"})
        self.assertEqual((run / "job.json").read_bytes(), before)

    def test_brief_to_video_jobs_use_the_nested_job_directory(self) -> None:
        run = self.service.workspace.new_run("created-card")
        write(run / "job/job.json", {"template": "test.card", "inputs": {"title": "New story"}})
        self.assertEqual(self.service.edit_run(run.name)["inputs"]["title"], "New story")

    def test_reopening_copy_refuses_escaped_paths_and_symlinks(self) -> None:
        outside = self.root / "private"
        write(outside / "job.json", {"template": "test.card", "inputs": {"title": "Private"}})
        run = self.service.workspace.new_run("link")
        (run / "job.json").symlink_to(outside / "job.json")
        for name in ("../private", str(outside), run.name, "missing-run"):
            with self.subTest(name=name), self.assertRaises(ProductionError):
                self.service.edit_run(name)

    def test_recipe_controls_can_display_real_preset_values(self) -> None:
        recipe = next(r for r in self.service.recipes() if r["id"] == "scene.kinetic-type")
        self.assertEqual(recipe["preset_values"]["neon"]["palette"][0], "#07080A")
        self.assertNotEqual(recipe["preset_values"]["neon"]["palette"], recipe["params_schema"]["properties"]["palette"]["default"])


@unittest.skipUnless(HAS_BROWSER, "Playwright is required for Studio browser journeys")
class StudioBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from playwright.sync_api import sync_playwright
        cls.temp = tempfile.TemporaryDirectory()
        profile = Profile.load()
        profile.data = {**profile.data, "id": "studio-ui-test", "routes": {}}
        cls.service = Service(profile, Workspace(Path(cls.temp.name)))
        cls.studio = Studio(cls.service, port=0)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), cls.studio.handler())
        cls.studio.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception:
            cls.playwright.stop()
            cls.httpd.shutdown()
            cls.httpd.server_close()
            cls.thread.join()
            cls.studio.jobs.pool.shutdown(wait=True)
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        cls.studio.jobs.pool.shutdown(wait=True)
        cls.temp.cleanup()

    def setUp(self) -> None:
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1080}, reduced_motion="reduce")
        self.page = self.context.new_page()
        self.errors: list[str] = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.studio.url)
        self.page.locator("#library .tile").first.wait_for()
        self.page.locator("#slot-headline").wait_for(state="attached")

    def tearDown(self) -> None:
        self.context.close()
        self.assertEqual(self.errors, [])

    def test_search_filter_save_and_empty_state_recovery(self) -> None:
        total = self.page.locator("#library .tile").count()
        self.assertGreater(total, 20)
        self.page.get_by_label("Search the library").fill("Kinetic typography reel")
        self.assertEqual(self.page.locator("#library .tile").count(), 1)
        self.page.get_by_role("button", name="Save Kinetic typography reel", exact=True).click()
        self.page.locator('[data-level="saved"]').click()
        self.assertEqual(self.page.locator("#library .tile").count(), 1)
        self.page.get_by_label("Search the library").fill("an impossible query")
        self.page.get_by_role("button", name="Explore all styles", exact=True).click()
        self.assertEqual(self.page.locator("#library .tile").count(), total)

    def test_sample_draft_reload_and_error_recovery(self) -> None:
        from playwright.sync_api import expect
        self.page.get_by_role("button", name="Make your first video", exact=True).click()
        self.page.get_by_role("button", name="Try sample copy", exact=True).click()
        field = self.page.locator("#slot-headline")
        field.fill("A story worth telling")
        expect(self.page.locator("#draft-status")).to_contain_text("saved")
        self.page.reload()
        self.page.locator("#slot-headline").wait_for()
        self.assertEqual(self.page.locator("#slot-headline").input_value(), "A story worth telling")
        self.page.route("**/api/check", lambda route: route.abort())
        self.page.get_by_role("button", name="Check my copy", exact=True).click()
        self.page.locator("#make-job .notice.bad").wait_for()
        self.assertIn("could not be reached", self.page.locator("#make-job").inner_text())
        self.assertEqual(self.page.locator("#slot-headline").input_value(), "A story worth telling")

    def test_real_render_download_and_reopen_copy(self) -> None:
        from playwright.sync_api import expect
        self.page.get_by_role("button", name="Make your first video", exact=True).click()
        self.page.get_by_role("button", name="Try sample copy", exact=True).click()
        original = self.page.locator("#slot-headline").input_value()
        self.page.get_by_role("button", name="Render video", exact=True).click()
        self.page.locator("#make-deliverables a[download]").wait_for(timeout=120000)
        self.assertTrue(self.page.locator("#make-preview video").is_visible())
        self.assertFalse(self.page.locator("#btn-render").is_disabled())
        self.page.locator('.tab[data-view="runs"]').click()
        self.page.get_by_role("button", name="Edit copy", exact=True).first.click()
        expect(self.page.locator("#view-make")).to_be_visible()
        self.assertEqual(self.page.locator("#slot-headline").input_value(), original)

    def test_preset_picker_updates_visible_controls(self) -> None:
        self.page.locator('.tab[data-view="code"]').click()
        self.page.locator("#recipe-select").select_option("scene.kinetic-type")
        self.page.locator("#recipe-preset").select_option("neon")
        self.assertEqual(self.page.locator("#param-palette input").first.input_value(), "#07080a")

    def test_desktop_and_mobile_screenshots_have_no_horizontal_overflow(self) -> None:
        destination = Path(os.environ.get("VIDEOGENOME_UI_ARTIFACTS", self.temp.name))
        destination.mkdir(parents=True, exist_ok=True)
        self.page.evaluate("document.fonts.ready")
        self.page.screenshot(path=str(destination / "studio-library-desktop.png"))
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))
        self.page.get_by_role("button", name="Make your first video", exact=True).click()
        self.page.get_by_role("button", name="Try sample copy", exact=True).click()
        self.page.get_by_text("Sample copy added. Make it your own.", exact=True).wait_for(state="detached")
        self.page.screenshot(path=str(destination / "studio-editor-desktop.png"))
        self.page.locator('.tab[data-view="library"]').click()
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))
        self.page.screenshot(path=str(destination / "studio-library-mobile.png"))
        self.page.get_by_role("button", name="Open navigation", exact=True).click()
        self.assertEqual(self.page.locator("#nav-toggle").get_attribute("aria-expanded"), "true")
        self.page.locator('.tab[data-view="make"]').click()
        self.assertEqual(self.page.locator("#nav-toggle").get_attribute("aria-expanded"), "false")
        self.page.screenshot(path=str(destination / "studio-editor-mobile.png"))
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))
