"""Single-meeting chat: the question goes to the loaded model with the full
transcript and my notes, speaker names already resolved so it can attribute
correctly. No retrieval at this scale."""

from __future__ import annotations

from meetingnotes.language.britpass import british_pass
from meetingnotes.llm.client import LMStudioClient

SYSTEM_PROMPT = (
    "You answer questions about one meeting, using only the transcript and "
    "notes provided. Speaker names in the transcript are correct; attribute "
    "statements to the right person. Answer plainly in British English. If "
    "the transcript does not contain the answer, say so."
)


def assemble_chat_messages(question: str, transcript: str, notes: str = "") -> list[dict[str, str]]:
    content = "# Transcript\n\n" + transcript.strip()
    if notes.strip():
        content += "\n\n# My notes\n\n" + notes.strip()
    content += "\n\n# Question\n\n" + question.strip()
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def ask_meeting(
    client: LMStudioClient, question: str, transcript: str, notes: str = "",
    allowlist: set[str] | None = None,
) -> str:
    answer = client.chat(assemble_chat_messages(question, transcript, notes))
    return british_pass(answer, allowlist).text
