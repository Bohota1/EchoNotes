/** Capture endpoints - EchoNotes Feature 1. */

import type { CaptureResult } from "@/types";

export function uploadCapture(_audio: Blob, _language?: string): Promise<CaptureResult> {
  throw new Error("not implemented");
}

export function fetchCaptureStatus(_captureId: string): Promise<{ stage: string; progress: number; spoken: string }> {
  throw new Error("not implemented");
}

export function cancelCapture(_captureId: string): Promise<void> {
  throw new Error("not implemented");
}
