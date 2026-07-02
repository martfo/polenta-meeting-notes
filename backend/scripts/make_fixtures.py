"""Generate the committed test fixtures.

A build-time developer step, never run by the app. It uses the macOS `say`
command so the audio clips have a known transcript and known speaker
identities, renders the OCR sample image, writes the controlled embedding
vectors used by the enrolment tests, and writes the canned LM Studio
responses. Run from the backend directory:

    uv run python scripts/make_fixtures.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures"

SAMPLE_RATE = 16000
GAP_SECONDS = 0.6

# The meeting script. Speaker A is the British voice, speaker B the American
# one, so diarisation has two clearly different voices to separate. The word
# "hydroponics" is the known keyword the pipeline tests assert on.
VOICE_A = "Daniel"
VOICE_B = "Samantha"

MEETING_SCRIPT = [
    ("SPEAKER_00", VOICE_A, "Good afternoon everyone. Today we are reviewing the hydroponics project budget and the delivery timeline for the client."),
    ("SPEAKER_01", VOICE_B, "Thanks Daniel. The greenhouse sensors arrived on Tuesday, and installation begins next week if the wiring is approved."),
    ("SPEAKER_00", VOICE_A, "That works well. Please send the revised schedule to the whole team before Friday."),
    ("SPEAKER_01", VOICE_B, "Will do. I still need a decision about the irrigation controller supplier before we can order anything."),
]

SECOND_CLIP_TEXT = (
    "Hello again. This is a short follow up about the hydroponics budget "
    "review we discussed earlier in the week."
)

OCR_TEXT = "Budget approved for hydroponics phase two"


def say_to_wav(voice: str, text: str, out: Path) -> None:
    subprocess.run(
        ["say", "-v", voice, "-o", str(out), f"--data-format=LEI16@{SAMPLE_RATE}", text],
        check=True,
    )


def read_samples(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SAMPLE_RATE and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(samples.astype(np.int16).tobytes())


def word_timings(text: str, start: float, end: float) -> list[dict]:
    """Approximate per-word timings by spreading the utterance over its words,
    weighted by word length. Monotonic within the segment by construction."""
    words = text.split()
    weights = np.array([len(w) + 1 for w in words], dtype=float)
    edges = np.concatenate([[0.0], np.cumsum(weights)]) / weights.sum()
    span = end - start
    return [
        {"word": w, "start": round(start + edges[i] * span, 3), "end": round(start + edges[i + 1] * span, 3)}
        for i, w in enumerate(words)
    ]


def build_meeting_clip() -> None:
    audio_dir = FIXTURES / "audio"
    seg_dir = FIXTURES / "segments"
    audio_dir.mkdir(parents=True, exist_ok=True)
    seg_dir.mkdir(parents=True, exist_ok=True)

    gap = np.zeros(int(GAP_SECONDS * SAMPLE_RATE), dtype=np.int16)
    pieces: list[np.ndarray] = [gap]
    cursor = GAP_SECONDS
    segments = []
    tmp = audio_dir / "_utterance.wav"
    for label, voice, text in MEETING_SCRIPT:
        say_to_wav(voice, text, tmp)
        samples = read_samples(tmp)
        start = cursor
        end = cursor + len(samples) / SAMPLE_RATE
        segments.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "speaker": label,
                "text": text,
                "words": word_timings(text, start, end),
            }
        )
        pieces.extend([samples, gap])
        cursor = end + GAP_SECONDS
    tmp.unlink()

    write_wav(audio_dir / "two_speaker_meeting.wav", np.concatenate(pieces))
    (seg_dir / "two_speaker_meeting.json").write_text(
        json.dumps({"language": "en", "segments": segments}, indent=2) + "\n"
    )

    say_to_wav(VOICE_A, SECOND_CLIP_TEXT, audio_dir / "speaker_a_second_clip.wav")


def build_ocr_image() -> None:
    from PIL import Image, ImageDraw, ImageFont

    out = FIXTURES / "images"
    out.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (1200, 220), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
    draw.text((40, 80), OCR_TEXT, fill="black", font=font)
    img.save(out / "ocr_sample.png")
    (out / "ocr_sample.txt").write_text(OCR_TEXT + "\n")


def build_embedding_vectors() -> None:
    """Controlled 8-dimensional unit vectors for the enrolment tests.

    Each cluster vector has exactly two non-zero components, so its cosine
    similarity to the matching basis vector is simply its first component.
    """
    out = FIXTURES / "embeddings"
    out.mkdir(parents=True, exist_ok=True)

    def unit(i: int) -> list[float]:
        v = np.zeros(8)
        v[i] = 1.0
        return v.tolist()

    def mix(main: int, other: int, cos: float) -> list[float]:
        v = np.zeros(8)
        v[main] = cos
        v[other] = float(np.sqrt(1.0 - cos * cos))
        return [round(x, 6) for x in v.tolist()]

    vectors = {
        # Gallery examples.
        "ben_positive_1": unit(0),
        "roger_positive_1": unit(2),
        # A clear match to Ben: cosine 0.9 against ben_positive_1.
        "cluster_ben_match": mix(0, 1, 0.9),
        # Ben again from a different clip: cosine 0.88. Used by the
        # enrol-then-recognise test.
        "cluster_ben_second_clip": mix(0, 3, 0.88),
        # Too far from everyone: cosine 0.3.
        "cluster_low_similarity": mix(0, 4, 0.3),
        # A different person whose voice sits close to Ben: cosine 0.85.
        # Used to force the false match that the correction tests undo.
        "cluster_false_match": mix(0, 5, 0.85),
        # Positive similarity 0.8 to Ben, used with a stored negative at
        # cosine 0.75 to exercise the veto margin.
        "cluster_near_negative": mix(0, 6, 0.8),
        "ben_negative_close": mix(0, 6, 0.75),
        # Segment embeddings for the mean-and-normalise test.
        "segment_a": unit(0),
        "segment_b": unit(1),
    }
    (out / "controlled_vectors.json").write_text(json.dumps(vectors, indent=2) + "\n")


def build_llm_fixtures() -> None:
    out = FIXTURES / "llm"
    out.mkdir(parents=True, exist_ok=True)

    # A well formed summary. It deliberately carries an em dash and two
    # American spellings so the tests can prove the British English pass runs
    # on everything the model produces before it is saved.
    (out / "summary_ok.md").write_text(
        "## Core items discussed\n\n"
        "### Hydroponics budget\n"
        "The team organized a review of the project budget — the greenhouse "
        "sensors arrived on Tuesday and installation begins next week once the "
        "wiring is approved.\n\n"
        "### Delivery timeline\n"
        "The revised schedule is due with the whole team before Friday, and the "
        "color coding of the plan will follow the client's template.\n\n"
        "## Next Steps\n\n"
        "- Samantha to send the revised schedule to the whole team before Friday.\n"
        "- Daniel to decide on the irrigation controller supplier.\n\n"
        "## Open Questions\n\n"
        "- Which irrigation controller supplier will be used?\n"
    )

    (out / "summary_no_open_questions.md").write_text(
        "## Core items discussed\n\n"
        "### Hydroponics budget\n"
        "The budget review covered the sensor delivery and the installation plan.\n\n"
        "## Next Steps\n\n"
        "- Samantha to send the revised schedule before Friday.\n"
    )

    (out / "summary_missing_mandatory.md").write_text(
        "## Core items discussed\n\n"
        "### Hydroponics budget\n"
        "The budget review covered the sensor delivery and the installation plan.\n\n"
        "## Open Questions\n\n"
        "- Which supplier will be used?\n"
    )

    (out / "folder_suggestion_ok.json").write_text('{ "folder": "Clients", "is_new": false }\n')
    (out / "folder_suggestion_new.json").write_text('{ "folder": "Hydroponics", "is_new": true }\n')
    (out / "folder_suggestion_unknown.json").write_text('{ "folder": "Somewhere Else", "is_new": false }\n')
    (out / "folder_suggestion_malformed.txt").write_text("I think Clients would be the best folder for this one!\n")

    (out / "chat_answer.md").write_text(
        "Ben mentioned the greenhouse sensors — they arrived on Tuesday and "
        "installation was organized for the following week.\n"
    )


def main() -> None:
    build_meeting_clip()
    build_ocr_image()
    build_embedding_vectors()
    build_llm_fixtures()
    print("fixtures written to", FIXTURES)


if __name__ == "__main__":
    sys.exit(main())
