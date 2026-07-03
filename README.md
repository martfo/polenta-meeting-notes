# Meeting Notes

A private, offline meeting notes app for macOS. It records a meeting, transcribes it locally
with speaker labels, writes a structured summary, and lets you chat with one transcript or
across a folder of them. Nothing that touches your audio, transcripts, or summaries leaves the
machine while the app is in use.

## What you need

- A Mac running macOS 14.4 or later, Apple Silicon.
- LM Studio, with a model loaded and its local server running on port 1234. A non-thinking
  instruct model works best for clean summaries, for example a current Qwen instruct model.
- ffmpeg, which the transcription pipeline uses to read audio. Install it once with
  `brew install ffmpeg`.
- FileVault turned on. The app keeps your meetings as files in a vault folder and relies on
  FileVault for encryption at rest.

## First-run setup

The app walks you through this once:

1. Choose where the vault lives, for example a folder called MeetingVault in your home folder.
2. Accept the pyannote model licence and paste a Hugging Face token. The token is stored in
   the macOS Keychain, never in a file.
3. The app downloads and caches the transcription and speaker models. This is the only time
   the app reaches the network. After this you can run it with networking off.
4. The app checks that LM Studio is reachable and a model is loaded, and tells you plainly if
   it is not.

## Permissions

The first time you record, macOS asks for two permissions:

- Microphone, so the app can hear you and anyone in the room.
- System audio recording, so the app can hear the other people on a call without a bot joining.

If you decline either, the app tells you what is missing rather than failing silently.

## Recording a meeting

Press record. For an online call on any platform, the app captures the call audio and your
microphone together, so it does not matter whether you are on Zoom, Teams, Meet, Slack, or a
browser call. For an in-person meeting it uses the microphone alone, and a separate conference
microphone will give better results than the built-in one when several people are round the
laptop. You can see input levels for both sources before you rely on them.

When you stop, the recording is saved and queued for processing, and you can start the next
meeting straight away. You do not have to wait for the previous one to finish. Meetings process
one at a time in the background, and the library shows where each one is up to.

## After the meeting

You get a transcript with speaker labels and a summary with three parts: the core items
discussed, the next steps with an owner against each one, and any open questions. The summary
is written in British English and is meant to be usable as it is, without editing.

Speaker names are worked out in this order: a voice you have named before is recognised
automatically, then the meeting's attendees are offered as names, then you can set or correct
any name by hand. If the app ever puts the wrong name on a voice, correct it once and it will
not make that same mistake again, because the correction teaches the app rather than just
fixing the one transcript.

There is a notes pane where you can type during the meeting and paste screenshots. Your notes
feed into the summary. Your own typed notes are left exactly as you wrote them.

## Folders, chat, and search

File each meeting in a folder. The app suggests one and you can accept it or pick another.

Ask questions of a single meeting in its chat box, for example what technology someone
mentioned or what their requirements were. To search across meetings, use the library chat and
choose whether to look in the current folder or across everything. It defaults to the current
folder.

## Where your files are

Everything is in the vault. Each meeting has its own folder holding the summary, the
transcript, the audio, your notes, and any pasted images. Use Reveal in Finder on any meeting
to open its folder directly. Raw recordings are kept for 30 days by default and then removed,
which you can change in settings. The transcript, summary, and notes are always kept.

## Logs

Errors are logged to a rotating file in the logs folder inside the vault, so they sit under the
same FileVault protection as the rest of your data. Each line is written in plain language with
a timestamp, and there is a matching machine-readable file for searching. The logs record what
went wrong and where, never the content of your meetings. Use Reveal logs in Finder to open the
folder.

## British English

Summaries and chat replies are put through a local British English pass before you see them.
Known American spellings are changed to British automatically, and a bundled British dictionary
quietly flags anything it does not recognise without changing names, technical terms, or code.
This runs on the machine and needs no network.

## Setting up a new Mac

In this order:

1. Install LM Studio, load a model (a non-thinking instruct model works best), and make
   sure its local server is on, on port 1234.
2. Open the MeetingNotes .dmg and drag the app to Applications.
3. Right-click the app in Applications and choose Open, then Open again. This one-time
   step is needed because the app is signed locally rather than notarised.
4. Pick where the vault should live, or point at an existing vault to open it as it is.
5. Paste your Hugging Face token (stored in the Keychain) and let the app fetch its
   backend and download the speech models. This first run is the only time the app uses
   the network.
6. Record or import a test meeting and watch it process through to a summary.

## Building and checking

`make gate` runs the fast test suite and is the single measure of a healthy build. The slower
tests that run the real transcription models run at phase boundaries with `make pipeline`,
and `make live-smoke` exercises a real loaded model on demand. `make dmg` builds the
installer; signing needs the one-off local certificate from scripts/make_signing_cert.sh.
The manual hardware checklist lives at docs/MANUAL_CHECKLIST.md.
