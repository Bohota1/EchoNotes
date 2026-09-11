/**
 * Smoke test: the app mounts, renders its landmarks, and survives a dead
 * backend by saying so rather than crashing.
 *
 * `fetch` is stubbed, so this needs no running server.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const SOURCES = [
  { name: "dummy", available: true, detail: "replaying sample_capture.wav", is_default: true },
  { name: "microphone", available: true, detail: "ready", is_default: false },
];

function stubFetch(handler: (url: string) => unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = handler(url);
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

const HEALTH = {
  status: "ok",
  capture_source: "dummy",
  capture_available: true,
  capture_detail: "replaying sample_capture.wav",
  asr_model: "base",
  llm_available: false,
};

afterEach(() => {
  // Vitest does not register testing-library's auto-cleanup unless `globals`
  // is on, so without this each render stacks on the last and queries find
  // duplicates.
  cleanup();
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("renders every landmark heading", async () => {
    stubFetch((url) => {
      if (url.includes("/health")) return HEALTH;
      if (url.includes("/capture/sources")) return SOURCES;
      if (url.includes("/reminders")) return { reminders: [], count: 0, spoken: "" };
      return [];
    });

    render(<App />);

    expect(
      screen.getByRole("heading", { name: "EchoNotes", level: 1 }),
    ).toBeDefined();
    for (const name of ["Status", "Capture", "Ask your notes"]) {
      expect(screen.getByRole("heading", { name, level: 2 })).toBeDefined();
    }
  });

  it("shows backend status once health resolves", async () => {
    stubFetch((url) => {
      if (url.includes("/health")) return HEALTH;
      if (url.includes("/capture/sources")) return SOURCES;
      if (url.includes("/reminders")) return { reminders: [], count: 0, spoken: "" };
      return [];
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Backend: connected/)).toBeDefined();
    });
    expect(screen.getByText(/Speech model: base/)).toBeDefined();
  });

  it("has a live region so nothing changes silently", () => {
    stubFetch(() => HEALTH);
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

    // Each panel reports its own failure, so several alerts is correct -
    // the user needs to know which part of the page is broken, not just that
    // something is.
    await waitFor(() => {
      expect(screen.getAllByText(/Cannot reach the backend/).length).toBeGreaterThan(0);
    });
  });

  it("warns that sample mode ignores the microphone", async () => {
    // The backend defaults to the `dummy` source, which replays a fixture. If
    // that is not said plainly, Record looks like it works while returning the
    // same canned sentence every time.
    stubFetch((url) => {
      if (url.includes("/health")) return HEALTH;
      if (url.includes("/capture/sources")) return SOURCES;
      if (url.includes("/reminders")) return { reminders: [], count: 0, spoken: "" };
      return [];
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/ignores your microphone/i)).toBeDefined();
    });
    expect(
      screen.getByRole("button", { name: /play sample recording/i }),
    ).toBeDefined();
  });

  it("offers start/stop on the microphone rather than a fixed length", async () => {
    // Nobody knows in advance how long a thought takes, so the microphone gets
    // a Start/Stop pair instead of a duration to pick up front.
    stubFetch((url) => {
      if (url.includes("/health")) return HEALTH;
      if (url.includes("/capture/sources")) return SOURCES;
      if (url.includes("/reminders")) return { reminders: [], count: 0, spoken: "" };
      return [];
    });

    render(<App />);

    const select = await screen.findByLabelText(/recording from/i);
    fireEvent.change(select, { target: { value: "microphone" } });

    expect(screen.getByRole("button", { name: /start recording/i })).toBeDefined();
    expect(screen.queryByLabelText(/record for/i)).toBeNull();
  });

  it("turns into a stop button once recording starts", async () => {
    stubFetch((url) => {
      if (url.includes("/health")) return HEALTH;
      if (url.includes("/capture/sources")) return SOURCES;
      if (url.includes("/capture/start")) {
        return {
          recording: true,
          capture_id: "abc",
          elapsed_seconds: 0,
          max_seconds: 300,
          hit_limit: false,
          spoken: "Recording.",
        };
      }
      if (url.includes("/reminders")) return { reminders: [], count: 0, spoken: "" };
      return [];
    });

    render(<App />);

    const select = await screen.findByLabelText(/recording from/i);
    fireEvent.change(select, { target: { value: "microphone" } });
    fireEvent.click(screen.getByRole("button", { name: /start recording/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /stop recording/i })).toBeDefined();
    });
    // Discard has to be reachable too, or a misfired recording can only be
    // ended by transcribing it.
    expect(screen.getByRole("button", { name: /discard/i })).toBeDefined();
    expect(screen.getByText(/Recording —/)).toBeDefined();
  });

  it("offers a voice-output control", async () => {
    stubFetch((url) => {
      if (url.includes("/health")) return HEALTH;
      if (url.includes("/capture/sources")) return SOURCES;
      if (url.includes("/reminders")) return { reminders: [], count: 0, spoken: "" };
      return [];
    });

    render(<App />);
    expect(
      screen.getByRole("heading", { name: "Voice output", level: 2 }),
    ).toBeDefined();
  });
});
