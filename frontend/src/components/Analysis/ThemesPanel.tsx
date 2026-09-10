/**
 * Themes and their topics - LNT Section 3.4.6, Table 5.
 *
 * Rendered as a nested list, not a tag cloud: a cloud conveys weight through size, which is
 * invisible to a screen reader. Weight is stated as text instead, and themes are ordered by it.
 */

import type { Theme } from "@/types";

export interface ThemesPanelProps {
  themes: Theme[];
}

export function ThemesPanel(_props: ThemesPanelProps) {
  throw new Error("not implemented");
}
