import { lazy, Suspense, useEffect, useState } from "react";
import { api } from "../../api";
import { BackofficeButton } from "../../backoffice/ui/BackofficeButton";
import {
  DISPLAY_FIELD_OPTIONS,
  displayFieldLabel,
} from "../filter/display-field-options";
import type { CandidateSearchDisplayFieldKey } from "../../types";

const SemiCheckboxGroup = lazy(() => import("@douyinfe/semi-ui-19/lib/es/checkbox/checkboxGroup"));
const SemiCard = lazy(() => import("@douyinfe/semi-ui-19/lib/es/card"));
const SemiParagraph = lazy(() => import("@douyinfe/semi-ui-19/lib/es/typography/paragraph"));
const SemiTable = lazy(() => import("@douyinfe/semi-ui-19/lib/es/table"));
const SemiTitle = lazy(() => import("@douyinfe/semi-ui-19/lib/es/typography/title"));

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

/** Illustrative cell values so the settings preview reads like the real table. */
const PREVIEW_ROWS = [
  {
    key: "preview-1",
    candidate: "张三",
    education: "硕士 · 浙江大学",
    experience: "后端开发实习",
    skills: "Python、Go",
    score: "86",
  },
  {
    key: "preview-2",
    candidate: "李四",
    education: "本科 · 华南理工大学",
    experience: "产品助理实习",
    skills: "Java、SQL",
    score: "78",
  },
];

function previewSampleValue(key: CandidateSearchDisplayFieldKey): string {
  switch (key) {
    case "institution_classifications":
      return "双一流";
    case "highest_degree":
      return "硕士";
    case "education_degree":
      return "本科";
    case "graduation":
      return "2024-06";
    case "employment_months":
    case "employment_or_internship_months":
      return "3 年";
    case "gender":
      return "女";
    case "age":
      return "26 岁";
    case "school":
      return "浙江大学";
    case "major":
      return "软件工程";
    case "academic_performance":
      return "前 10%";
    case "experience_type":
      return "实习";
    case "experience_name":
      return "AI 平台研发";
    case "organization":
      return "字节跳动";
    case "title":
      return "后端工程师";
    case "experience_award":
      return "优秀实习生";
    case "skills":
      return "Python";
    case "language":
      return "英语 CET-6";
    case "scholarship":
      return "国家奖学金";
    case "competition":
      return "ACM 银奖";
    case "leadership":
      return "班长";
    case "keywords":
      return "大模型";
  }
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

  const previewColumns =
    savedKeys === null
      ? []
      : [
          { title: "候选人", dataIndex: "candidate", key: "candidate" },
          { title: "学历 / 院校", dataIndex: "education", key: "education" },
          { title: "经历", dataIndex: "experience", key: "experience" },
          { title: "核心技能", dataIndex: "skills", key: "skills" },
          ...savedKeys.map((key) => ({
            title: displayFieldLabel(key),
            dataIndex: key,
            key,
            render: () => previewSampleValue(key),
          })),
          { title: "综合评分", dataIndex: "score", key: "score" },
        ];

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

        {savedKeys !== null && (
          <div style={{ marginTop: 24 }}>
            <SemiTitle heading={6} style={{ margin: 0, marginBottom: 8 }}>
              结果表预览
            </SemiTitle>
            <SemiTable
              aria-label="筛选显示字段结果表预览"
              columns={previewColumns}
              dataSource={PREVIEW_ROWS}
              pagination={false}
              rowKey="key"
              scroll={{ x: 900 }}
              size="small"
            />
            {savedKeys.length === 0 && (
              <SemiParagraph type="tertiary" style={{ margin: 0, marginTop: 8 }}>
                未选择字段，结果表将沿用自动推断的列。
              </SemiParagraph>
            )}
          </div>
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
