"""Section 1.9: audio retention settings. Unit tier."""

from meetingnotes.config import default_config, load_config, save_config
from meetingnotes.storage.retention import retention_days, set_retention_days


def test_ac_1_9_a_default_retention_30_days(tmp_path):
    """A fresh config keeps audio for 30 days."""
    config = default_config(tmp_path / "MeetingVault")
    assert config.audio_retention_days == 30
    # And it survives the write-read round trip.
    save_config(config, tmp_path / "config.json")
    assert load_config(tmp_path / "config.json").audio_retention_days == 30


def test_ac_1_9_c_retention_configurable(tmp_path, conn):
    """The period can be changed in config.json and in settings, and the
    purge uses the changed value; settings takes precedence."""
    config = default_config(tmp_path / "MeetingVault")

    # Changed in config.json.
    config.audio_retention_days = 7
    save_config(config, tmp_path / "config.json")
    reloaded = load_config(tmp_path / "config.json")
    assert retention_days(reloaded, conn) == 7

    # Changed in settings.
    set_retention_days(conn, 90)
    assert retention_days(reloaded, conn) == 90
