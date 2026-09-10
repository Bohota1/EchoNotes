/**
 * The ARIA live region every announcement goes through.
 *
 * Nothing in EchoNotes changes silently: recording state, transcription progress, note added,
 * note moved, cluster summary refreshed, and every error are all announced here.
 *
 * Two regions, because politeness matters:
 *   - polite   for progress and confirmations, which wait for a gap in the user's reading
 *   - assertive for errors and recording state, which interrupt
 */

import type { ReactNode } from "react";

export type Politeness = "polite" | "assertive";

export interface AnnouncerContextValue {
  announce: (message: string, politeness?: Politeness) => void;
  repeatLast: () => void;
}

export function AnnouncerProvider(_props: { children: ReactNode }) {
  throw new Error("not implemented");
}

export function useAnnouncer(): AnnouncerContextValue {
  throw new Error("not implemented");
}
