/**
 * Settings - Idea11y Section 4.1, Figure 2a.
 *
 * The paper's settings section offered: mode, voice (consistent or coded), and whether co-presence
 * is signalled by earcon, speech, both, or none. EchoNotes keeps the same controls, minus the
 * collaboration ones:
 *
 *   - Voice: consistent, or coded by note type
 *   - Feedback: earcon / speech / both / none
 *   - Announce cluster summaries automatically
 *   - Announce quality score with note info
 *   - Capture trigger: spacebar, hotkey, or hardware
 *
 * Changing a setting takes effect immediately and is confirmed aloud, so the user can hear the
 * difference rather than hunting for a save button.
 */

import type { Settings } from "@/types";

export interface SettingsPanelProps {
  settings: Settings;
  onChange: (next: Partial<Settings>) => void;
}

export function SettingsPanel(_props: SettingsPanelProps) {
  throw new Error("not implemented");
}
