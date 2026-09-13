/**
 * High-contrast, large-text mode for low-vision users.
 *
 * Pure black, white and yellow at 125% text - the combination many low-vision
 * readers already set on their own devices. It starts on by itself when the
 * operating system asks for more contrast, and the user's own choice is
 * remembered after that.
 *
 * The mode is a `data-contrast` attribute on <html>, so the whole stylesheet
 * switches in one place (see src/styles/global.css).
 */

import { useCallback, useEffect, useState } from "react";

export type ContrastMode = "standard" | "high";

const STORAGE_KEY = "echonotes.contrast";

function systemWantsMoreContrast(): boolean {
  try {
    return (
      window.matchMedia("(prefers-contrast: more)").matches ||
      window.matchMedia("(forced-colors: active)").matches
    );
  } catch {
    return false;
  }
}

function storedMode(): ContrastMode | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === "high" || value === "standard" ? value : null;
  } catch {
    return null;
  }
}

export function useContrastMode(): [ContrastMode, (mode: ContrastMode) => void] {
  const [mode, setMode] = useState<ContrastMode>(
    () => storedMode() ?? (systemWantsMoreContrast() ? "high" : "standard"),
  );

  useEffect(() => {
    document.documentElement.dataset.contrast = mode;
  }, [mode]);

  const choose = useCallback((next: ContrastMode) => {
    setMode(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage blocked: the choice lasts until the page is reloaded.
    }
  }, []);

  return [mode, choose];
}
