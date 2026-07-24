import { useState, type ReactNode } from "react";
import { BackofficeButton } from "../../backoffice/ui/BackofficeButton";
import { BackofficeSelect } from "../../backoffice/ui/BackofficeSelect";
import { TableSkeleton } from "../../backoffice/ui/TableSkeleton";
import { Icon } from "../../icons";
import {
  clampMonths,
  degreeLabels,
  experienceTypeOptions,
  formatDuration,
  formatMinimumDuration,
  institutionClassificationLabel,
  institutionClassificationLabels,
  resolvedInstitutionClassificationOptions,
  sortInstitutionClassifications,
  type FilterDraft,
  type MatchMode,
} from "./filter-model";
import type {
  CandidateSearchDisplayFieldKey,
  CandidateSearchItem,
  CandidateSearchResponse,
  DegreeLevel,
  FilterOptions,
  InstitutionClassification,
  PresenceStatus,
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

function FilterPanel({
  draft,
  filterOptions,
  onDraftChange,
  savedFilters,
  onReset,
  onSave,
  onApplySaved,
  onDeleteSaved,
}: {
  draft: FilterDraft;
  filterOptions: FilterOptions;
  onDraftChange: (draft: FilterDraft, timing?: "immediate" | "debounced") => void;
  savedFilters: SavedFilter[];
  onReset: () => void;
  onSave: (name: string) => Promise<void>;
  onApplySaved: (filter: SavedFilter) => boolean;
  onDeleteSaved: (filter: SavedFilter) => Promise<void>;
}) {
  const [selectedSavedId, setSelectedSavedId] = useState("");
  const [saveName, setSaveName] = useState("");
  const [saving, setSaving] = useState(false);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const institutionClassifications = resolvedInstitutionClassificationOptions(filterOptions);

  const update = (patch: Partial<FilterDraft>) =>
    onDraftChange({ ...draft, ...patch });
  const updateAfterTyping = (patch: Partial<FilterDraft>) =>
    onDraftChange({ ...draft, ...patch }, "debounced");
  const applySaved = (id: string) => {
    setSelectedSavedId(id);
    const saved = savedFilters.find((item) => item.saved_filter_id === id);
    if (saved && !onApplySaved(saved)) setSelectedSavedId("");
  };

  const save = async () => {
    setSaving(true);
    try {
      await onSave(saveName);
      setSaveName("");
    } finally {
      setSaving(false);
    }
  };

  return (
    <aside
      aria-label="筛选条件"
      className={`filter-panel${mobileFiltersOpen ? " is-mobile-open" : ""}`}
    >
      <div className="filter-panel-header">
        <h2 className="filter-panel-title">筛选条件</h2>
        <div className="filter-panel-header-actions">
          <button
            aria-controls="filter-controls"
            aria-expanded={mobileFiltersOpen}
            className="text-button filter-mobile-toggle"
            onClick={() => setMobileFiltersOpen((current) => !current)}
            type="button"
          >
            <Icon name="filter" size={15} />
            {mobileFiltersOpen ? "收起筛选" : "展开筛选"}
          </button>
          <button
            className="text-button"
            onClick={() => void onReset()}
            type="button"
          >
            清空
          </button>
        </div>
      </div>
      <div className="filter-scroll" id="filter-controls">
        <section className="filter-section">
          <div className="filter-section-heading">
            <h3>已保存的筛选</h3>
            <span>{savedFilters.length} 组</span>
          </div>
          <div className="saved-filter-row">
            <div className="select-wrap" style={{ flex: 1 }}>
              <label className="sr-only" htmlFor="saved-filter">
                选择已保存的筛选
              </label>
              <select
                className="select-field"
                id="saved-filter"
                onChange={(event) => applySaved(event.target.value)}
                value={selectedSavedId}
              >
                <option value="">选择一组筛选</option>
                {savedFilters.map((item) => (
                  <option
                    key={item.saved_filter_id}
                    value={item.saved_filter_id}
                  >
                    {item.name}
                  </option>
                ))}
              </select>
              <Icon name="chevron-down" size={16} />
            </div>
            {selectedSavedId && (
              <button
                aria-label="删除当前保存的筛选"
                className="icon-button"
                onClick={() => {
                  const item = savedFilters.find(
                    (filter) => filter.saved_filter_id === selectedSavedId,
                  );
                  if (!item) return;
                  void onDeleteSaved(item).then(() => setSelectedSavedId(""));
                }}
                type="button"
              >
                <Icon name="close" size={16} />
              </button>
            )}
          </div>
          <div className="saved-filter-row">
            <label className="sr-only" htmlFor="save-filter-name">
              筛选名称
            </label>
            <input
              className="field"
              id="save-filter-name"
              maxLength={120}
              onChange={(event) => setSaveName(event.target.value)}
              placeholder="为当前条件命名"
              value={saveName}
            />
            <button
              className="button"
              disabled={saving}
              onClick={() => void save()}
              type="button"
            >
              保存
            </button>
          </div>
        </section>

        <section className="filter-section">
          <div className="filter-section-heading">
            <h3>学历与院校</h3>
            <span>任一满足</span>
          </div>
          <div className="field-stack">
            <span className="field-label">院校类型</span>
            <div className="choice-grid" aria-label="院校类型条件">
              {institutionClassifications.map((option) => (
                <label className="choice-row" key={option.value}>
                  <input
                    checked={draft.institutionClassifications.includes(option.value)}
                    onChange={() =>
                      update({
                        institutionClassifications: sortInstitutionClassifications(
                          draft.institutionClassifications.includes(option.value)
                            ? draft.institutionClassifications.filter(
                                (value) => value !== option.value,
                              )
                            : [
                                ...draft.institutionClassifications,
                                option.value,
                              ],
                        ),
                      })
                    }
                    type="checkbox"
                  />
                  {option.label}
                </label>
              ))}
            </div>
            <span className="field-hint">已选院校类型满足任一即可。</span>
          </div>
          <span className="field-label">最高学历</span>
          <div className="choice-grid" aria-label="学历条件">
            {filterOptions.degrees.map((option) => (
              <label className="choice-row" key={option.value}>
                <input
                  checked={draft.degrees.includes(option.value)}
                  onChange={() =>
                    update({
                      degrees: draft.degrees.includes(option.value)
                        ? draft.degrees.filter(
                            (degree) => degree !== option.value,
                          )
                        : [...draft.degrees, option.value],
                    })
                  }
                  type="checkbox"
                />
                {option.label}
              </label>
            ))}
          </div>
          <span className="field-hint">已选最高学历满足任一即可。</span>
          <div className="field-stack">
            <span className="field-label">应届状态</span>
            <div className="choice-grid choice-grid-inline" role="radiogroup">
              {filterOptions.graduation_statuses.map((option) => (
                <label className="choice-row" key={option.value}>
                  <input
                    checked={draft.graduationStatus === option.value}
                    name="graduation-status"
                    onChange={() => update({ graduationStatus: option.value })}
                    type="radio"
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </div>
          {draft.graduationStatus !== "any" && (
            <div className="filter-inline-fields">
              <label className="field-stack">
                <span className="field-label">应届窗口开始</span>
                <input
                  className="field"
                  onChange={(event) => updateAfterTyping({ freshGraduateStartMonth: event.target.value })}
                  type="month"
                  value={draft.freshGraduateStartMonth}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">应届窗口结束</span>
                <input
                  className="field"
                  onChange={(event) => updateAfterTyping({ freshGraduateEndMonth: event.target.value })}
                  type="month"
                  value={draft.freshGraduateEndMonth}
                />
              </label>
            </div>
          )}
          <div className="field-stack">
            <label className="field-label" htmlFor="school-name">
              院校名称
            </label>
            <input
              className="field"
              id="school-name"
              onChange={(event) => updateAfterTyping({ schoolName: event.target.value })}
              placeholder="可填全称或简称，例如：北大"
              value={draft.schoolName}
            />
          </div>
          <details className="advanced-filter">
            <summary>成绩、绩点与排名（非必选）</summary>
            <div className="filter-inline-fields">
              <label className="field-stack">
                <span className="field-label">最低平均成绩</span>
                <input
                  className="field"
                  max="100"
                  min="0"
                  onChange={(event) => updateAfterTyping({ minAverageScore: event.target.value })}
                  placeholder="例如：85"
                  type="number"
                  value={draft.minAverageScore}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">最低绩点百分比</span>
                <input
                  className="field"
                  max="100"
                  min="0"
                  onChange={(event) => updateAfterTyping({ minGpaPercent: event.target.value })}
                  placeholder="例如：85"
                  type="number"
                  value={draft.minGpaPercent}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">专业名次不低于</span>
                <input
                  className="field"
                  min="1"
                  onChange={(event) => updateAfterTyping({ maxRankPosition: event.target.value })}
                  placeholder="例如：10（前 10 名）"
                  type="number"
                  value={draft.maxRankPosition}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">排名前百分比</span>
                <input
                  className="field"
                  max="100"
                  min="1"
                  onChange={(event) => updateAfterTyping({ maxRankPercent: event.target.value })}
                  placeholder="例如：10"
                  type="number"
                  value={draft.maxRankPercent}
                />
              </label>
            </div>
            <span className="field-hint">
              只匹配简历中有明确成绩、绩点或排名证据的同一条教育经历。
            </span>
          </details>
          <div className="field-stack">
            <label className="field-label" htmlFor="major-name">
              专业方向
            </label>
            <input
              className="field"
              id="major-name"
              onChange={(event) => updateAfterTyping({ major: event.target.value })}
              placeholder="例如：计算机科学"
              value={draft.major}
            />
          </div>
        </section>

        <section className="filter-section">
          <div className="filter-section-heading">
            <h3>经历类别</h3>
            <span>按同一条经历匹配</span>
          </div>
          <div className="field-stack">
            <label className="field-label" htmlFor="min-experience">
              最低正式工作年限
            </label>
            <input
              className="range-input"
              id="min-experience"
              max="240"
              min="0"
              onChange={(event) =>
                updateAfterTyping({
                  minEmploymentMonths: clampMonths(Number(event.target.value)),
                })
              }
              step="12"
              type="range"
              value={draft.minEmploymentMonths}
            />
            <div className="range-values">
              <span>{formatMinimumDuration(draft.minEmploymentMonths)}</span>
              <span>20 年</span>
            </div>
          </div>
          <div className="field-stack">
            <label className="field-label" htmlFor="min-work-internship">
              最低工作 + 实习年限
            </label>
            <input
              className="range-input"
              id="min-work-internship"
              max="240"
              min="0"
              onChange={(event) =>
                updateAfterTyping({
                  minEmploymentOrInternshipMonths: clampMonths(
                    Number(event.target.value),
                  ),
                })
              }
              step="12"
              type="range"
              value={draft.minEmploymentOrInternshipMonths}
            />
            <div className="range-values">
              <span>{formatMinimumDuration(draft.minEmploymentOrInternshipMonths)}</span>
              <span>20 年</span>
            </div>
          </div>
          <div className="field-stack">
            <span className="field-label">经历类型</span>
            <div className="choice-grid" aria-label="经历类型条件">
              {filterOptions.experience_types.map((option) => (
                <label className="choice-row" key={option.value}>
                  <input
                    checked={draft.experienceTypes.includes(option.value)}
                    onChange={() =>
                      update({
                        experienceTypes: draft.experienceTypes.includes(
                          option.value,
                        )
                          ? draft.experienceTypes.filter(
                              (value) => value !== option.value,
                            )
                          : [...draft.experienceTypes, option.value],
                      })
                    }
                    type="checkbox"
                  />
                  {option.label}
                </label>
              ))}
            </div>
            <span className="field-hint">不选则不限经历类型。</span>
          </div>
          <div className="field-stack">
            <label className="field-label" htmlFor="experience-name">
              项目 / 竞赛 / 经历名称
            </label>
            <input
              className="field"
              id="experience-name"
              onChange={(event) => updateAfterTyping({ experienceName: event.target.value })}
              placeholder="例如：全国大学生数学建模竞赛"
              value={draft.experienceName}
            />
          </div>
          <div className="field-stack">
            <label className="field-label" htmlFor="company-name">
              公司 / 组织
            </label>
            <input
              className="field"
              id="company-name"
              onChange={(event) => updateAfterTyping({ company: event.target.value })}
              placeholder="例如：字节跳动"
              value={draft.company}
            />
          </div>
          <div className="field-stack">
            <label className="field-label" htmlFor="role-name">
              职位名称
            </label>
            <input
              className="field"
              id="role-name"
              onChange={(event) => updateAfterTyping({ title: event.target.value })}
              placeholder="例如：后端工程师"
              value={draft.title}
            />
          </div>
          <details className="advanced-filter">
            <summary>经历获奖情况（非必选）</summary>
            <div className="choice-grid">
              {filterOptions.award_levels.map((option) => (
                <label className="choice-row" key={option.value}>
                  <input
                    checked={draft.experienceAwardLevels.includes(option.value)}
                    onChange={() =>
                      update({
                        experienceAwardLevels: draft.experienceAwardLevels.includes(option.value)
                          ? draft.experienceAwardLevels.filter((value) => value !== option.value)
                          : [...draft.experienceAwardLevels, option.value],
                      })
                    }
                    type="checkbox"
                  />
                  {option.label}
                </label>
              ))}
            </div>
            <input
              className="field"
              onChange={(event) => updateAfterTyping({ experienceAwardResult: event.target.value })}
              placeholder="获奖结果，例如：一等奖"
              value={draft.experienceAwardResult}
            />
          </details>
        </section>

        <section className="filter-section">
          <div className="filter-section-heading">
            <h3>技能</h3>
            <span>支持全部或任一</span>
          </div>
          <div className="field-stack">
            <span className="field-label">技能匹配方式</span>
            <div className="choice-grid choice-grid-inline" role="radiogroup">
              {(
                [
                  ["all", "全部具备"],
                  ["any", "任一具备"],
                ] as Array<[MatchMode, string]>
              ).map(([value, label]) => (
                <label className="choice-row" key={value}>
                  <input
                    checked={draft.skillsMode === value}
                    name="skills-match-mode"
                    onChange={() => update({ skillsMode: value })}
                    type="radio"
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>
          <span className="field-label">技能分类（非必选）</span>
          <div className="choice-grid">
            {filterOptions.skill_categories.map((option) => (
              <label className="choice-row" key={option.value}>
                <input
                  checked={draft.skillCategories.includes(option.value)}
                  onChange={() =>
                    update({
                      skillCategories: draft.skillCategories.includes(option.value)
                        ? draft.skillCategories.filter((value) => value !== option.value)
                        : [...draft.skillCategories, option.value],
                    })
                  }
                  type="checkbox"
                />
                {option.label}
              </label>
            ))}
          </div>
          <ChipInput
            label="核心技能"
            onChange={(skills) => update({ skills })}
            placeholder="输入技能后按 Enter"
            values={draft.skills}
          />
        </section>

        <section className="filter-section">
          <div className="filter-section-heading">
            <h3>英语能力</h3>
            <span>证书之间按 OR</span>
          </div>
          <div className="credential-list">
            {filterOptions.language_credentials.map((option) => {
              const selected = draft.languageCredentials.includes(option.value);
              return (
                <div className="credential-row" key={option.value}>
                  <label className="choice-row">
                    <input
                      checked={selected}
                      onChange={() =>
                        update({
                          languageCredentials: selected
                            ? draft.languageCredentials.filter((value) => value !== option.value)
                            : [...draft.languageCredentials, option.value],
                        })
                      }
                      type="checkbox"
                    />
                    {option.label}
                  </label>
                  {selected && option.value !== "custom" && (
                    <input
                      aria-label={`${option.label}最低分`}
                      className="field score-field"
                      min="0"
                      onChange={(event) =>
                        updateAfterTyping({
                          languageScores: {
                            ...draft.languageScores,
                            [option.value]: event.target.value,
                          },
                        })
                      }
                      placeholder="最低分（可选）"
                      type="number"
                      value={draft.languageScores[option.value] ?? ""}
                    />
                  )}
                </div>
              );
            })}
          </div>
          {draft.languageCredentials.includes("custom") && (
            <input
              className="field"
              onChange={(event) => updateAfterTyping({ customLanguageName: event.target.value })}
              placeholder="填写英语证书名称"
              value={draft.customLanguageName}
            />
          )}
          <span className="field-hint">
            “四级、英语四级、CET4、CET-4”等写法均匹配大学英语四级（CET-4）。
          </span>
        </section>

        <section className="filter-section">
          <div className="filter-section-heading">
            <h3>奖学金与竞赛</h3>
            <span>均为非必选</span>
          </div>
          <PresenceRadio
            label="奖学金"
            name="scholarship-status"
            options={filterOptions.presence_statuses}
            value={draft.scholarshipStatus}
            onChange={(scholarshipStatus) => update({ scholarshipStatus })}
          />
          {draft.scholarshipStatus === "present" && (
            <div className="field-stack">
              <div className="choice-grid">
                {filterOptions.scholarship_levels.map((option) => (
                  <label className="choice-row" key={option.value}>
                    <input
                      checked={draft.scholarshipLevels.includes(option.value)}
                      onChange={() =>
                        update({
                          scholarshipLevels: draft.scholarshipLevels.includes(option.value)
                            ? draft.scholarshipLevels.filter((value) => value !== option.value)
                            : [...draft.scholarshipLevels, option.value],
                        })
                      }
                      type="checkbox"
                    />
                    {option.label}
                  </label>
                ))}
              </div>
              <input
                className="field"
                onChange={(event) => updateAfterTyping({ scholarshipName: event.target.value })}
                placeholder="奖学金名称（可选）"
                value={draft.scholarshipName}
              />
            </div>
          )}
          <PresenceRadio
            label="技能竞赛参赛记录"
            name="competition-status"
            options={filterOptions.presence_statuses}
            value={draft.competitionStatus}
            onChange={(competitionStatus) => update({ competitionStatus })}
          />
          <PresenceRadio
            label="技能竞赛获奖记录"
            name="competition-award-status"
            options={filterOptions.presence_statuses}
            value={draft.competitionAwardStatus}
            onChange={(competitionAwardStatus) => update({ competitionAwardStatus })}
          />
        </section>

        <section className="filter-section">
          <div className="filter-section-heading">
            <h3>管理与领导经历</h3>
            <span>非必选</span>
          </div>
          <div className="choice-grid">
            {filterOptions.leadership_contexts.map((option) => (
              <label className="choice-row" key={option.value}>
                <input
                  checked={draft.leadershipContexts.includes(option.value)}
                  onChange={() =>
                    update({
                      leadershipContexts: draft.leadershipContexts.includes(option.value)
                        ? draft.leadershipContexts.filter((item) => item !== option.value)
                        : [...draft.leadershipContexts, option.value],
                    })
                  }
                  type="checkbox"
                />
                {option.label}
              </label>
            ))}
          </div>
          <ChipInput
            label="角色名称"
            onChange={(leadershipRoles) => update({ leadershipRoles })}
            placeholder="例如：班干部、组长、主管、经理"
            values={draft.leadershipRoles}
          />
        </section>

        <section className="filter-section">
          <div className="filter-section-heading">
            <h3>自定义关键词</h3>
            <span>泛匹配或精准匹配</span>
          </div>
          <div className="field-stack">
            <span className="field-label">关键词匹配方式</span>
            <div className="choice-grid choice-grid-inline" role="radiogroup">
              {filterOptions.keyword_modes.map((option) => (
                <label className="choice-row" key={option.value}>
                  <input
                    checked={draft.keywordsMode === option.value}
                    name="keywords-match-mode"
                    onChange={() => update({ keywordsMode: option.value })}
                    type="radio"
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </div>
          <ChipInput
            label="补充关键词"
            onChange={(keywords) => update({ keywords })}
            placeholder="输入关键词后按 Enter"
            values={draft.keywords}
          />
        </section>

      </div>
    </aside>
  );
}

function PresenceRadio({
  label,
  name,
  options,
  value,
  onChange,
}: {
  label: string;
  name: string;
  options: FilterOptions["presence_statuses"];
  value: PresenceStatus;
  onChange: (value: PresenceStatus) => void;
}) {
  return (
    <div className="field-stack">
      <span className="field-label">{label}</span>
      <div className="choice-grid choice-grid-inline" role="radiogroup">
        {options.map((option) => (
          <label className="choice-row" key={option.value}>
            <input
              checked={value === option.value}
              name={name}
              onChange={() => onChange(option.value)}
              type="radio"
            />
            {option.label}
          </label>
        ))}
      </div>
    </div>
  );
}

function ChipInput({
  label,
  values,
  onChange,
  placeholder,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder: string;
}) {
  const [value, setValue] = useState("");
  const add = () => {
    const normalized = value.trim();
    if (
      !normalized ||
      values.some(
        (item) => item.toLocaleLowerCase() === normalized.toLocaleLowerCase(),
      )
    )
      return;
    onChange([...values, normalized]);
    setValue("");
  };
  return (
    <div className="field-stack">
      <label className="field-label">{label}</label>
      <div className="chip-input">
        {values.map((item) => (
          <span className="filter-chip" key={item}>
            {item}
            <button
              aria-label={`移除 ${item}`}
              onClick={() =>
                onChange(values.filter((valueItem) => valueItem !== item))
              }
              type="button"
            >
              <Icon name="close" size={12} />
            </button>
          </span>
        ))}
        <input
          onBlur={add}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" ||
              event.key === "," ||
              event.key === "，"
            ) {
              event.preventDefault();
              add();
            }
          }}
          placeholder={values.length ? "继续添加" : placeholder}
          value={value}
        />
      </div>
    </div>
  );
}

function InstitutionClassificationTags({
  classifications,
}: {
  classifications: readonly InstitutionClassification[] | null | undefined;
}) {
  const orderedClassifications = sortInstitutionClassifications(classifications);
  if (!orderedClassifications.length) {
    return <span className="candidate-meta">待核实</span>;
  }
  return (
    <div className="institution-classification-tags">
      {orderedClassifications.map((classification) => (
        <span className="tag" key={classification}>
          {institutionClassificationLabel(classification)}
        </span>
      ))}
    </div>
  );
}

interface ResultDisplayColumn {
  key: CandidateSearchDisplayFieldKey;
  label: string;
}

function activeResultDisplayColumns(draft: FilterDraft): ResultDisplayColumn[] {
  const columns: ResultDisplayColumn[] = [];
  const add = (key: CandidateSearchDisplayFieldKey, label: string) => {
    if (!columns.some((column) => column.key === key)) {
      columns.push({ key, label });
    }
  };

  if (draft.graduationStatus !== "any") add("graduation", "毕业时间");
  if (draft.minEmploymentMonths > 0) {
    add("employment_months", "正式工作年限");
  }
  if (draft.minEmploymentOrInternshipMonths > 0) {
    add("employment_or_internship_months", "工作 + 实习年限");
  }

  if (draft.schoolName.trim()) add("school", "学校");
  if (draft.major.trim()) add("major", "专业");
  if (
    draft.minAverageScore ||
    draft.minGpaPercent ||
    draft.maxRankPosition ||
    draft.maxRankPercent
  ) {
    add("academic_performance", "学业表现");
  }

  if (draft.experienceTypes.length) add("experience_type", "经历类型");
  if (draft.experienceName.trim()) add("experience_name", "经历名称");
  if (draft.company.trim()) add("organization", "公司 / 组织");
  if (draft.title.trim()) add("title", "职位");
  if (
    draft.experienceAwardLevels.length ||
    draft.experienceAwardResult.trim()
  ) {
    add("experience_award", "经历获奖");
  }

  if (draft.skills.length || draft.skillCategories.length) add("skills", "技能");
  if (
    draft.languageCredentials.some(
      (credential) =>
        credential !== "custom" || Boolean(draft.customLanguageName.trim()),
    )
  ) {
    add("language", "语言证书");
  }
  if (
    draft.scholarshipStatus !== "any" ||
    draft.scholarshipName.trim() ||
    draft.scholarshipLevels.length
  ) {
    add("scholarship", "奖学金");
  }
  if (
    draft.competitionStatus !== "any" ||
    draft.competitionAwardStatus !== "any"
  ) {
    add("competition", "竞赛");
  }
  if (draft.leadershipContexts.length || draft.leadershipRoles.length) {
    add("leadership", "领导经历");
  }
  if (draft.keywords.length) add("keywords", "关键词命中");

  return columns;
}

function resultDisplayValueLabel(
  key: CandidateSearchDisplayFieldKey,
  value: string,
): string {
  const normalized = value.trim();
  if (!normalized) return "";

  if (key === "institution_classifications") {
    return (
      institutionClassificationLabels[
        normalized as InstitutionClassification
      ] ?? normalized
    );
  }
  if (key === "highest_degree" || key === "education_degree") {
    return degreeLabels[normalized as DegreeLevel] ?? normalized;
  }
  if (key === "experience_type") {
    return (
      experienceTypeOptions.find((option) => option.value === normalized)
        ?.label ?? normalized
    );
  }
  if (
    key === "employment_months" ||
    key === "employment_or_internship_months"
  ) {
    const months = Number(normalized);
    return Number.isFinite(months) ? formatDuration(months) : normalized;
  }
  return normalized;
}

function resultDisplayValues(
  item: CandidateSearchItem,
  key: CandidateSearchDisplayFieldKey,
): string[] {
  const values = (item.display_fields ?? [])
    .filter((field) => field.key === key)
    .flatMap((field) => field.values)
    .map((value) => resultDisplayValueLabel(key, value))
    .filter(Boolean);
  return [...new Set(values)];
}

function ResultDisplayValues({
  item,
  fieldKey,
  label,
}: {
  item: CandidateSearchItem;
  fieldKey: CandidateSearchDisplayFieldKey;
  label?: string;
}) {
  const values = resultDisplayValues(item, fieldKey);
  if (!values.length) {
    return <span className="candidate-meta result-display-empty">—</span>;
  }

  return (
    <div
      aria-label={`${label ?? "筛选字段"}：${values.join("；")}`}
      className="result-display-values"
      title={values.join("；")}
    >
      {values.slice(0, 2).map((value) => (
        <span className="result-display-value" key={value}>
          {value}
        </span>
      ))}
      {values.length > 2 && (
        <span className="result-display-more">+{values.length - 2} 项</span>
      )}
    </div>
  );
}

function ResultColumnHeader({
  children,
  active = false,
}: {
  children: ReactNode;
  active?: boolean;
}) {
  return (
    <span className="result-column-heading">
      {children}
      {active && <span className="result-filter-indicator">已筛</span>}
    </span>
  );
}

function scoreConfidencePresentation(value: number | null): {
  label: string;
  tone: "grounded" | "partial" | "unknown";
} {
  if (value === null) {
    return { label: "依据待核实", tone: "unknown" };
  }
  if (value >= 80) {
    return { label: `可信度高 · ${value.toFixed(0)}%`, tone: "grounded" };
  }
  if (value >= 50) {
    return { label: `可信度中 · ${value.toFixed(0)}%`, tone: "partial" };
  }
  return { label: `待核实 · ${value.toFixed(0)}%`, tone: "unknown" };
}

function scoreStatusLabel(status: string | null): string | null {
  if (status === "overridden") return "含人工调整";
  if (status === "needs_review") return "建议复核";
  if (status === "succeeded") return null;
  return status ? "评分待更新" : null;
}

function CandidateEducationCell({ item }: { item: CandidateSearchItem }) {
  const hasEducation = Boolean(
    item.highest_degree ||
      item.education_school ||
      item.education_major ||
      item.institution_classifications.length,
  );
  if (!hasEducation) return <span className="candidate-meta">未识别</span>;
  return (
    <div className="candidate-profile-cell candidate-education-cell">
      <div className="candidate-profile-primary">
        {item.highest_degree && (
          <span className="degree-label">{degreeLabels[item.highest_degree]}</span>
        )}
        <span className="candidate-profile-title">
          {item.education_school || "学校信息待补充"}
        </span>
      </div>
      {item.education_major && (
        <span className="candidate-meta">{item.education_major}</span>
      )}
      <InstitutionClassificationTags
        classifications={item.institution_classifications}
      />
    </div>
  );
}

function CandidateExperienceCell({ item }: { item: CandidateSearchItem }) {
  const experienceType = experienceTypeOptions.find(
    (option) => option.value === item.latest_experience_type,
  )?.label;
  const role = [
    item.latest_experience_title,
    item.latest_experience_organization,
  ]
    .filter(Boolean)
    .join(" · ");
  const hasVerifiedEmployment = item.employment_months > 0;
  const hasAdditionalInternshipTenure =
    item.employment_or_internship_months > item.employment_months;
  return (
    <div className="candidate-profile-cell">
      <div className="candidate-profile-primary">
        <span
          aria-label={
            hasVerifiedEmployment
              ? `正式工作 ${formatDuration(item.employment_months)}`
              : "正式工作年限待核实"
          }
          className="candidate-profile-title"
          title="正式工作年限仅累计有明确工作类型、公司、职位和起止日期的工作经历；实习单独计入“工作 + 实习”。"
        >
          {hasVerifiedEmployment
            ? `${formatDuration(item.employment_months)} 正式工作`
            : "正式工作年限待核实"}
        </span>
      </div>
      {hasAdditionalInternshipTenure && (
        <span className="candidate-meta">
          工作 + 实习 {formatDuration(item.employment_or_internship_months)}
        </span>
      )}
      {role ? (
        <span className="candidate-meta">
          {experienceType ? `${experienceType} · ` : ""}
          {role}
        </span>
      ) : (
        <span className="candidate-meta">最近岗位信息待补充</span>
      )}
    </div>
  );
}

function CandidateSkillHighlights({ item }: { item: CandidateSearchItem }) {
  const skills = item.skill_highlights ?? [];
  if (!skills.length) return <span className="candidate-meta">未识别</span>;
  return (
    <div
      aria-label={`核心技能：${skills.join("；")}`}
      className="candidate-skill-highlights"
      title={skills.join("；")}
    >
      {skills.slice(0, 3).map((skill) => (
        <span className="tag" key={skill}>{skill}</span>
      ))}
      {skills.length > 3 && <span className="candidate-skills-more">+{skills.length - 3}</span>}
    </div>
  );
}

function ResultsPane({
  appliedDraft,
  search,
  searching,
  selectedResumeId,
  onOpenCandidate,
  onScoreTemplateChange,
  onLoadMore,
  onUpload,
  scoreTemplateId,
  scoreTemplates,
}: {
  appliedDraft: FilterDraft;
  search: CandidateSearchResponse;
  searching: boolean;
  selectedResumeId: string | null;
  onOpenCandidate: (item: CandidateSearchItem, tab?: "score") => void;
  onScoreTemplateChange: (templateId: string | null) => void;
  onLoadMore: () => void;
  onUpload: () => void;
  scoreTemplateId: string | null;
  scoreTemplates: ScoreTemplate[];
}) {
  const displayColumns = activeResultDisplayColumns(appliedDraft);
  const hasAppliedDisplayColumns = displayColumns.length > 0;
  const selectedScoreTemplate = scoreTemplates.find(
    (template) => template.template_id === scoreTemplateId,
  );
  const scoreOrderLabel = selectedScoreTemplate
    ? `按“${selectedScoreTemplate.name} · v${selectedScoreTemplate.version}”综合评分排序`
    : "未选择统一评分模板，按最近更新排序";

  return (
    <section className="results-pane" aria-label="候选人结果">
      <header className="results-header">
        <div className="results-summary">
          <h1>候选人结果</h1>
          <p>
            {search.items.length
              ? `当前已加载 ${search.items.length} 位候选人，${scoreOrderLabel}`
              : "仅显示已完成 AI 提取并启用的简历"}
          </p>
        </div>
        <div className="results-toolbar">
          <div className="score-sort-control">
            <span id="score-sort-label">评分口径</span>
            <BackofficeSelect
              ariaLabel="综合评分排序规则"
              ariaLabelledBy="score-sort-label"
              className="score-sort-select"
              onChange={(templateId) => onScoreTemplateChange(templateId || null)}
              options={[
                { label: "不按评分排序", value: "" },
                ...scoreTemplates.map((template) => ({
                  label: `${template.name} · v${template.version}`,
                  value: template.template_id,
                })),
              ]}
              value={scoreTemplateId ?? ""}
            />
          </div>
          {search.needs_review_count > 0 && (
            <span className="status-pill">
              待处理 {search.needs_review_count}
            </span>
          )}
          <BackofficeButton
            icon={<Icon name="upload" size={16} />}
            onClick={onUpload}
          >
            上传简历
          </BackofficeButton>
        </div>
      </header>
      <div
        aria-label="候选人结果，可横向滚动查看筛选字段"
        className="table-scroll"
        role="region"
        tabIndex={0}
      >
        {searching && !search.items.length ? (
          <TableSkeleton />
        ) : search.items.length ? (
          <table
            className={`candidate-table${
              hasAppliedDisplayColumns ? " has-active-filter-columns" : ""
            }`}
          >
            <thead>
              <tr>
                <th scope="col">候选人</th>
                <th scope="col">学历 / 院校</th>
                <th scope="col">经历</th>
                <th scope="col">核心技能</th>
                {displayColumns.map((column) => (
                  <th className="result-display-column" key={column.key} scope="col">
                    <ResultColumnHeader active>{column.label}</ResultColumnHeader>
                  </th>
                ))}
                <th scope="col">综合评分</th>
                <th scope="col" aria-label="查看详情" />
              </tr>
            </thead>
            <tbody>
              {search.items.map((item) => (
                <tr
                  className={
                    selectedResumeId === item.resume_id ? "is-selected" : ""
                  }
                  key={item.resume_id}
                  onClick={() => onOpenCandidate(item)}
                >
                  <td className="candidate-result-cell">
                    <div className="candidate-person">
                      <span className="candidate-name">
                        {item.display_name?.trim() || "未命名候选人"}
                      </span>
                    </div>
                  </td>
                  <td>
                    <CandidateEducationCell item={item} />
                  </td>
                  <td>
                    <CandidateExperienceCell item={item} />
                  </td>
                  <td><CandidateSkillHighlights item={item} /></td>
                  {displayColumns.map((column) => (
                    <td className="result-display-cell" key={column.key}>
                      <ResultDisplayValues
                        fieldKey={column.key}
                        item={item}
                        label={column.label}
                      />
                    </td>
                  ))}
                  <td className="candidate-score-cell">
                    {item.score_total !== null ? (
                      <div className="candidate-score-summary">
                        <button
                          aria-label={`查看 ${item.display_name ?? "候选人"} 的评分详情`}
                          className="library-score candidate-score-link"
                          onClick={(event) => {
                            event.stopPropagation();
                            onOpenCandidate(item, "score");
                          }}
                          type="button"
                        >
                          <strong>{item.score_total.toFixed(1)}</strong>
                          <span>/ 100</span>
                          {item.score_template_name && (
                            <small>{item.score_template_name}</small>
                          )}
                        </button>
                        <span
                          className={`score-confidence is-${scoreConfidencePresentation(item.score_confidence).tone}`}
                        >
                          {scoreConfidencePresentation(item.score_confidence).label}
                        </span>
                        {scoreStatusLabel(item.score_status) && (
                          <span className="candidate-score-status">
                            {scoreStatusLabel(item.score_status)}
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="library-empty-copy">尚未评分</span>
                    )}
                  </td>
                  <td className="candidate-open-cell">
                    <button
                      aria-label={`查看 ${item.display_name?.trim() || "未命名候选人"} 的简历详情`}
                      className="candidate-open-action"
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpenCandidate(item);
                      }}
                      type="button"
                    >
                      查看 <Icon name="chevron-right" size={17} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty-state">
            <div className="empty-state-inner">
              <span className="empty-glyph">
                <Icon name="search" size={24} />
              </span>
              <h2>没有符合条件的已启用简历</h2>
              <p>
                调整筛选条件，或上传一份简历。AI
                提取完成后，它会自动进入筛选库。
              </p>
              <button
                className="button button-primary"
                onClick={onUpload}
                type="button"
              >
                <Icon name="upload" size={16} />
                上传简历
              </button>
            </div>
          </div>
        )}
      </div>
      <footer className="results-footer">
        <span>
          {searching ? (
            <span className="loading-line">
              <i className="spinner" />
              正在查询候选人…
            </span>
          ) : (
            `${search.items.length} 位候选人`
          )}
        </span>
        {search.next_cursor && (
          <button
            className="button button-ghost"
            disabled={searching}
            onClick={onLoadMore}
            type="button"
          >
            加载更多 <Icon name="arrow-right" size={16} />
          </button>
        )}
      </footer>
    </section>
  );
}
