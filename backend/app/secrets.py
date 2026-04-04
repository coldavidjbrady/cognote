from __future__ import annotations

import subprocess
import sys


KEYCHAIN_SERVICE = "Cognote"
KEYCHAIN_ACCOUNT = "openai-api-key"


def keychain_available() -> bool:
    return sys.platform == "darwin"


def get_openai_api_key() -> str | None:
    if not keychain_available():
        return None

    proc = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-w",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_ACCOUNT,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    value = (proc.stdout or "").strip()
    return value or None


def set_openai_api_key(value: str) -> None:
    if not keychain_available():
        raise RuntimeError("macOS Keychain is not available on this system.")

    clean_value = value.strip()
    if not clean_value:
        raise ValueError("OpenAI API key cannot be empty.")

    proc = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_ACCOUNT,
            "-w",
            clean_value,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or "Unknown Keychain error"
        raise RuntimeError(f"Unable to save OpenAI API key to Keychain: {detail}")


def delete_openai_api_key() -> None:
    if not keychain_available():
        raise RuntimeError("macOS Keychain is not available on this system.")

    proc = subprocess.run(
        [
            "security",
            "delete-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_ACCOUNT,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # Missing key is fine for delete semantics.
    if proc.returncode not in (0, 44):
        detail = (proc.stderr or proc.stdout or "").strip() or "Unknown Keychain error"
        raise RuntimeError(f"Unable to remove OpenAI API key from Keychain: {detail}")
