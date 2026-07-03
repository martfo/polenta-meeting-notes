"""The optional local OCR pass over pasted images, so text in a screenshot
can join the summary context. Apple's Vision framework through pyobjc: on the
machine, offline, no extra install. Full image understanding with a vision
model is out of scope."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from meetingnotes.notes.notes import linked_images
from meetingnotes.storage.vault import Vault


class OcrEngine(Protocol):
    def extract_text(self, image_path: Path) -> str: ...


class VisionOcr:
    def extract_text(self, image_path: Path) -> str:
        import Vision
        from Foundation import NSURL

        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
            NSURL.fileURLWithPath_(str(image_path)), None
        )
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        ok, _error = handler.performRequests_error_([request], None)
        if not ok:
            return ""
        lines = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if candidates:
                lines.append(str(candidates[0].string()))
        return "\n".join(lines)


def ocr_texts_for_meeting(
    vault: Vault, meeting_id: str, engine: OcrEngine | None = None,
    enabled: bool = True,
) -> list[str]:
    """OCR text for each image linked from the meeting's notes, when the OCR
    pass is enabled in config."""
    if not enabled:
        return []
    engine = engine or VisionOcr()
    texts = []
    for image in linked_images(vault, meeting_id):
        text = engine.extract_text(image).strip()
        if text:
            texts.append(text)
    return texts
