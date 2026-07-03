"""Section 2.1: scoping. The default scope is the current folder."""

import inspect

import pytest

from meetingnotes.llm.librarychat import DEFAULT_SCOPE, ChatScope, ask_library, retrieve


def test_ac_2_1_d_default_scope_current_folder():
    assert DEFAULT_SCOPE is ChatScope.FOLDER
    assert inspect.signature(retrieve).parameters["scope"].default is ChatScope.FOLDER
    assert inspect.signature(ask_library).parameters["scope"].default is ChatScope.FOLDER

    # Folder scope is real scoping, not a fallback: without the current
    # folder it refuses rather than quietly searching everything.
    class NoStore:
        def search(self, *args, **kwargs):
            raise AssertionError("must not search before scope is validated")

    class NoEmbedder:
        def embed_texts(self, texts):
            raise AssertionError("must not embed before scope is validated")

    with pytest.raises(ValueError):
        retrieve(NoStore(), NoEmbedder(), "question", scope=ChatScope.FOLDER, folder_id=None)
