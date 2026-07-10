"""The Whisper vocabulary prompt built from a meeting's people and glossary."""

from __future__ import annotations

from meetingnotes.pipeline.vocabulary import build_initial_prompt


def test_empty_inputs_give_no_prompt() -> None:
    assert build_initial_prompt([], []) is None
    assert build_initial_prompt(["  ", ""], []) is None


def test_names_and_terms_are_listed() -> None:
    prompt = build_initial_prompt(["Martin", "Zach"], ["Camunda", "CoSec"])
    assert prompt == "Participants: Martin, Zach. Terms: Camunda, CoSec."


def test_people_only_omits_the_terms_clause() -> None:
    assert build_initial_prompt(["Jake"], []) == "Participants: Jake."


def test_glossary_only_omits_the_participants_clause() -> None:
    assert build_initial_prompt([], ["Workato"]) == "Terms: Workato."


def test_order_is_preserved_and_duplicates_dropped() -> None:
    prompt = build_initial_prompt(["Martin", "martin", "Zach"], ["Zach", "CET"])
    # "martin" duplicates "Martin"; "Zach" already appears as a participant.
    assert prompt == "Participants: Martin, Zach. Terms: CET."
