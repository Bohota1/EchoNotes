/**
 * One subject - Idea11y's Frame level, rendered as an h1.
 *
 * The Unfiled subject renders last and says so in its heading, so a user walking headings knows
 * it holds notes waiting to be filed rather than a real subject.
 */

import type { Subject } from "@/types";

export interface SubjectSectionProps {
  subject: Subject;
}

export function SubjectSection(_props: SubjectSectionProps) {
  throw new Error("not implemented");
}
