# Polenta Meeting Notes

A private, offline meeting notes app for macOS. It records or imports a meeting, transcribes it
locally with speaker labels, writes a structured summary, and lets you chat with one transcript
or across a folder of them. Transcription and speaker separation run on the Apple GPU, and the
summary is written by a local LLM. Nothing that touches your audio, transcripts, or summaries
leaves the machine while the app is in use.

## What you need

- A Mac running macOS 14.4 or later, Apple Silicon.
- LM Studio, with a model loaded and its local server running on port 1234. A non-thinking
  instruct model works best for clean summaries, for example a current Qwen instruct model.
- FileVault turned on. The app keeps your meetings as files in a vault folder and relies on
  FileVault for encryption at rest.

## First-run setup

The app walks you through this once:

1. Choose where the vault lives, for example a folder called MeetingVault in your home folder.
2. Accept the pyannote model licence and paste a Hugging Face token. The token is stored in
   the macOS Keychain, never in a file, and is filled in for you if you ever see this step
   again after an update.
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

If a recording is tied to a calendar meeting, its scheduled end is not a hard cut-off: the app
keeps recording while the call is still going and stops once the audio has been quiet for a few
minutes, so a meeting that runs over is captured in full. A long-running safety limit still
stops a forgotten recording.

## Importing existing recordings and transcripts

You can bring in audio you already have. Use Settings, Import, or simply drag one or more files
onto the window and confirm. Most formats are accepted (mp3, m4a, wav) and are converted to the
vault's format on the way in, then transcribed, speaker-separated, and summarised exactly like a
live recording.

Recordings are often named for when they were made, for example `2026-08-19 14-30.m4a` or
`Recording 20260819_143000.mp3`. When the filename contains a date and time the meeting is filed
under that day rather than the moment you imported it. If a date cannot be read, or you want to
correct one, adjust the recorded date from the meeting's detail view and the library re-files it.

Transcripts that are already written up come in the same way. Drag a markdown, text, or subtitle
file onto the window, or use Settings, Import, and the turns are read into a meeting with no
audio. These shapes are understood:

- this app's own `transcript.md` (`**[00:01:02] Name**` headings);
- `Ben Adams: ...` lines, with or without a leading `[00:01:02]`, which is what Granola and most
  other tools write (Granola's own "Me" becomes your name, so the summary attributes your points
  to you);
- a speaker and a time as a heading, `Ben Adams   0:04` or `Ben Adams (0:04)`, with the words
  beneath it, as Teams, Otter, and Fireflies write it;
- `.vtt` and `.srt` subtitle exports, including WebVTT `<v Name>` voice spans.

YAML front matter (`title`, `date`, `attendees`) is honoured where it is there, a `## Transcript`
section is preferred over the notes around it, and prose with no speakers at all still imports.
Nothing needs transcribing, so the meeting goes straight to the search index and the summary.

To see how a file from an unfamiliar tool would be read, without importing anything:

```
cd backend && uv run python -m meetingnotes.tools.transcript_text "/path/to/export.md"
```

You can also import your history from Granola: use its CSV export (Settings, Profile, Generate
CSV) from Settings, Import. Those meetings come in with their transcript, summary, notes, and
folder, ready to search and chat.

## After the meeting

You get a transcript with speaker labels and a summary with these parts: the core items
discussed, the next steps with an owner against each one, decisions, and any open questions. The
summary is written in British English and is meant to be usable as it is.

Speaker names are worked out in this order: a voice you have named before is recognised
automatically, then the meeting's attendees are offered as names, then you can set or correct
any name by hand. If the app ever puts the wrong name on a voice, correct it once and it will
not make that same mistake again, because the correction teaches the app rather than just
fixing the one transcript.

The summary and notes are yours to edit. You can edit the summary in place, and a find and
replace tool fixes a mis-heard name or term across the summary and notes in one pass. There is a
notes pane where you can type during the meeting and paste screenshots; your notes feed into the
summary and your own words are left exactly as you wrote them.

Summarising needs LM Studio. If it is not running when a meeting finishes, the transcript is
still produced and the summary is left pending, then filled in on its own once LM Studio is back.

## Folders, chat, and search

File each meeting in a folder. The app suggests one, learning from how you have filed similar
meetings before, and you can accept it or pick another. Right-click any meeting in the library
for quick actions, and switch the library between folder and date views.

Ask questions of a single meeting in its chat box, for example what technology someone
mentioned or what their requirements were. To search across meetings, use the library chat and
choose whether to look in the current folder or across everything. It defaults to the current
folder.

## Where your files are

Everything is in the vault. Each meeting has its own folder holding the summary, the
transcript, the audio, your notes, and any pasted images. Use Reveal in Finder on any meeting
to open its folder directly. Raw recordings are kept for 30 days by default and then removed,
which you can change in settings. The transcript, summary, and notes are always kept.

## British English

Summaries and chat replies are put through a local British English pass before you see them.
Known American spellings are changed to British automatically, and a bundled British dictionary
quietly flags anything it does not recognise without changing names, technical terms, or code.
This runs on the machine and needs no network.

## Logs

Errors are logged to a rotating file in the logs folder inside the vault, so they sit under the
same FileVault protection as the rest of your data. Each line is written in plain language with
a timestamp, and there is a matching machine-readable file for searching. The logs record what
went wrong and where, never the content of your meetings. Use Reveal logs in Finder to open the
folder.

## Setting up a new Mac

In this order:

1. Install LM Studio, load a model (a non-thinking instruct model works best), and make
   sure its local server is on, on port 1234.
2. Open the Polenta Meeting Notes .dmg and drag the app to Applications.
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
