"""The Hugging Face token lives in the macOS Keychain, never in config.json
or any file in the vault. Reads and writes go through the security command;
the runner is injectable so tests prove the target without touching a real
keychain."""

from __future__ import annotations

import subprocess
from typing import Callable

SERVICE = "MeetingNotes"
ACCOUNT = "huggingface-token"

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class KeychainStore:
    def __init__(self, runner: Runner = subprocess.run):
        self._run = runner

    def read_token(self) -> str | None:
        result = self._run(
            ["security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return None
        token = result.stdout.strip()
        return token or None

    def write_token(self, token: str) -> None:
        result = self._run(
            ["security", "add-generic-password", "-U",
             "-s", SERVICE, "-a", ACCOUNT, "-w", token],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError("could not store the token in the Keychain")

    def delete_token(self) -> None:
        self._run(
            ["security", "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT],
            capture_output=True, text=True,
        )


def read_hf_token() -> str | None:
    return KeychainStore().read_token()
