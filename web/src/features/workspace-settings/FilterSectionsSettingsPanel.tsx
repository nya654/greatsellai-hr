import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { BackofficeButton } from "../../backoffice/ui/BackofficeButton";
import {
  ALL_FILTER_SECTION_KEYS,
  FILTER_SECTION_OPTIONS,
} from "../filter/filter-section-options";
import { FilterPanel } from "../filter/FilterPanel";
import {
  fallbackFilterOptions,
  freshDefaultFilter,
} from "../filter/filter-search-model";
import type { FilterOptions, FilterSectionKey } from "../../types";
import "../filter/filter-workspace.css";

const SemiCard = lazy(() => import("@douyinfe/semi-ui-19/lib/es/card"));
const SemiCheckboxGroup = lazy(() => import("@douyinfe/semi-ui-19/lib/es/checkbox/checkboxGroup"));
const SemiCol = lazy(() => import("@douyinfe/semi-ui-19/lib/es/grid/col"));
const SemiParagraph = lazy(() => import("@douyinfe/semi-ui-19/lib/es/typography/paragraph"));
const SemiRow = lazy(() => import("@douyinfe/semi-ui-19/lib/es/grid/row"));
const SemiTitle = lazy(() => import("@douyinfe/semi-ui-19/lib/es/typography/title"));

export interface FilterSectionsSettingsPanelProps {
  formatError: (error: unknown) => string;
  notify: (kind: "success" | "error", message: string) => void;
}

function asFilterSectionKeys(values: unknown[]): FilterSectionKey[] {
  const allowed = new Set<string>(ALL_FILTER_SECTION_KEYS);
  return values.filter(
    (value): value is FilterSectionKey =>
      typeof value === "string" && allowed.has(value),
  );
}

/**
 * 初筛条件板块 personal-preference settings section. Lets a user treat the
 * left filter panel as pluggable blocks: every saved key keeps that section
 * visible in FilterPanel, and sections without a key disappear. An empty
 * selection hides the whole panel so the results table takes the full width.
 * The right column previews the change by rendering the real FilterPanel with
 * the current checkbox selection as a controlled preference.
 */
export function FilterSectionsSettingsPanel({
  formatError,
  notify,
}: FilterSectionsSettingsPanelProps) {
  const [savedKeys, setSavedKeys] = useState<FilterSectionKey[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [previewOptions, setPreviewOptions] = useState<FilterOptions>(
    fallbackFilterOptions,
  );
  const previewDraft = useMemo(() => freshDefaultFilter(), []);

  useEffect(() => {
    let cancelled = false;
    api
      .getFilterSectionPreferences()
      .then((preferences) => {
        if (!cancelled) setSavedKeys(asFilterSectionKeys(preferences.filter_section_keys));
      })
      .catch((error) => {
        if (!cancelled) notify("error", formatError(error));
      });
    return () => {
      cancelled = true;
    };
  }, [formatError, notify]);

  useEffect(() => {
    let cancelled = false;
    api
      .getFilterOptions()
      .then((options) => {
        if (!cancelled) setPreviewOptions({ ...fallbackFilterOptions, ...options });
      })
      .catch(() => {
        if (!cancelled) setPreviewOptions(fallbackFilterOptions);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async () => {
    if (!savedKeys) return;
    setSaving(true);
    try {
      const saved = await api.updateFilterSectionPreferences(savedKeys);
      setSavedKeys(asFilterSectionKeys(saved.filter_section_keys));
      notify("success", "初筛条件板块已保存。");
    } catch (error) {
      notify("error", formatError(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Suspense fallback={<p>加载设置控件…</p>}>
      <SemiRow gutter={24}>
        <SemiCol span={9}>
          <SemiCard className="settings-panel" title="初筛条件板块">
            <SemiParagraph type="tertiary" style={{ margin: 0 }}>
              初筛条件面板由可插拔的板块组成。选择贵司实际会用到的条件板块，
              未勾选的板块在筛选页隐藏——例如成绩 / GPA、排名这类招聘时往往
              拿不到的信息可以关掉；全不选则隐藏整个初筛条件面板。
            </SemiParagraph>

            {savedKeys === null ? (
              <p style={{ marginTop: 20 }}>加载初筛板块偏好…</p>
            ) : (
              <SemiCheckboxGroup
                aria-label="初筛条件板块"
                direction="vertical"
                onChange={(values) => setSavedKeys(asFilterSectionKeys(values))}
                options={FILTER_SECTION_OPTIONS.map((option) => ({
                  label: option.label,
                  value: option.key,
                }))}
                style={{ marginTop: 20 }}
                value={savedKeys}
              />
            )}

            <div className="settings-actions">
              <BackofficeButton
                loading={saving}
                onClick={() => void save()}
                tone="primary"
              >
                保存
              </BackofficeButton>
            </div>
          </SemiCard>
        </SemiCol>
        <SemiCol span={15}>
          <SemiTitle heading={6} style={{ margin: 0, marginBottom: 12 }}>
            筛选页初筛条件面板预览
          </SemiTitle>
          {savedKeys !== null && savedKeys.length === 0 ? (
            <SemiCard aria-label="初筛条件面板预览">
              <SemiParagraph type="tertiary" style={{ margin: 0 }}>
                未选择板块，筛选页将隐藏初筛条件面板，直接展示结果表格。
              </SemiParagraph>
            </SemiCard>
          ) : (
            <FilterPanel
              draft={previewDraft}
              filterOptions={previewOptions}
              onDraftChange={() => undefined}
              onReset={() => undefined}
              sectionPreferenceKeys={savedKeys}
            />
          )}
        </SemiCol>
      </SemiRow>
    </Suspense>
  );
}
