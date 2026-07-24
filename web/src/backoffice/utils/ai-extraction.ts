import type { AiExtractionStatus } from "../../types";

/** Shared polling cadence for workbench surfaces that show AI extraction state. */
export const AI_STATUS_POLL_INTERVAL_MS = 2_500;

export function aiExtractionIsInProgress(
  status: AiExtractionStatus | undefined,
): boolean {
  return status === "queued" || status === "running";
}
