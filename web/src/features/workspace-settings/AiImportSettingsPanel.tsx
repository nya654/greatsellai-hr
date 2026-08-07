import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { api } from "../../api";
import { BackofficeButton } from "../../backoffice/ui/BackofficeButton";
import { BackofficeSelect, type BackofficeSelectOption } from "../../backoffice/ui/BackofficeSelect";
import type { AiImportSettings, ScoreTemplate } from "../../types";

const SemiSwitch = lazy(() => import("@douyinfe/semi-ui-19/lib/es/switch"));
const SemiCheckbox = lazy(() => import("@douyinfe/semi-ui-19/lib/es/checkbox"));
const SemiTypography = lazy(() => import("@douyinfe/semi-ui-19/lib/es/typography"));
const SemiSpace = lazy(() => import("@douyinfe/semi-ui-19/lib/es/space"));

export interface AiImportSettingsPanelProps {
  formatError: (error: unknown) => string;
  notify: (kind: "success" | "error", message: string) => void;
}

function SettingRow({ label, control }: { label: string; control: ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 16,
        maxWidth: 480,
      }}
    >
      <span>{label}</span>
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
    if (settings.auto_score_enabled && !settings.default_score_template_id) {
      notify("error", "请先选择默认评分模板。");
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

  const templateOptions: BackofficeSelectOption[] = templates.map((template) => ({
    label: template.name,
    value: template.template_id,
  }));

  return (
    <Suspense fallback={<p>加载设置控件…</p>}>
      <div>
        <SemiTypography.Title heading={5}>AI 导入处理</SemiTypography.Title>
        <SemiTypography.Paragraph type="tertiary">
          开启后，导入的简历将自动运行 AI 提取、总结与评分，会产生对应的模型调用费用。
        </SemiTypography.Paragraph>

        <SemiSpace direction="vertical" spacing="medium" style={{ marginTop: 20 }}>
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
            label="默认评分模板"
            control={
              <BackofficeSelect
                ariaLabel="默认评分模板"
                disabled={!settings.auto_score_enabled}
                onChange={(templateId) => update({ default_score_template_id: templateId || null })}
                options={templateOptions}
                placeholder={settings.auto_score_enabled ? "选择默认评分模板" : "请先开启自动评分"}
                value={settings.default_score_template_id ?? ""}
              />
            }
          />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 16,
              maxWidth: 480,
            }}
          >
            <span>触发来源</span>
            <span style={{ display: "inline-flex", gap: 24 }}>
              <SemiCheckbox.Checkbox
                checked={settings.trigger_manual_upload}
                onChange={(event) => update({ trigger_manual_upload: event.target.checked })}
              >
                手动上传
              </SemiCheckbox.Checkbox>
              <SemiCheckbox.Checkbox
                checked={settings.trigger_mailbox_import}
                onChange={(event) => update({ trigger_mailbox_import: event.target.checked })}
              >
                邮箱入库
              </SemiCheckbox.Checkbox>
            </span>
          </div>
        </SemiSpace>

        <BackofficeButton
          loading={saving}
          onClick={() => void save()}
          tone="primary"
        >
          保存
        </BackofficeButton>
      </div>
    </Suspense>
  );
}
