from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

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


class ConfigKeyResolutionTests(unittest.TestCase):
    def tearDown(self) -> None:
        config = importlib.import_module("backend.app.config")
        config.clear_settings_cache()

    def test_dev_mode_uses_env_key(self) -> None:
        config = importlib.import_module("backend.app.config")

        with temporary_env(
            COGNOTE_RUNTIME_MODE="dev",
            OPENAI_API_KEY="env-key",
            NOTES_DB_PATH=str(Path(tempfile.gettempdir()) / "cognote-dev.db"),
        ):
            with patch("backend.app.config.get_openai_api_key", return_value="keychain-key"):
                config.clear_settings_cache()
                settings = config.get_settings()

        self.assertEqual(settings.openai_api_key, "env-key")
        self.assertEqual(settings.openai_api_key_source, "env")

    def test_packaged_mode_falls_back_to_keychain(self) -> None:
        config = importlib.import_module("backend.app.config")

        with tempfile.TemporaryDirectory() as temp_dir:
            with temporary_env(
                COGNOTE_RUNTIME_MODE="packaged",
                OPENAI_API_KEY=None,
                COGNOTE_APP_SUPPORT_DIR=str(Path(temp_dir) / "app-support"),
            ):
                with patch("backend.app.config.get_openai_api_key", return_value="keychain-key"):
                    config.clear_settings_cache()
                    settings = config.get_settings()

        self.assertEqual(settings.openai_api_key, "keychain-key")
        self.assertEqual(settings.openai_api_key_source, "keychain")


class SettingsEndpointTests(unittest.TestCase):
    def _load_main_module(self):
        module = importlib.import_module("backend.app.main")
        return importlib.reload(module)

    def test_settings_endpoint_reports_key_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with temporary_env(
                COGNOTE_RUNTIME_MODE="dev",
                OPENAI_API_KEY="env-key",
                NOTES_DB_PATH=str(Path(temp_dir) / "notes.db"),
            ):
                config = importlib.import_module("backend.app.config")
                config.clear_settings_cache()
                main = self._load_main_module()

                with TestClient(main.app) as client:
                    response = client.get("/api/settings")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["semantic_search_enabled"])
        self.assertEqual(payload["openai_key_source"], "env")
        self.assertFalse(payload["packaged_mode"])

    def test_packaged_mode_can_store_and_remove_openai_key(self) -> None:
        api_key = "sk-test-openai-key-1234567890"
        with tempfile.TemporaryDirectory() as temp_dir:
            with temporary_env(
                COGNOTE_RUNTIME_MODE="packaged",
                OPENAI_API_KEY=None,
                COGNOTE_APP_SUPPORT_DIR=str(Path(temp_dir) / "app-support"),
                NOTES_DB_PATH=str(Path(temp_dir) / "notes.db"),
            ):
                config = importlib.import_module("backend.app.config")
                config.clear_settings_cache()

                with patch("backend.app.config.get_openai_api_key", side_effect=[None, api_key, None]):
                    main = self._load_main_module()

                    with patch("backend.app.main.keychain_available", return_value=True):
                        with patch("backend.app.main.set_openai_api_key") as set_key_mock:
                            with TestClient(main.app) as client:
                                put_response = client.put(
                                    "/api/settings/openai-key",
                                    json={"api_key": api_key},
                                )

                        with patch("backend.app.main.delete_openai_api_key") as delete_key_mock:
                            with patch("backend.app.main.keychain_available", return_value=True):
                                with TestClient(main.app) as client:
                                    delete_response = client.delete("/api/settings/openai-key")

                self.assertEqual(put_response.status_code, 200)
                self.assertTrue(put_response.json()["openai_key_configured"])
                self.assertEqual(put_response.json()["openai_key_source"], "keychain")
                set_key_mock.assert_called_once_with(api_key)

                self.assertEqual(delete_response.status_code, 200)
                self.assertFalse(delete_response.json()["openai_key_configured"])
                self.assertEqual(delete_response.json()["openai_key_source"], "none")
                delete_key_mock.assert_called_once()

    def test_dev_mode_rejects_key_management_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with temporary_env(
                COGNOTE_RUNTIME_MODE="dev",
                NOTES_DB_PATH=str(Path(temp_dir) / "notes.db"),
            ):
                config = importlib.import_module("backend.app.config")
                config.clear_settings_cache()
                main = self._load_main_module()

                with TestClient(main.app) as client:
                    response = client.put("/api/settings/openai-key", json={"api_key": "x" * 30})

        self.assertEqual(response.status_code, 400)
        self.assertIn("packaged mode", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
