/**
 * "Read aloud" control.
 *
 * Toggles between speaking and stopping, and its accessible name says which it
 * will do — a button whose label never changes leaves a listener guessing
 * whether their press registered.
 */

import { useEffect, useState } from "react";

import { speak, speechSupported, stopSpeaking } from "@/a11y/speech";

interface Props {
  text: string;
  label?: string;
  className?: string;
}

export function SpeakButton({ text, label = "Read aloud", className }: Props) {
  const [speaking, setSpeaking] = useState(false);
  const supported = speechSupported();

  // Stop speech when this control goes away, so collapsing a note does not
  // leave a disembodied voice reading it.
  useEffect(() => {
    return () => {
      if (speaking) stopSpeaking();
    };
  }, [speaking]);

  if (!supported) return null;

  function toggle() {
    if (speaking) {
      stopSpeaking();
      setSpeaking(false);
      return;
    }
    const started = speak(text, { onEnd: () => setSpeaking(false) });
    setSpeaking(started);
  }

  return (
    <button
      type="button"
      className={className ?? "small-button"}
      onClick={toggle}
      aria-pressed={speaking}
    >
      {speaking ? "Stop reading" : label}
    </button>
  );
}
