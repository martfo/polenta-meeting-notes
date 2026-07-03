"""AC-3.4-b: the staged dmg contents carry the bundled resources (the map,
the dictionary, the allowlist, the default summary prompt) and no model
weights."""

from tests.integration.test_ac_3_4_dmg_staging import stage

WEIGHT_SUFFIXES = {".pt", ".pth", ".bin", ".ckpt", ".onnx", ".gguf", ".safetensors"}


def test_ac_3_4_b_staged_resources_no_weights(tmp_path):
    staging = stage(tmp_path)
    resources = staging / "Polenta Meeting Notes.app/Contents/Resources"

    for bundled in (
        "language/american_to_british.json",
        "language/technical_allowlist.txt",
        "language/dict/en_GB.aff",
        "language/dict/en_GB.dic",
        "summary_prompt.md",
    ):
        assert (resources / bundled).exists(), f"missing bundled resource {bundled}"

    offenders = [
        path for path in staging.rglob("*")
        if path.is_file() and path.suffix.lower() in WEIGHT_SUFFIXES
    ]
    assert offenders == [], f"model weights must never ship in the dmg: {offenders}"
