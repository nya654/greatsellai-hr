import { lazy, Suspense, useEffect, useState } from "react";
import { api } from "../../api";
import { BackofficeButton } from "../../backoffice/ui/BackofficeButton";
import { DISPLAY_FIELD_OPTIONS } from "../filter/display-field-options";
import type { CandidateSearchDisplayFieldKey } from "../../types";

const SemiCheckboxGroup = lazy(() => import("@douyinfe/semi-ui-19/lib/es/checkbox/checkboxGroup"));
const SemiCard = lazy(() => import("@douyinfe/semi-ui-19/lib/es/card"));
const SemiParagraph = lazy(() => import("@douyinfe/semi-ui-19/lib/es/typography/paragraph"));

export interface DisplayFieldsSettingsPanelProps {
  formatError: (error: unknown) => string;
  notify: (kind: "success" | "error", message: string) => void;
}

function asDisplayFieldKeys(values: unknown[]): CandidateSearchDisplayFieldKey[] {
  const allowed = new Set<string>(
    DISPLAY_FIELD_OPTIONS.map((option) => option.key),
  );
  return values.filter(
    (value): value is CandidateSearchDisplayFieldKey =>
      typeof value === "string" && allowed.has(value),
  );
}

/**
 * 筛选显示字段 personal-preference settings section. Lets a user pin which
 * candidate display fields the results table always shows; an empty selection
 * falls back to the auto-derived columns (see ResultsPane).
 */
export function DisplayFieldsSettingsPanel({
  formatError,
  notify,
}: DisplayFieldsSettingsPanelProps) {
  const [savedKeys, setSavedKeys] = useState<CandidateSearchDisplayFieldKey[] | null>(
    null,
  );
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getDisplayFieldPreferences()
      .then((preferences) => {
        if (!cancelled) setSavedKeys(asDisplayFieldKeys(preferences.display_field_keys));
      })
      .catch((error) => {
        if (!cancelled) notify("error", formatError(error));
      });
    return () => {
      cancelled = true;
    };
  }, [formatError, notify]);

  const save = async () => {
    if (!savedKeys) return;
    setSaving(true);
    try {
      const saved = await api.updateDisplayFieldPreferences(savedKeys);
      setSavedKeys(asDisplayFieldKeys(saved.display_field_keys));
      notify("success", "筛选显示字段已保存。");
    } catch (error) {
      notify("error", formatError(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Suspense fallback={<p>加载设置控件…</p>}>
      <SemiCard className="settings-panel" title="筛选显示字段">
        <SemiParagraph type="tertiary" style={{ margin: 0 }}>
          选择后，筛选结果表将固定显示这些字段；未选择时沿用自动推断。
        </SemiParagraph>

        {savedKeys === null ? (
          <p style={{ marginTop: 20 }}>加载显示字段偏好…</p>
        ) : (
          <SemiCheckboxGroup
            aria-label="筛选结果显示字段"
            direction="vertical"
            onChange={(values) => setSavedKeys(asDisplayFieldKeys(values))}
            options={DISPLAY_FIELD_OPTIONS.map((option) => ({
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
    </Suspense>
  );
}
