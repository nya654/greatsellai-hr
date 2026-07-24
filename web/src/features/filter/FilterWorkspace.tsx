import { FilterPanel } from "./FilterPanel";
import { ResultsPane } from "./ResultsPane";
import type { FilterDraft } from "./filter-model";
import type {
  CandidateSearchItem,
  CandidateSearchResponse,
  FilterOptions,
  SavedFilter,
  ScoreTemplate,
} from "../../types";
import "./filter-workspace.css";

export function FilterWorkspace({
  appliedDraft,
  draft,
  filterOptions,
  onDraftChange,
  savedFilters,
  search,
  searching,
  selectedResumeId,
  onReset,
  onSave,
  onApplySaved,
  onDeleteSaved,
  onOpenCandidate,
  onScoreTemplateChange,
  onLoadMore,
  onUpload,
  scoreTemplateId,
  scoreTemplates,
}: {
  appliedDraft: FilterDraft;
  draft: FilterDraft;
  filterOptions: FilterOptions;
  onDraftChange: (draft: FilterDraft, timing?: "immediate" | "debounced") => void;
  savedFilters: SavedFilter[];
  search: CandidateSearchResponse;
  searching: boolean;
  selectedResumeId: string | null;
  onReset: () => void;
  onSave: (name: string) => Promise<void>;
  onApplySaved: (filter: SavedFilter) => boolean;
  onDeleteSaved: (filter: SavedFilter) => Promise<void>;
  onOpenCandidate: (item: CandidateSearchItem, tab?: "score") => void;
  onScoreTemplateChange: (templateId: string | null) => void;
  onLoadMore: () => void;
  onUpload: () => void;
  scoreTemplateId: string | null;
  scoreTemplates: ScoreTemplate[];
}) {
  return (
    <div className="filter-workspace">
      <FilterPanel
        draft={draft}
        filterOptions={filterOptions}
        onApplySaved={onApplySaved}
        onDeleteSaved={onDeleteSaved}
        onDraftChange={onDraftChange}
        onReset={onReset}
        onSave={onSave}
        savedFilters={savedFilters}
      />
      <ResultsPane
        appliedDraft={appliedDraft}
        onLoadMore={onLoadMore}
        onOpenCandidate={onOpenCandidate}
        onScoreTemplateChange={onScoreTemplateChange}
        onUpload={onUpload}
        search={search}
        searching={searching}
        selectedResumeId={selectedResumeId}
        scoreTemplateId={scoreTemplateId}
        scoreTemplates={scoreTemplates}
      />
    </div>
  );
}
