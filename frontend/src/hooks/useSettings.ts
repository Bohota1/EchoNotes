/**
 * Accessibility settings - Idea11y Section 4.1a.
 *
 * Persisted server-side rather than in localStorage: these are the settings that make the app
 * usable at all, so they must follow the user to a new machine, not be re-discovered there.
 */

import type { Settings } from "@/types";

export interface UseSettings {
  settings: Settings | null;
  update: (next: Partial<Settings>) => Promise<void>;
}

export function useSettings(): UseSettings {
  throw new Error("not implemented");
}
