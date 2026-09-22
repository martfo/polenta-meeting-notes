"""Parsing a written transcript document into segments."""

from datetime import datetime

from meetingnotes.storage.transcript import render_transcript
from meetingnotes.tools.transcript_text import (
    apply_owner_label,
    parse_markdown_transcript,
    split_front_matter,
    transcript_duration_s,
)

# transcript.md exactly as this app writes it: one paragraph per turn.
OWN_FORMAT = """# Transcript

**[00:00:04] Martin**
Morning. Shall we start with the pipeline?

**[00:00:11] Nisha Patel**
Yes. The import path is the last piece. It needs a test over a real export.

**[00:01:02] Martin**
Agreed.
"""


def test_reads_this_apps_own_transcript_format():
    """A transcript.md written by the app round-trips back into segments."""
    parsed = parse_markdown_transcript(OWN_FORMAT)
    assert [s.speaker for s in parsed.segments] == ["Martin", "Nisha Patel", "Martin"]
    assert [s.start for s in parsed.segments] == [4.0, 11.0, 62.0]
    assert parsed.segments[0].text == "Morning. Shall we start with the pipeline?"
    # "# Transcript" is the section heading, not the meeting's name.
    assert parsed.title is None


def test_a_turn_wrapped_over_several_lines_stays_one_turn():
    parsed = parse_markdown_transcript(
        "**[00:00:11] Nisha Patel**\nThe import path is the last piece.\n"
        "It needs a test over a real export.\n")
    assert len(parsed.segments) == 1
    assert parsed.segments[0].text == (
        "The import path is the last piece. It needs a test over a real export.")


def test_rerendering_a_parsed_transcript_matches_the_original():
    """Parse then render is the identity on the app's own format, so a
    transcript exported from one vault imports into another unchanged."""
    parsed = parse_markdown_transcript(OWN_FORMAT)
    assert render_transcript(parsed.segments) == OWN_FORMAT


def test_plain_speaker_lines_with_and_without_timestamps():
    text = """Ben Adams: We reviewed the budget.
Roger Neel: Agreed, with one change.
[00:05:30] Ben Adams: Noted.
"""
    parsed = parse_markdown_transcript(text)
    assert [s.speaker for s in parsed.segments] == ["Ben Adams", "Roger Neel", "Ben Adams"]
    assert parsed.segments[2].start == 330.0
    # Untimed turns still advance, so the order is preserved.
    assert parsed.segments[0].start < parsed.segments[1].start


def test_front_matter_supplies_title_date_and_attendees():
    text = """---
title: Quarterly review
date: 2026-06-01 14:30
attendees:
  - Ben Adams
  - name: Roger Neel
---

Ben Adams: Let us begin.
"""
    parsed = parse_markdown_transcript(text)
    assert parsed.title == "Quarterly review"
    assert parsed.started_at is not None
    assert parsed.started_at.date() == datetime(2026, 6, 1).date()
    assert parsed.started_at.hour == 14 and parsed.started_at.minute == 30
    assert parsed.attendees == ["Ben Adams", "Roger Neel"]
    assert len(parsed.segments) == 1


def test_heading_gives_the_title_and_bullets_are_stripped():
    text = """# Weekly sync

- Ben Adams: First point.
> Roger Neel: Second point.
"""
    parsed = parse_markdown_transcript(text)
    assert parsed.title == "Weekly sync"
    assert [s.text for s in parsed.segments] == ["First point.", "Second point."]


def test_a_sentence_with_a_colon_is_not_read_as_a_speaker():
    """Only short, name-shaped labels become speakers; prose stays prose."""
    parsed = parse_markdown_transcript(
        "One thing to remember: the vault is never written outside its root.")
    assert len(parsed.segments) == 1
    assert parsed.segments[0].speaker is None
    assert parsed.segments[0].text.startswith("One thing to remember:")


def test_prose_with_no_speakers_still_imports_as_one_turn():
    parsed = parse_markdown_transcript(
        "We agreed the scope.\nThe work starts on Monday.")
    assert len(parsed.segments) == 1
    assert parsed.segments[0].speaker is None
    assert parsed.segments[0].text == "We agreed the scope. The work starts on Monday."


def test_a_transcript_section_wins_over_the_preamble():
    """A document with notes and then a transcript imports the speech, not
    the notes."""
    text = """# Client call

## Summary

We discussed the renewal.

## Transcript

Ben Adams: Shall we renew?
Roger Neel: Yes.

## Actions

Send the contract.
"""
    parsed = parse_markdown_transcript(text)
    assert [s.speaker for s in parsed.segments] == ["Ben Adams", "Roger Neel"]
    assert parsed.title == "Client call"


def test_empty_and_headers_only_documents_yield_nothing():
    assert parse_markdown_transcript("").segments == []
    assert parse_markdown_transcript("   \n\n").segments == []
    assert parse_markdown_transcript("---\ntitle: Nothing\n---\n").segments == []


def test_front_matter_that_is_not_a_mapping_is_treated_as_body():
    front, body = split_front_matter("---\njust text\n---\nBen: Hello.\n")
    assert front == {}
    assert "Ben: Hello." in body


def test_duration_comes_only_from_real_timestamps():
    """Synthetic times say nothing about length, so they give no duration."""
    timed = parse_markdown_transcript(OWN_FORMAT)
    assert transcript_duration_s(timed.segments) == 63

    untimed = parse_markdown_transcript("Ben Adams: One.\nRoger Neel: Two.")
    assert transcript_duration_s(untimed.segments) is None


# -- other tools' exports --------------------------------------------------

def test_granola_style_me_and_them_lines():
    """Granola writes the person recording as "Me"; the other side is named."""
    parsed = parse_markdown_transcript(
        "Me: Shall we start with the renewal?\n"
        "Ben Adams: Yes, the terms are unchanged.\n"
        "Me: Good.\n")
    assert [s.speaker for s in parsed.segments] == ["Me", "Ben Adams", "Me"]

    named = apply_owner_label(parsed.segments, "Martin")
    assert [s.speaker for s in named] == ["Martin", "Ben Adams", "Martin"]


def test_a_name_and_time_on_its_own_line_opens_the_turn():
    """Otter, Teams, and Fireflies write the speaker and the time as a
    heading, with the words beneath it."""
    parsed = parse_markdown_transcript(
        "Ben Adams   0:04\n"
        "We reviewed the budget this morning.\n"
        "It came in under plan.\n"
        "\n"
        "Roger Neel (1:12)\n"
        "Good. I will circulate the figures.\n")
    assert [s.speaker for s in parsed.segments] == ["Ben Adams", "Roger Neel"]
    assert [s.start for s in parsed.segments] == [4.0, 72.0]
    assert parsed.segments[0].text == (
        "We reviewed the budget this morning. It came in under plan.")


def test_a_name_with_the_time_in_brackets_on_one_line():
    parsed = parse_markdown_transcript(
        "Ben Adams (00:00:04): We reviewed the budget.\n"
        "Roger Neel [00:01:12]: Noted.\n")
    assert [s.speaker for s in parsed.segments] == ["Ben Adams", "Roger Neel"]
    assert [s.start for s in parsed.segments] == [4.0, 72.0]


SRT = """1
00:00:04,000 --> 00:00:07,500
Ben Adams: We reviewed the budget this morning.

2
00:00:07,600 --> 00:00:09,000
It came in under plan.

3
00:01:12,000 --> 00:01:14,000
Roger Neel: Noted, thank you.
"""


def test_a_subrip_export_reads_as_speech():
    """Consecutive cues from one speaker are one turn, with real times."""
    parsed = parse_markdown_transcript(SRT)
    assert [s.speaker for s in parsed.segments] == ["Ben Adams", None, "Roger Neel"]
    assert parsed.segments[0].start == 4.0
    assert parsed.segments[0].end == 7.5
    assert parsed.segments[2].start == 72.0
    # The renderer groups the run, so the caption split does not show.
    rendered = render_transcript(parsed.segments)
    assert "**[00:00:04] Ben Adams**" in rendered
    assert "**[00:01:12] Roger Neel**" in rendered


VTT = """WEBVTT

NOTE recorded by a meeting tool

00:00:04.000 --> 00:00:07.500
<v Ben Adams>We reviewed the budget this morning.</v>

00:01:12.000 --> 00:01:14.000
<v Roger Neel>Noted, thank you.</v>
"""


def test_a_webvtt_export_uses_its_voice_spans():
    parsed = parse_markdown_transcript(VTT)
    assert [s.speaker for s in parsed.segments] == ["Ben Adams", "Roger Neel"]
    assert [s.text for s in parsed.segments] == [
        "We reviewed the budget this morning.", "Noted, thank you."]
    assert parsed.segments[1].start == 72.0


def test_cue_numbers_are_not_mistaken_for_speech():
    """A SubRip cue number is recognised by the time line under it, so it is
    dropped, while a spoken line that is only a number is kept."""
    parsed = parse_markdown_transcript(SRT)
    assert parsed.segments[0].text == "We reviewed the budget this morning."
    assert all(not s.text.strip().isdigit() for s in parsed.segments)

    spoken = parse_markdown_transcript(
        "1\n00:00:04,000 --> 00:00:06,000\nBen Adams: How many?\n\n"
        "2\n00:00:06,000 --> 00:00:07,000\n42\n")
    assert spoken.segments[-1].text == "42"


def test_a_cue_file_keeps_a_real_duration():
    assert transcript_duration_s(parse_markdown_transcript(SRT).segments) == 74


def test_short_timestamps_without_hours_are_minutes_and_seconds():
    parsed = parse_markdown_transcript("[5:30] Ben Adams: Half past five in.\n")
    assert parsed.segments[0].start == 330.0
