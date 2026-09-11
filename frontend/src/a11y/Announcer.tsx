/**
 * The ARIA live region every status change goes through.
 *
 * EchoNotes is built for blind and low-vision users, so nothing may change
 * silently: recording started, transcription finished, note saved, query
 * answered, and every error are all announced here.
 *
 * Two regions, because politeness matters:
 *   polite    progress and confirmations — waits for a gap in what the screen
 *             reader is already reading
 *   assertive errors and recording state — interrupts, because they change what
 *             the user should do next
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

type Politeness = "polite" | "assertive";

interface AnnouncerValue {
  announce: (message: string, politeness?: Politeness) => void;
  lastMessage: string;
}

const AnnouncerContext = createContext<AnnouncerValue | null>(null);

export function AnnouncerProvider({ children }: { children: ReactNode }) {
  const [polite, setPolite] = useState("");
  const [assertive, setAssertive] = useState("");
  const lastRef = useRef("");

  const announce = useCallback(
    (message: string, politeness: Politeness = "polite") => {
      if (!message) return;
      lastRef.current = message;

      const setter = politeness === "assertive" ? setAssertive : setPolite;
      // Clear first: re-announcing an identical string is a no-op for screen
      // readers unless the region's text actually changes, and "Note saved"
      // twice in a row is a normal thing to need to hear.
      setter("");
      window.setTimeout(() => setter(message), 50);
    },
    [],
  );

  const value = useMemo(
    () => ({ announce, lastMessage: lastRef.current }),
    [announce],
  );

  return (
    <AnnouncerContext.Provider value={value}>
      {children}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="visually-hidden"
      >
        {polite}
      </div>
      <div
        role="alert"
        aria-live="assertive"
        aria-atomic="true"
        className="visually-hidden"
      >
        {assertive}
      </div>
    </AnnouncerContext.Provider>
  );
}

export function useAnnouncer(): AnnouncerValue {
  const context = useContext(AnnouncerContext);
  if (!context) {
    throw new Error("useAnnouncer must be used inside an AnnouncerProvider");
  }
  return context;
}
