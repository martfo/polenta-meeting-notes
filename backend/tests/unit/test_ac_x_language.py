"""Cross-cutting: the British English pass and the source-string lint."""

import json

from meetingnotes.language.british import MAP_PATH, convert_to_british
from meetingnotes.language.flag import flag_unknown_words
from meetingnotes.language.lint import lint_repo, lint_text


def test_ac_x_d_source_string_lint(repo_root):
    """No em dashes and no denylisted American spellings in app-authored
    strings or the default summary prompt."""
    # Positive control: the lint does catch both kinds of problem.
    bad = "We organized the color scheme — nicely."
    problems = {v.problem for v in lint_text(bad, "control")}
    assert "em dash" in problems
    assert any("organized" in p for p in problems)
    assert any("color" in p for p in problems)

    # The repository itself is clean.
    violations = lint_repo(repo_root)
    assert violations == [], "\n".join(str(v) for v in violations)


def test_ac_x_f_british_conversion():
    """Known American spellings are converted; names, code, and words outside
    the map are untouched."""
    text = (
        "The color scheme will organize the report for Denver Analytics. "
        "Run `organize_files(color)` to check. The kohlrabi is unaffected."
    )
    converted = convert_to_british(text)
    assert "colour scheme" in converted
    assert "organise the report" in converted
    assert "Denver Analytics" in converted, "proper names left alone"
    assert "`organize_files(color)`" in converted, "code spans left alone"
    assert "kohlrabi" in converted, "words outside the map left alone"
    # Case is preserved.
    assert convert_to_british("Color and COLOR") == "Colour and COLOUR"


def test_ac_x_g_dictionary_flagging():
    """The dictionary flag reports unknown words without altering anything,
    and skips likely names, code spans, and allowlisted terms."""
    text = (
        "The zorbleflux reading came from Ben Adams. "
        "Call `weirdfn()` and check the diarisation and the kubernetes pods."
    )
    flags = flag_unknown_words(text, allowlist={"kubernetes"})
    assert flags == ["zorbleflux"]
    # Nothing is rewritten: flagging is read-only by construction; the same
    # text passed again produces the same result.
    assert flag_unknown_words(text, allowlist={"kubernetes"}) == ["zorbleflux"]


def test_ac_x_l_map_contents():
    """The bundled VarCon-derived map: sample conversions resolve and the
    meaning-dependent words are not keys."""
    mapping = json.loads(MAP_PATH.read_text())
    assert mapping["color"] == "colour"
    assert mapping["organize"] == "organise"
    assert mapping["analyze"] == "analyse"
    assert mapping["center"] == "centre"
    assert mapping["catalog"] == "catalogue"
    for excluded in ("license", "practice", "program", "meter"):
        assert excluded not in mapping
