export type CandidateDrawerTab =
  | "original"
  | "summary"
  | "score"
  | "evidence"
  | "applications";

export interface SelectedResume {
  resumeId: string;
  candidateId: string;
  candidateName: string;
}
