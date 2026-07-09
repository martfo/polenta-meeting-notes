"""Section 1.5: the summary. Unit tier against canned model responses."""

import pytest

from meetingnotes.language.emdash import strip_em_dashes
from meetingnotes.llm.summary import (
    assemble_messages,
    generate_summary_text,
    missing_mandatory,
    summarise_meeting,
)
from meetingnotes.storage import meetings as m
from meetingnotes.storage.frontmatter import read_meeting_md
from tests.conftest import FakeLMClient, make_meeting

TRANSCRIPT = ("**[00:00:04] Ben Adams**\nWe reviewed the hydroponics budget in "
              "detail and agreed the delivery timeline for the client this week.")
NOTES = "Remember to chase the supplier quote."


@pytest.fixture
def canned(fixtures_dir):
    return {
        "ok": (fixtures_dir / "llm" / "summary_ok.md").read_text(),
        "no_open_questions": (fixtures_dir / "llm" / "summary_no_open_questions.md").read_text(),
        "missing_mandatory": (fixtures_dir / "llm" / "summary_missing_mandatory.md").read_text(),
    }


def test_ac_1_5_a_prompt_assembly():
    """The summary prompt is assembled from summary_prompt.md plus transcript
    plus notes, all three present."""
    messages = assemble_messages("TEMPLATE TEXT", TRANSCRIPT, NOTES)
    content = messages[-1]["content"]
    assert "TEMPLATE TEXT" in content
    assert TRANSCRIPT in content
    assert NOTES in content


def test_ac_1_5_b_prompt_edit_takes_effect(conn, vault, canned):
    """Editing summary_prompt.md changes the next summary with no restart."""
    meeting_id = make_meeting(conn, vault)
    vault.summary_prompt_path.write_text("FIRST PROMPT VERSION")
    client = FakeLMClient(canned["ok"])

    summarise_meeting(conn, vault, client, meeting_id, TRANSCRIPT)
    assert "FIRST PROMPT VERSION" in client.requests[0][-1]["content"]

    vault.summary_prompt_path.write_text("SECOND PROMPT VERSION")
    summarise_meeting(conn, vault, client, meeting_id, TRANSCRIPT)
    assert "SECOND PROMPT VERSION" in client.requests[1][-1]["content"]
    assert "FIRST PROMPT VERSION" not in client.requests[1][-1]["content"]


def test_ac_1_5_c_meeting_md_written(conn, vault, canned):
    """Given a canned response, meeting.md carries correct front matter and
    the summary body, already through the British English pass."""
    meeting_id = make_meeting(conn, vault)
    m.add_attendee(conn, meeting_id, "Ben Adams", email="ben@example.com")
    vault.summary_prompt_path.write_text("prompt")

    summarise_meeting(conn, vault, FakeLMClient(canned["ok"]), meeting_id, TRANSCRIPT)

    front, body = read_meeting_md(vault.meeting_md_path(meeting_id))
    assert front["id"] == meeting_id
    assert front["title"] == "Client review"
    assert front["date"] == "2026-07-02"
    assert front["start_time"] == "14:00"
    assert front["source"] == "online"
    assert front["attendees"] == [{"name": "Ben Adams", "email": "ben@example.com"}]
    assert front["summary_status"] == "ready"
    assert "## Core items discussed" in body
    assert "## Next Steps" in body
    # The canned reply carried an em dash and two American spellings; the
    # saved body must not.
    assert "—" not in body
    assert "organised" in body and "organized" not in body
    assert "colour" in body and "color" not in body
    assert m.get_meeting(conn, meeting_id)["summary_status"] == "ready"


def test_ac_1_5_d_validator_mandatory_and_optional(canned):
    """Core items discussed and Next Steps are mandatory; Open Questions is
    optional. A missing mandatory section triggers one regeneration, then
    needs_attention."""
    assert missing_mandatory(canned["ok"]) == []
    assert missing_mandatory(canned["no_open_questions"]) == []
    assert missing_mandatory(canned["missing_mandatory"]) == ["next steps"]
    # Case-insensitive heading matching.
    assert missing_mandatory("## CORE ITEMS DISCUSSED\nx\n## next steps\ny") == []

    # Bad then good: one regeneration, result ready.
    client = FakeLMClient(canned["missing_mandatory"], canned["ok"])
    result = generate_summary_text(client, "p", TRANSCRIPT, "")
    assert (result.attempts, result.status) == (2, "ready")

    # Bad twice: saved anyway, marked needs_attention.
    client = FakeLMClient(canned["missing_mandatory"])
    result = generate_summary_text(client, "p", TRANSCRIPT, "")
    assert (result.attempts, result.status) == (2, "needs_attention")
    assert "## Core items discussed" in result.body, "what was produced is kept"

    # A summary with no Open Questions regenerates nothing.
    client = FakeLMClient(canned["no_open_questions"])
    result = generate_summary_text(client, "p", TRANSCRIPT, "")
    assert (result.attempts, result.status) == (1, "ready")


def test_prompt_variables_filled_from_meeting(conn, vault):
    """{{meeting_datetime}} and friends are replaced with the meeting's own
    details; unknown placeholders are left untouched."""
    from meetingnotes.llm.summary import fill_prompt_variables

    meeting_id = make_meeting(conn, vault)  # started 2026-07-02T14:00:00+01:00
    template = ("Meeting date and time: {{meeting_datetime}}\n"
                "Title: {{meeting_title}}\nDate: {{meeting_date}}\nKeep: {{unknown}}")

    filled = fill_prompt_variables(template, conn, meeting_id)

    assert "{{meeting_datetime}}" not in filled
    assert "2 July 2026" in filled and "14:00" in filled
    assert "Client review" in filled
    assert "{{unknown}}" in filled, "unknown placeholders are left as written"


def test_ac_1_5_e_em_dash_strip():
    """No em dashes survive the strip."""
    text = "The budget — which is tight — was approved.\n— A dangling aside\nEnd—start."
    stripped = strip_em_dashes(text)
    assert "—" not in stripped
    assert "The budget, which is tight, was approved." in stripped
    assert "- A dangling aside" in stripped
    assert "End, start." in stripped
