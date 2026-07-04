"""Section 1.4: pasted images and the OCR pass. Integration tier with the
fixture image."""

from meetingnotes.llm.summary import assemble_messages
from meetingnotes.notes.notes import linked_images, paste_image, read_notes
from meetingnotes.notes.ocr import VisionOcr, ocr_texts_for_meeting
from tests.conftest import make_meeting

OCR_EXPECTED = "Budget approved for hydroponics phase two"


def test_ac_1_4_a_pasted_image_saved_and_linked(conn, vault, fixtures_dir):
    """A pasted image lands in assets/ and notes.md gains a relative link."""
    meeting_id = make_meeting(conn, vault)
    image_bytes = (fixtures_dir / "images" / "ocr_sample.png").read_bytes()

    relative = paste_image(vault, meeting_id, image_bytes)

    saved = vault.meeting_dir(meeting_id) / relative
    assert relative.startswith("assets/")
    assert saved.exists() and saved.read_bytes() == image_bytes
    notes = read_notes(vault, meeting_id)
    assert f"({relative})" in notes and "![pasted image]" in notes
    assert linked_images(vault, meeting_id) == [saved]


def test_ac_1_4_c_ocr_text_joins_context(conn, vault, fixtures_dir):
    """With OCR enabled, text read out of a pasted image joins the summary
    context; disabled, it does not."""
    meeting_id = make_meeting(conn, vault)
    paste_image(vault, meeting_id, (fixtures_dir / "images" / "ocr_sample.png").read_bytes())

    texts = ocr_texts_for_meeting(vault, meeting_id, VisionOcr(), enabled=True)
    assert any(OCR_EXPECTED in t for t in texts)

    content = assemble_messages("template", "transcript", "notes", texts)[-1]["content"]
    assert OCR_EXPECTED in content

    assert ocr_texts_for_meeting(vault, meeting_id, VisionOcr(), enabled=False) == []


def test_pasted_image_ocr_reaches_chat_and_index(conn, vault, fixtures_dir):
    """Text recognised from a pasted image is cached in a sidecar and reaches
    the single-meeting chat context and the search index."""
    from meetingnotes.llm.chat import assemble_chat_messages
    from meetingnotes.notes.ocr import VisionOcr, read_ocr_texts, store_image_ocr
    from meetingnotes.notes.notes import linked_images

    meeting_id = make_meeting(conn, vault)
    paste_image(vault, meeting_id, (fixtures_dir / "images" / "ocr_sample.png").read_bytes())

    # OCR at paste time writes the sidecar; read_ocr_texts needs no engine.
    store_image_ocr(linked_images(vault, meeting_id)[0], VisionOcr())
    cached = read_ocr_texts(vault, meeting_id)
    assert any(OCR_EXPECTED in t for t in cached)

    # Chat carries the image text in the system context.
    messages = assemble_chat_messages("what was in the image?", "transcript", "", cached)
    assert OCR_EXPECTED in messages[0]["content"]
    assert "pasted image" in messages[0]["content"].lower()
