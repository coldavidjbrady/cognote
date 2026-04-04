from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@contextmanager
def temporary_env(**updates: str | None):
    previous = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class RuntimeConfigTests(unittest.TestCase):
    def tearDown(self) -> None:
        config = importlib.import_module("backend.app.config")
        config.clear_settings_cache()

    def test_dev_mode_defaults_remain_repo_local(self) -> None:
        config = importlib.import_module("backend.app.config")

        with temporary_env(
            COGNOTE_RUNTIME_MODE=None,
            COGNOTE_APP_SUPPORT_DIR=None,
            COGNOTE_FRONTEND_DIST_DIR=None,
            NOTES_DB_PATH=None,
        ):
            config.clear_settings_cache()
            settings = config.get_settings()

        self.assertEqual(settings.runtime_mode, "dev")
        self.assertFalse(settings.is_packaged)
        self.assertEqual(settings.db_path, config.DEFAULT_DB_PATH.resolve())
        self.assertEqual(settings.source_root, config.BASE_DIR.resolve())
        self.assertTrue(str(settings.frontend_dist_dir).endswith("frontend/dist"))

    def test_packaged_mode_uses_app_support_defaults(self) -> None:
        config = importlib.import_module("backend.app.config")

        with tempfile.TemporaryDirectory() as temp_dir:
            app_support_dir = Path(temp_dir) / "Application Support" / "Cognote"
            frontend_dist_dir = Path(temp_dir) / "frontend-dist"
            frontend_dist_dir.mkdir(parents=True, exist_ok=True)

            with temporary_env(
                COGNOTE_RUNTIME_MODE="packaged",
                COGNOTE_APP_SUPPORT_DIR=str(app_support_dir),
                COGNOTE_FRONTEND_DIST_DIR=str(frontend_dist_dir),
                NOTES_DB_PATH=None,
            ):
                config.clear_settings_cache()
                settings = config.get_settings()

            self.assertEqual(settings.runtime_mode, "packaged")
            self.assertTrue(settings.is_packaged)
            self.assertEqual(settings.app_support_dir, app_support_dir.resolve())
            self.assertEqual(settings.db_path, (app_support_dir / "notes.db").resolve())
            self.assertEqual(settings.frontend_dist_dir, frontend_dist_dir.resolve())


class PackagedFrontendServingTests(unittest.TestCase):
    def _load_main_module(self):
        module = importlib.import_module("backend.app.main")
        return importlib.reload(module)

    def test_packaged_mode_serves_frontend_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            frontend_dist = temp_root / "dist"
            assets_dir = frontend_dist / "assets"
            frontend_dist.mkdir(parents=True, exist_ok=True)
            assets_dir.mkdir(parents=True, exist_ok=True)
            (frontend_dist / "index.html").write_text("<html><body>Cognote</body></html>", encoding="utf-8")
            (assets_dir / "app.js").write_text("console.log('cognote');", encoding="utf-8")

            with temporary_env(
                COGNOTE_RUNTIME_MODE="packaged",
                COGNOTE_FRONTEND_DIST_DIR=str(frontend_dist),
                COGNOTE_APP_SUPPORT_DIR=str(temp_root / "app-support"),
                NOTES_DB_PATH=str(temp_root / "notes.db"),
            ):
                config = importlib.import_module("backend.app.config")
                config.clear_settings_cache()
                main = self._load_main_module()

                with TestClient(main.app) as client:
                    root_response = client.get("/")
                    asset_response = client.get("/assets/app.js")
                    spa_response = client.get("/notes/123")
                    health_response = client.get("/api/health")

            self.assertEqual(root_response.status_code, 200)
            self.assertIn("Cognote", root_response.text)
            self.assertEqual(asset_response.status_code, 200)
            self.assertIn("console.log('cognote');", asset_response.text)
            self.assertEqual(spa_response.status_code, 200)
            self.assertIn("Cognote", spa_response.text)
            self.assertEqual(health_response.status_code, 200)
            self.assertEqual(health_response.json()["runtime_mode"], "packaged")

    def test_dev_mode_does_not_add_frontend_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with temporary_env(
                COGNOTE_RUNTIME_MODE="dev",
                COGNOTE_FRONTEND_DIST_DIR=None,
                COGNOTE_APP_SUPPORT_DIR=None,
                NOTES_DB_PATH=str(Path(temp_dir) / "notes.db"),
            ):
                config = importlib.import_module("backend.app.config")
                config.clear_settings_cache()
                main = self._load_main_module()

                with TestClient(main.app) as client:
                    response = client.get("/")
                    health_response = client.get("/api/health")

            self.assertEqual(response.status_code, 404)
            self.assertEqual(health_response.status_code, 200)
            self.assertEqual(health_response.json()["runtime_mode"], "dev")


if __name__ == "__main__":
    unittest.main()
