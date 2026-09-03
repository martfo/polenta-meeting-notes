"""Adjusting an already-imported meeting's recorded date."""

from __future__ import annotations

from meetingnotes.llm.summary import meeting_front_matter
from meetingnotes.storage import meetings as m
from meetingnotes.storage.frontmatter import read_meeting_md, write_meeting_md
from meetingnotes.storage.refresh import refresh_meeting_files
from tests.conftest import make_meeting


def test_set_started_at_updates_column_and_listing(conn, vault):
    mid = make_meeting(conn, vault)  # created at 2026-07-02T14:00
    m.set_started_at(conn, mid, "2026-08-19T09:30:00+01:00")
    assert m.get_meeting(conn, mid)["started_at"] == "2026-08-19T09:30:00+01:00"
    row = next(x for g in m.library_listing(conn) for x in g["meetings"] if x["id"] == mid)
    assert row["date"] == "2026-08-19"          # the library files it under the new day
    assert row["started_at"].startswith("2026-08-19T09:30")


def test_refresh_rewrites_meeting_md_date(conn, vault):
    mid = make_meeting(conn, vault)
    md = vault.meeting_md_path(mid)
    write_meeting_md(md, meeting_front_matter(conn, mid), "## Core items discussed\n- x")

    m.set_started_at(conn, mid, "2026-08-19T09:30:00+01:00")
    refresh_meeting_files(conn, vault, mid)

    front, body = read_meeting_md(md)
    assert front["date"] == "2026-08-19"
    assert front["start_time"] == "09:30"
    assert "Core items discussed" in body  # the summary body is preserved
