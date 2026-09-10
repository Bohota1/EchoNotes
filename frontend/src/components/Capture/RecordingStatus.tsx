/**
 * Recording and pipeline status - EchoNotes Feature 1.
 *
 * Renders the current stage and, more importantly, announces each transition through the live
 * region: "Recording", "Transcribing", "Understanding", "Note added under Deadlock".
 *
 * A long capture must keep announcing progress. Silence during a thirty-second wait is
 * indistinguishable from a crash when you cannot see a spinner.
 */

import type { CaptureStage } from "@/types";

export interface RecordingStatusProps {
  stage: CaptureStage;
  progress: number;
}

export function RecordingStatus(_props: RecordingStatusProps) {
  throw new Error("not implemented");
}
