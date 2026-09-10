/**
 * Recording and capture state - EchoNotes Feature 1.
 *
 * Wraps MediaRecorder: start on trigger press, stop on release, upload, then poll status while
 * the pipeline runs. Every stage transition is announced, and the earcons fire here rather than
 * in the component so a capture started by any trigger sounds the same.
 */

import type { CaptureResult, CaptureStage } from "@/types";

export interface UseCapture {
  stage: CaptureStage;
  progress: number;
  start: () => Promise<void>;
  stop: () => Promise<CaptureResult | null>;
  cancel: () => void;
}

export function useCapture(): UseCapture {
  throw new Error("not implemented");
}
