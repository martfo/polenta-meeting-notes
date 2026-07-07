"""Summary generation: the whole transcript plus my notes to the loaded
model, validated against the fixed headings, passed through the British
English pass, and written into meeting.md under the front matter.

The prompt template lives at settings/summary_prompt.md in the vault and is
read at generation time, so editing it takes effect on the next summary with
no rebuild.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from meetingnotes.language.britpass import british_pass
from meetingnotes.llm.client import LMStudioClient
from meetingnotes.storage import meetings as m
from meetingnotes.storage.frontmatter import write_meeting_md
from meetingnotes.storage.vault import Vault

MANDATORY_SECTIONS = ["core items discussed", "next steps"]
OPTIONAL_SECTIONS = ["decisions", "open questions"]

HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def find_sections(summary: str) -> set[str]:
    """A section is a level-two heading whose trimmed text matches one of the
    fixed names, case-insensitive."""
    known = set(MANDATORY_SECTIONS) | set(OPTIONAL_SECTIONS)
    found = set()
    for match in HEADING.finditer(summary):
        name = match.group(1).strip().lower()
        if name in known:
            found.add(name)
    return found


def missing_mandatory(summary: str) -> list[str]:
    found = find_sections(summary)
    return [name for name in MANDATORY_SECTIONS if name not in found]


def assemble_messages(
    prompt_template: str, transcript: str, notes: str, ocr_texts: list[str] | None = None,
) -> list[dict[str, str]]:
    """The summary prompt: the editable template, then the transcript, then
    my notes, then any text read out of pasted screenshots."""
    parts = [prompt_template.strip(), "# Transcript\n\n" + transcript.strip()]
    if notes.strip():
        parts.append("# My notes\n\n" + notes.strip())
    for text in ocr_texts or []:
        if text.strip():
            parts.append("# Text from a pasted image\n\n" + text.strip())
    return [{"role": "user", "content": "\n\n".join(parts)}]


@dataclass
class SummaryResult:
    body: str
    status: str  # ready or needs_attention
    flags: list[str] = field(default_factory=list)
    attempts: int = 1


def generate_summary_text(
    client: LMStudioClient, prompt_template: str, transcript: str, notes: str,
    ocr_texts: list[str] | None = None, allowlist: set[str] | None = None,
) -> SummaryResult:
    """Generate, validate, regenerate once if a mandatory section is missing,
    then run the British English pass. A missing Open Questions section is
    fine and is not a warning."""
    messages = assemble_messages(prompt_template, transcript, notes, ocr_texts)
    text = client.chat(messages)
    attempts = 1
    if missing_mandatory(text):
        text = client.chat(messages)
        attempts = 2
    status = "needs_attention" if missing_mandatory(text) else "ready"
    passed = british_pass(text, allowlist)
    return SummaryResult(body=passed.text, status=status, flags=passed.flags, attempts=attempts)


def meeting_front_matter(conn: sqlite3.Connection, meeting_id: str,
                         summary_status: str | None = None) -> dict:
    row = m.get_meeting(conn, meeting_id)
    folder = None
    if row["folder_id"] is not None:
        folder = conn.execute(
            "SELECT name FROM folders WHERE id = ?", (row["folder_id"],)
        ).fetchone()["name"]
    attendees = [
        {"name": a["name"], **({"email": a["email"]} if a["email"] else {})}
        for a in m.list_attendees(conn, meeting_id)
    ]
    speakers = [
        r["display_name"] or r["diarised_label"]
        for r in conn.execute(
            "SELECT * FROM meeting_speakers WHERE meeting_id = ? ORDER BY id", (meeting_id,)
        ).fetchall()
    ]
    started = row["started_at"]
    return {
        "id": row["id"],
        "title": row["title"],
        "date": started[:10],
        "start_time": started[11:16],
        "duration_s": row["duration_s"],
        "source": row["source"],
        "folder": folder,
        "attendees": attendees,
        "speakers": speakers,
        "tags": [],
        "processing_status": row["processing_status"],
        "summary_status": summary_status or row["summary_status"],
    }


# Below this many words of actual speech, there is nothing to summarise, so
# the model is not asked (it would otherwise invent content).
MIN_SPEECH_WORDS = 8

NO_SPEECH_BODY = (
    "No speech was detected in this recording, so there is nothing to "
    "summarise. If you expected audio, check the microphone and system audio "
    "input levels for next time."
)


def transcript_word_count(transcript: str) -> int:
    """Words of spoken content, ignoring the heading and the bold speaker and
    timestamp lines."""
    words = 0
    for line in transcript.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("**["):
            continue
        words += len(stripped.split())
    return words


def summarise_meeting(
    conn: sqlite3.Connection, vault: Vault, client: LMStudioClient, meeting_id: str,
    transcript: str, notes: str = "", ocr_texts: list[str] | None = None,
    allowlist: set[str] | None = None,
) -> SummaryResult:
    """The summarise stage: generate, write meeting.md, record the status.
    A recording with no real speech is not sent to the model; it gets a plain
    note instead of a fabricated summary."""
    if transcript_word_count(transcript) < MIN_SPEECH_WORDS and not notes.strip():
        m.set_summary_status(conn, meeting_id, "ready")
        conn.execute("UPDATE meetings SET summary_edited = 0 WHERE id = ?", (meeting_id,))
        conn.commit()
        front = meeting_front_matter(conn, meeting_id, summary_status="ready")
        write_meeting_md(vault.meeting_md_path(meeting_id), front, NO_SPEECH_BODY)
        return SummaryResult(body=NO_SPEECH_BODY, status="ready", attempts=0)

    prompt_template = vault.summary_prompt_path.read_text()
    result = generate_summary_text(client, prompt_template, transcript, notes, ocr_texts, allowlist)
    m.set_summary_status(conn, meeting_id, result.status)
    # A fresh machine summary: any earlier hand edits are gone by definition.
    conn.execute("UPDATE meetings SET summary_edited = 0 WHERE id = ?", (meeting_id,))
    conn.commit()
    front = meeting_front_matter(conn, meeting_id, summary_status=result.status)
    write_meeting_md(vault.meeting_md_path(meeting_id), front, result.body)
    return result
