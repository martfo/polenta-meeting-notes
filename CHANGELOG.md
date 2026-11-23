# Changes

Newest first. "Runtime" is the backend version the app sets up; a new runtime means the app shows
the setup screen once after updating, and you click **Set up the backend** then **Continue**.

## 2026-11-23: keep the library from outgrowing the disk (runtime 42)

Each recording used to be stored twice: once as a raw capture and once in its meeting. The raw
capture is now removed as soon as the meeting holds an identical copy, and the copies left by
earlier versions are cleared on first start. Anything with no identical copy in a meeting is
kept. This roughly halves how much each hour of recording uses.

Settings has a new **Storage** section. It shows how big the library is, what takes the space,
how much was recorded in the last 30 days, and how much disk is free. It also has a **Keep
recordings for** setting: Forever (the default), 1 year, 6 months, 90 days or 30 days. Past
that age, a meeting's recording is either deleted or moved to a folder you choose, such as an
external drive. Transcripts, summaries, notes, screenshots and search are always kept.
Meetings still processing, or with a problem, keep their recording. Before a new setting
removes anything, you're shown how many meetings, hours and gigabytes it affects. A meeting
whose recording has gone says so, and can't be transcribed again.

An orange banner appears when the disk holding the library has less than 10 GB free, saying
roughly how many hours of recording are left.

After updating, the setup screen appears once: click **Set up the backend**, then **Continue**.

## 2026-11-19: take notes during a call (runtime 41)

When you start recording, the meeting appears in the library straight away, marked
**recording**, and opens on its Notes tab. Type notes, paste links (they are listed below the
notes and open with a click) and paste screenshots while the call is going; notes save on
their own as you type. When you stop, the recording is attached to the same meeting, and the
transcript and summary follow as usual, with your notes and screenshots feeding the summary.
If a recording captures no audio, the meeting is kept only if you wrote something in it.

After updating, the setup screen appears once: click **Set up the backend**, then **Continue**.

## 2026-11-18: your microphone is kept for the whole meeting

Your side of a meeting could go missing when a call app switched AirPods to their call mode or
the microphone changed, while the other side was recorded as normal. The microphone now
restarts on its own within a second or two, and if it is missing for more than a few seconds an
orange note beside the level meters says so until it is back. No setup screen after updating.

## 2026-10-28: first public release (runtime 40)

Record or import meetings, transcribe them locally with speaker labels, write structured
summaries with a local LLM, and search or chat across your library. Everything runs on your Mac.
