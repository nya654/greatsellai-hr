import { lazy } from "react";
import type { ReactNode } from "react";

const SemiTag = lazy(() => import("@douyinfe/semi-ui-19/lib/es/tag"));

/**
 * Maps the workspace status classes (is-success / is-error / is-warning /
 * is-progress) to Semi Tag tones. An empty or unknown class renders neutral.
 */
function statusPillTone(className: string): "green" | "red" | "orange" | "blue" | "grey" {
  switch (className.trim()) {
    case "is-success": return "green";
    case "is-error": return "red";
    case "is-warning": return "orange";
    case "is-progress": return "blue";
    default: return "grey";
  }
}

/** Status-pill logic stays in the model status classes; it renders as a Semi Tag. */
export function StatusPillTag({ className, children }: { className: string; children: ReactNode }) {
  return <SemiTag color={statusPillTone(className)} size="small">{children}</SemiTag>;
}
