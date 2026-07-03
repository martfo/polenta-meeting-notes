"""Cross-cutting: the Hugging Face token lives in the Keychain, never a file."""

import json
from subprocess import CompletedProcess

from meetingnotes.config import Config, default_config, save_config
from meetingnotes.storage.keychain import ACCOUNT, SERVICE, KeychainStore

TOKEN = "hf_example_token_value"


class FakeRunner:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.commands: list[list[str]] = []
        self.stdout = stdout
        self.returncode = returncode

    def __call__(self, cmd, **kwargs):
        self.commands.append(cmd)
        return CompletedProcess(cmd, self.returncode, stdout=self.stdout, stderr="")


def test_ac_x_e_token_keychain_only(tmp_path):
    """Reads and writes target the macOS Keychain through the security
    command, and config.json never contains the token."""
    runner = FakeRunner(stdout=TOKEN + "\n")
    store = KeychainStore(runner=runner)

    store.write_token(TOKEN)
    assert store.read_token() == TOKEN

    for cmd in runner.commands:
        assert cmd[0] == "security", "every access goes through the Keychain"
        assert SERVICE in cmd and ACCOUNT in cmd
    assert any("add-generic-password" in c for c in runner.commands[0])
    assert any("find-generic-password" in c for c in runner.commands[1])

    # The config schema has no field that could hold it, and a saved
    # config.json never contains the token.
    assert not any("token" in field.lower() for field in Config.model_fields)
    config_path = tmp_path / "config.json"
    save_config(default_config(tmp_path / "MeetingVault"), config_path)
    text = config_path.read_text()
    assert TOKEN not in text
    assert "token" not in json.loads(text)
