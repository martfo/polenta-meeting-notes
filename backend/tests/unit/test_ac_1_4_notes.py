"""Section 1.4: the notes pane feeds the summary. Unit tier."""

from meetingnotes.llm.summary import assemble_messages


def test_ac_1_4_b_notes_in_summary_context():
    """Typed note text is included in the assembled summary context."""
    notes = "Supplier quote still outstanding. Chase Priya on Monday."
    messages = assemble_messages("template", "transcript text", notes)
    content = messages[-1]["content"]
    assert notes in content
    assert "# My notes" in content
