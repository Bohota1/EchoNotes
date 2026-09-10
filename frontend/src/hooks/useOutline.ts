/**
 * Outline state.
 *
 * The server owns the hierarchy; this hook only caches it and refetches after a mutation. No
 * optimistic local tree, deliberately: if the UI and the server disagreed about where a note
 * lives, a screen reader user would be told one thing and find another.
 */

import type { Outline } from "@/types";

export interface UseOutline {
  outline: Outline | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useOutline(): UseOutline {
  throw new Error("not implemented");
}
