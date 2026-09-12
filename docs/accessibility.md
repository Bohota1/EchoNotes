# Accessibility contract

EchoNotes is built for blind and low-vision screen reader users. Accessibility is the primary
requirement, not a retrofit. Idea11y's design goals are the source for most of what follows.

## Non-negotiables

1. **Every action is reachable from the keyboard.** No action exists only on hover, drag or a
   mouse-only control. Idea11y §4.2 exists because drag-and-drop made Miro unusable.
2. **The outline is built from real semantics.** H1 Subject, H2 Topic/Project, `ul`/`li` notes.
   Users navigate with their screen reader's own heading and list commands (`H`, `Shift+H`, `1`,
   `2`, `3` in JAWS and NVDA). Do not replace this with a custom `role="tree"` widget.
3. **Nothing changes silently.** Every state change is announced through an ARIA live region:
   recording started/stopped, transcription progress, note created, note moved, cluster summary
   updated, errors.
4. **Focus is managed explicitly.** After a note is added, focus lands on that note. After a note
   is deleted, focus lands on the next sibling, or on the parent heading if there is none.
5. **Announcements are short and front-loaded.** The identifying information comes first — screen
   reader users interrupt constantly and should not have to wait through a preamble.

## The voice console

Three keys do everything, and every result is spoken. This is the primary interface; the panels
below it on the page are the same functionality for sighted use.

| Key | Action |
|---|---|
| `Space` | Record a note. Press again to stop; the note is transcribed, filed and read back |
| `Shift` | Open a conversation. Press again to end it |
| `Enter` | Ask a question. Inside a conversation, follow-ups keep their context |
| `Escape` | Cancel whatever is in progress |

Both recording keys **toggle**. Hold-to-talk was rejected here: it makes the user keep a finger
down while thinking, and a key released by accident ends the recording silently.

`Shift` is read on **release**, and only when it was pressed and released with nothing in between.
It is also a modifier - held down for every capital letter - so a press alone cannot mean anything;
a bare tap can.

### Why a conversation is a mode

Most questions are one-offs, and keeping history for those makes *retrieval* worse: an unrelated
previous question drags the search sideways. So context is opened deliberately and closed when the
topic changes. Inside a conversation a follow-up may say "it", and the question is rewritten to
stand alone **before** retrieval runs - embedding "how does it relate to system design" searches
for the words "it relate" and never finds the notes the user meant.

Rewriting changes only what is searched for. Every answer is still built solely from the notes that
search returns, and a conversation that cannot answer from them says so. A conversation that
invented continuity would be worse than one with no memory at all, because it sounds more
trustworthy.

### Reading notes back

"Read my system design notes out loud" is the one retrieval path that never touches the LLM. The
user asked for their own words, so summarising them - however well - would answer a question they
did not ask. Retrieval decides *which* notes; nothing rewrites *what* they say. Every other
question is answered from the retrieved notes, not read from them.

An explicit read verb is what separates the two: "read", "play back", "say". "What is system
design?" is a question and is answered as one.

## Keyboard map

| Key | Action | Source |
|---|---|---|
| `Space` (hold) | Push-to-talk: record while held, transcribe on release | EchoNotes Feature 1 |
| `Ctrl+Alt+Space` | Toggle-to-talk: start recording, press again to stop. For long lectures | EchoNotes Feature 1 |
| `Ctrl+Alt+E` | Edit the focused note (inline field pre-filled with its text) | Idea11y §4.2 |
| `Ctrl+Alt+M` | Move / re-file the focused note (drop-down of current Topics) | Idea11y §4.2 |
| `Ctrl+Alt+D` | Delete the focused note, with confirmation | Idea11y §4.2 |
| `Ctrl+Alt+I` | Note info: type, subject, capture time, source, `Qi` | Idea11y §4.3 note-info shortcut |
| `Ctrl+Alt+N` | Add a note under the focused Topic | Idea11y §4.2 add button |
| `Ctrl+Alt+S` | Speak the cluster summary of the focused Topic | Idea11y §4.1 |
| `Ctrl+Alt+O` | Jump to the Library Overview | Idea11y §4.1 board overview |
| `Ctrl+Alt+Q` | Ask a question by voice (RAG) | EchoNotes Feature 4 |
| `Enter` | Submit the inline input | Idea11y §4.2 |
| `Escape` | Cancel the inline input, stop speech | Idea11y §4.2 |
| `Ctrl+Alt+.` | Repeat the last announcement | EchoNotes |
| `Ctrl+Alt+,` | Open settings (voice coding, earcons, verbosity) | Idea11y §4.1a settings |

The `Ctrl+Alt+X` pattern is taken directly from Idea11y, which chose it because it does not
collide with JAWS or NVDA reserved keys.

### One real conflict to handle: the spacebar

`Space` is the requested trigger, and it is also how a screen reader activates a focused button
and how browsers scroll a page. Three rules resolve it, and they must be implemented in
`frontend/src/components/Capture/SpacebarTrigger.tsx`:

1. **Never capture `Space` while focus is inside a text input, textarea or `contenteditable`.**
   Typing a space must type a space.
2. **Never capture `Space` while focus is on a `button`, `checkbox`, `link` or `select`.** In those
   cases `Space` keeps its native activation meaning.
3. Everywhere else — the outline body, headings, list items, the page background — a held `Space`
   starts recording. Because screen readers in browse mode intercept keys before the page sees
   them, the app also registers `Ctrl+Alt+Space` as an always-available equivalent, and the
   settings panel lets the user rebind the trigger entirely (`CAPTURE_TRIGGER` in `.env`).

Announce the trigger state on every change: an earcon on start, a different earcon on stop, and a
spoken "Recording" / "Transcribing" / "Note added under <Topic>".

## Voice coding and earcons (Idea11y §4.3)

Idea11y read notes from different collaborators in different synthesized voices, so a listener
picked up a second channel of information without extra words. EchoNotes has one user, so the
second channel becomes **note type**:

| Note type | Default voice profile |
|---|---|
| Academic | voice A |
| Brainstorm / Idea | voice B |
| To-Do / Task | voice C |

Default is a **single consistent voice**, as in the paper; voice coding is opt-in through
settings. Earcons signal: recording start, recording stop, note saved, error, and end of list.
Each can be set to earcon, speech, both, or none — the exact four options Idea11y offered.

## Verbosity settings

Mirrors Idea11y's settings section:

- Mode: capture / review
- Voice: consistent, or coded by note type
- Feedback: earcon, speech, both, none
- Announce cluster summaries automatically: on / off
- Announce `Qi` with note info: on / off

## Testing

- Manual passes with **NVDA on Windows** and **VoiceOver on macOS**, the two Idea11y evaluated.
- Automated: `axe-core` in component tests, and assertions that every interactive element has an
  accessible name, that heading levels never skip, and that focus lands where this document says
  it should after add, delete and move.
