"""Parsing a written transcript document into segments."""

from datetime import datetime

from meetingnotes.storage.transcript import render_transcript
from meetingnotes.tools.transcript_text import (
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
