/**
 * Global shortcut handling.
 *
 * Two rules that are easy to get wrong and expensive to get wrong:
 *   1. A shortcut never fires while focus is in a text field, except Escape and Enter.
 *   2. A handled shortcut calls preventDefault, so the browser and the screen reader do not also
 *      act on it.
 */

import type { ShortcutName } from "./shortcuts";

export type ShortcutHandlers = Partial<Record<ShortcutName, (event: KeyboardEvent) => void>>;

export function useKeyboardShortcuts(_handlers: ShortcutHandlers, _enabled = true): void {
  throw new Error("not implemented");
}

/** True when the event target is a field where typing must win over shortcuts. */
export function isTextEntryTarget(_target: EventTarget | null): boolean {
  throw new Error("not implemented");
}
