/**
 * Accessibility tests for the outline - Idea11y Section 4.1.
 *
 * These assert the structural promises the paper's design depends on. They are not cosmetic:
 * if a heading level goes missing, heading navigation silently degrades and the outline stops
 * being navigable, with nothing visibly wrong.
 */

import { describe, it } from "vitest";

describe("OutlineView", () => {
  it.todo("renders subjects as h1 and topics as h2");
  it.todo("renders notes as list items inside a ul");
  it.todo("never skips a heading level");
  it.todo("gives every interactive element an accessible name");
  it.todo("places the cluster summary immediately after its topic heading");
  it.todo("has no axe violations");
});
