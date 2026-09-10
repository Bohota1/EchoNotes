/**
 * Keyboard map. Single source of truth; `docs/accessibility.md` documents it for users.
 *
 * The Ctrl+Alt+X pattern comes from Idea11y (Section 4.2, 4.3), which chose it because it does
 * not collide with keys JAWS and NVDA reserve for themselves.
 */

export const SHORTCUTS = {
  RECORD_HOLD: "Space",                 // hold to record (see SpacebarTrigger for the guards)
  RECORD_TOGGLE: "ctrl+alt+Space",      // toggle, for long lectures
  EDIT_NOTE: "ctrl+alt+e",              // Idea11y Section 4.2
  MOVE_NOTE: "ctrl+alt+m",              // Idea11y Section 4.2
  DELETE_NOTE: "ctrl+alt+d",            // Idea11y Section 4.2
  NOTE_INFO: "ctrl+alt+i",              // Idea11y Section 4.3
  ADD_NOTE: "ctrl+alt+n",               // Idea11y Section 4.2
  SPEAK_SUMMARY: "ctrl+alt+s",          // Idea11y Section 4.1
  GO_OVERVIEW: "ctrl+alt+o",            // Idea11y Section 4.1
  ASK: "ctrl+alt+q",                    // EchoNotes Feature 4
  REPEAT_LAST: "ctrl+alt+.",
  SETTINGS: "ctrl+alt+,",
} as const;

export type ShortcutName = keyof typeof SHORTCUTS;

/** Elements where Space must keep its native meaning. See docs/accessibility.md. */
export const SPACE_RESERVED_SELECTOR =
  'input, textarea, select, button, a[href], [contenteditable="true"], [role="button"], [role="checkbox"], [role="menuitem"]';
