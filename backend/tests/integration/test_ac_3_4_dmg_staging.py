"""AC-3.4-a: the dmg build script stages a drag-to-install layout. The test
runs the real script against a stub app bundle; hdiutil is skipped."""

import subprocess

from tests.conftest import REPO_ROOT


def make_stub_app(tmp_path):
    """A stub .app with the same resource layout build_app.sh produces."""
    app = tmp_path / "MeetingNotes.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    (app / "Contents/MacOS/MeetingNotesApp").write_bytes(b"stub-binary")
    resources = app / "Contents/Resources"
    (resources / "language/dict").mkdir(parents=True)
    src = REPO_ROOT / "backend/meetingnotes/resources"
    (resources / "language/american_to_british.json").write_bytes(
        (src / "american_to_british.json").read_bytes())
    (resources / "language/technical_allowlist.txt").write_bytes(
        (src / "technical_allowlist.txt").read_bytes())
    (resources / "language/dict/en_GB.aff").write_bytes((src / "dict/en_GB.aff").read_bytes())
    (resources / "language/dict/en_GB.dic").write_bytes((src / "dict/en_GB.dic").read_bytes())
    (resources / "summary_prompt.md").write_bytes((src / "summary_prompt.md").read_bytes())
    (app / "Contents/Info.plist").write_text("<plist/>")
    return app


def stage(tmp_path):
    app = make_stub_app(tmp_path)
    staging = tmp_path / "staging"
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/build_dmg.sh"), "--stage-only",
         str(app), str(staging)],
        check=True, capture_output=True,
    )
    return staging


def test_ac_3_4_a_dmg_staging_layout(tmp_path):
    staging = stage(tmp_path)

    assert (staging / "Polenta Meeting Notes.app/Contents/MacOS/MeetingNotesApp").exists()
    applications = staging / "Applications"
    assert applications.is_symlink() and str(applications.readlink()) == "/Applications"
    readme = staging / "Read me first.txt"
    assert readme.exists()
    text = readme.read_text()
    assert "right-click" in text.lower() or "control-click" in text.lower()
