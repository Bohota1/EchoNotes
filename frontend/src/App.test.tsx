/**
 * Smoke tests for the page as it is: the landmarks, the three keys, the two
 * settings, and a dead backend reported rather than crashing.
 *
 * `fetch` is stubbed, so these need no running server.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

function stubFetch(handler: (url: string) => unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const body = handler(String(input));
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function emptyBackend(url: string): unknown {
  if (url.includes("/reminders")) return { reminders: [], count: 0, spoken: "" };
  return [];
}

beforeEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.contrast;
});

afterEach(() => {
  // Vitest does not register testing-library's auto-cleanup unless `globals`
  // is on, so without this each render stacks on the last.
  cleanup();
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("renders every landmark heading", () => {
    stubFetch(emptyBackend);
    render(<App />);

    expect(screen.getByRole("heading", { name: "EchoNotes", level: 1 })).toBeDefined();
    for (const name of ["Voice", "Knowledge graph", "Notes (0)", "Reminders (0)"]) {
      expect(screen.getByRole("heading", { name, level: 2 })).toBeDefined();
    }
    expect(screen.getByRole("main")).toBeDefined();
    expect(screen.getByRole("complementary", { name: "Reminders and notes" })).toBeDefined();
  });

  it("offers the three keys, named by what they do and which key does it", () => {
    stubFetch(emptyBackend);
    render(<App />);

    expect(screen.getByRole("button", { name: "Record a note (Space)" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Start a conversation (Shift)" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Ask a question (Enter)" })).toBeDefined();
  });

  it("shows the knowledge graph's subjects, empty or not", async () => {
    const SUBJECTS = [{ id: "s1", name: "Operating Systems", is_unfiled: false, topic_count: 2 }];
    stubFetch((url) => (url.includes("/graph/subjects") ? SUBJECTS : emptyBackend(url)));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Operating Systems/)).toBeDefined();
    });
    expect(screen.getByText(/2 topics/)).toBeDefined();
  });

  it("has a live region so nothing changes silently", () => {
    stubFetch(emptyBackend);
    render(<App />);
    // Screen-reader users cannot see a status change; it has to be announced.
    expect(screen.getByRole("status")).toBeDefined();
  });

  it("explains an unreachable backend instead of crashing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getAllByText(/Cannot reach the backend/).length).toBeGreaterThan(0);
    });
  });

  it("switches to high contrast and remembers it", () => {
    stubFetch(emptyBackend);
    render(<App />);

    const toggle = screen.getByRole("switch", { name: "High contrast" });
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(document.documentElement.dataset.contrast).toBe("standard");

    fireEvent.click(toggle);

    expect(toggle.getAttribute("aria-checked")).toBe("true");
    expect(document.documentElement.dataset.contrast).toBe("high");
    expect(window.localStorage.getItem("echonotes.contrast")).toBe("high");
  });

  it("starts in the contrast mode chosen last time", () => {
    window.localStorage.setItem("echonotes.contrast", "high");
    stubFetch(emptyBackend);
    render(<App />);

    expect(screen.getByRole("switch", { name: "High contrast" }).getAttribute("aria-checked")).toBe(
      "true",
    );
    expect(document.documentElement.dataset.contrast).toBe("high");
  });
});
