import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { api } from "../../api";
import { BackofficeButton } from "../../backoffice/ui/BackofficeButton";
import type { AiImportSettings, ScoreTemplate } from "../../types";

const SemiSwitch = lazy(() => import("@douyinfe/semi-ui-19/lib/es/switch"));
const SemiCheckbox = lazy(() => import("@douyinfe/semi-ui-19/lib/es/checkbox/checkbox"));
const SemiCard = lazy(() => import("@douyinfe/semi-ui-19/lib/es/card"));
const SemiParagraph = lazy(() => import("@douyinfe/semi-ui-19/lib/es/typography/paragraph"));
const SemiSelect = lazy(() => import("@douyinfe/semi-ui-19/lib/es/select"));
const SemiSpace = lazy(() => import("@douyinfe/semi-ui-19/lib/es/space"));

export interface AiImportSettingsPanelProps {
  formatError: (error: unknown) => string;
  notify: (kind: "success" | "error", message: string) => void;
}

function SettingRow({ label, control }: { label: string; control: ReactNode }) {
  return (
    <div className="settings-row">
      <span className="settings-row-label">{label}</span>
      {control}
    </div>
  );
}

/**
 * AI 导入处理 settings section. Consumes the settings-center AI-import
 * endpoints; auto-score requires a default scoring template before saving.
 */
export function AiImportSettingsPanel({ formatError, notify }: AiImportSettingsPanelProps) {
  const [settings, setSettings] = useState<AiImportSettings | null>(null);
  const [templates, setTemplates] = useState<ScoreTemplate[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [nextSettings, nextTemplates] = await Promise.all([
          api.getAiImportSettings(),
          api.listScoreTemplates(),
        ]);
        if (cancelled) return;
        setSettings(nextSettings);
        setTemplates(nextTemplates);
      } catch (error) {
        if (!cancelled) notify("error", formatError(error));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [formatError, notify]);

  const update = (patch: Partial<AiImportSettings>) => {
    setSettings((current) => (current ? { ...current, ...patch } : current));
  };

  const save = async () => {
    if (!settings) return;
    if (settings.auto_score_enabled && settings.score_template_ids.length === 0) {
      notify("error", "请至少选择一个评分模板。");
      return;
    }
    setSaving(true);
    try {
      const saved = await api.updateAiImportSettings(settings);
      setSettings(saved);
      notify("success", "AI 导入处理设置已保存。");
    } catch (error) {
      notify("error", formatError(error));
    } finally {
      setSaving(false);
    }
  };

  if (!settings) {
    return <p>加载 AI 导入处理设置…</p>;
  }

  const selectedTemplateIds = settings.score_template_ids ?? [];
  const templateOptions = templates.map((template) => ({
    label: template.name,
    value: template.template_id,
  }));
  // Keep selected templates that were since deleted visible as options so
  // they can be removed from the selection instead of showing a raw id.
  const optionValues = new Set(templateOptions.map((option) => option.value));
  const orphanOptions = selectedTemplateIds
    .filter((id) => !optionValues.has(id))
    .map((id) => ({ label: id, value: id }));
  const allOptions = [...templateOptions, ...orphanOptions];

  return (
    <Suspense fallback={<p>加载设置控件…</p>}>
      <SemiCard className="settings-panel" title="AI 导入处理">
        <SemiParagraph type="tertiary" style={{ margin: 0 }}>
          开启后，导入的简历将自动运行 AI 提取、总结与评分，会产生对应的模型调用费用。
        </SemiParagraph>

        <SemiSpace vertical spacing="medium" style={{ marginTop: 20, width: "100%" }}>
          <SettingRow
            label="自动生成 AI 总结"
            control={
              <SemiSwitch
                aria-label="自动生成 AI 总结"
                checked={settings.auto_summary_enabled}
                onChange={(checked) => update({ auto_summary_enabled: checked })}
              />
            }
          />
          <SettingRow
            label="自动评分"
            control={
              <SemiSwitch
                aria-label="自动评分"
                checked={settings.auto_score_enabled}
                onChange={(checked) => update({ auto_score_enabled: checked })}
              />
            }
          />
          <SettingRow
            label="评分模板"
            control={
              <SemiSelect
                aria-label="评分模板"
                className="settings-score-templates"
                disabled={!settings.auto_score_enabled}
                multiple
                onChange={(nextValue) =>
                  update({
                    score_template_ids: Array.isArray(nextValue)
                      ? nextValue.map(String)
                      : [],
                  })
                }
                optionList={allOptions}
                placeholder={settings.auto_score_enabled ? "选择评分模板（可多选）" : "请先开启自动评分"}
                value={selectedTemplateIds}
              />
            }
          />
          <div className="settings-row">
            <span className="settings-row-label">触发来源</span>
            <div className="settings-row-options">
              <SemiCheckbox
                checked={settings.trigger_manual_upload}
                onChange={(event) => update({ trigger_manual_upload: event.target.checked })}
              >
                手动上传
              </SemiCheckbox>
              <SemiCheckbox
                checked={settings.trigger_mailbox_import}
                onChange={(event) => update({ trigger_mailbox_import: event.target.checked })}
              >
                邮箱入库
              </SemiCheckbox>
            </div>
          </div>
        </SemiSpace>

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
