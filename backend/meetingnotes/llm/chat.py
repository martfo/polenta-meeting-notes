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


def assemble_chat_messages(
    question: str, transcript: str, notes: str = "",
    ocr_texts: list[str] | None = None,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """The transcript, notes, and any text read from pasted images ride in the
    system message, so follow-up turns keep the full context without repeating
    it."""
    system = SYSTEM_PROMPT + "\n\n# Transcript\n\n" + transcript.strip()
    if notes.strip():
        system += "\n\n# My notes\n\n" + notes.strip()
    for text in ocr_texts or []:
        if text.strip():
            system += "\n\n# Text from a pasted image\n\n" + text.strip()
    messages = [{"role": "system", "content": system}]
    for turn in history or []:
        messages.append({"role": "user", "content": turn["question"]})
        messages.append({"role": "assistant", "content": turn["answer"]})
    messages.append({"role": "user", "content": question.strip()})
    return messages


def ask_meeting(
    client: LMStudioClient, question: str, transcript: str, notes: str = "",
    ocr_texts: list[str] | None = None,
    history: list[dict[str, str]] | None = None,
    allowlist: set[str] | None = None,
) -> str:
    answer = client.chat(
        assemble_chat_messages(question, transcript, notes, ocr_texts, history))
    return british_pass(answer, allowlist).text
