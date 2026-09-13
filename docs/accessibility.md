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

**No other key does anything.** Tab, Escape, arrows, letters and Backspace are all swallowed. A
person who cannot see the page cannot tell what an unexpected key did: `Tab` silently moves focus
onto a button, and the next `Space` then presses that button instead of recording. With three
keys and nothing else, every press has one meaning wherever focus happens to be.

The keys are caught in the capture phase on the window, before any element sees them, so a focused
button, link or field cannot claim `Space` or `Enter` first. Combinations held with `Ctrl`, `Alt`
or the system key pass through: those belong to the browser and the operating system, and blocking
the few a page can block would only trap the user in the tab.

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

`Space`, `Shift` and `Enter`, as above - and nothing else. An earlier draft of this document listed
`Ctrl+Alt` shortcuts for editing, moving and deleting notes; none of them were ever built, and
under the three-key rule none will be.

### One real conflict to handle: the spacebar

`Space` is the requested trigger, and it is also how a screen reader activates a focused button
and how browsers scroll a page.

It used to be resolved by stepping aside: `Space` was left alone inside a text field or on a
focused button. That made its meaning depend on where focus was - something a user who cannot see
the page has no way to know. It is now resolved the other way: `Space` always records, and nothing
on the page can take it, because no other key can move focus onto anything that would.

**One component owns the key.** There is one microphone, so there can be one handler. An earlier
Capture panel bound `Space` on the window as well, and a single press reached both: the panel
fired a one-shot capture while the console started a recording. The panel has been removed rather
than made to negotiate, because two owners of one device is not a thing that can be made safe -
only a thing that can be made rarer.

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
