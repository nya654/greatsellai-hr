export type CandidateDrawerTab = "original" | "summary" | "score" | "evidence";

export interface SelectedResume {
  resumeId: string;
  candidateId: string;
  candidateName: string;
}
