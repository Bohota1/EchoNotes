/**
 * Content quality - LNT Section 3.5, Tables 2 and 6.
 *
 * Shows the four metrics (readability, cohesion, coherence, entropy) and the score Qi from
 * Equation 5, as a table with real th scopes so a screen reader can read it by row.
 *
 * Every number is paired with its meaning in words. "0.727" tells a listener nothing on its own;
 * "0.73, good - readable, with clear themes" does.
 */

import type { Quality } from "@/types";

export interface QualityPanelProps {
  quality: Quality;
}

export function QualityPanel(_props: QualityPanelProps) {
  throw new Error("not implemented");
}
