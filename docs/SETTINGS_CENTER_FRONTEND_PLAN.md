# Settings Center Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the workspace settings center with Semi UI (left grouped sidebar + master-detail mailbox + consistent panels), and add the AI-import-processing and filter-display-fields settings sections.

**Architecture:** Rewrite `WorkspaceSettingsPage` as a Semi `Layout`/`Navigation` shell with two groups. New `AiImportSettingsPanel` + `DisplayFieldsSettingsPanel` consume the new backend endpoints. `MailboxPage` and `CandidateDataLifecyclePage` keep all business logic/state but their JSX presentation moves to Semi components; custom CSS files for these features are deleted. Display-field preference is applied in `ResultsPane` (falling back to current auto-derived columns when the user has no saved selection).

**Tech Stack:** React, TypeScript, Vite, `@douyinfe/semi-ui-19` (v2.101.1), `@douyinfe/semi-icons`, existing wrappers `BackofficeButton` / `BackofficeInput` / `BackofficeSelect` / `BackofficeProgress`.

## Global Constraints

- **Controls must use Semi** (`@douyinfe/semi-ui-19`) or the project's existing Backoffice wrappers (per `AGENTS.md`). No custom `div`+ARIA+CSS re-implementations of buttons, inputs, selects, tabs, tables, tags, toasts, or navigation. Custom CSS for these features is **deleted**, not extended.
- **Business logic untouched.** All API calls, state management, validation, and permission logic in `MailboxPage` / `CandidateDataLifecyclePage` stay as-is; only the rendered JSX and its styles change.
- **Display-field preference is per-user** and applies to the filter results table. Empty preference ⇒ fall back to current auto-derived columns (`activeResultDisplayColumns`).
- **AI-import settings defaults** (from backend): all toggles on; auto-score requires a default template (backend rejects without one — surface the error via `Toast`).
- **Keep the existing `embedded` prop semantics** — these pages are rendered only inside the settings center.
- **Verify Semi prop names against the installed `@douyinfe/semi-ui-19` type definitions** (`node_modules/@douyinfe/semi-ui-19`) where the plan references Semi APIs; minor prop-name drift between Semi minors is the only acceptable deviation.
- **End:** `npm run build` in `web/` must pass; existing `web/e2e` suite must pass (with updates where assertions reference removed markup).

---

### Task 1: Types + api client methods

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/api.ts`

**Interfaces:**
- Consumes: existing `request<T>(path, opts)` helper in `api.ts`; existing type style.
- Produces:
  - `AiImportSettings` and `DisplayFieldPreferences` TS interfaces (matching the backend `AiImportSettingsResponse` / `DisplayFieldPreferencesResponse`).
  - `api.getAiImportSettings()`, `api.updateAiImportSettings(input)`, `api.getDisplayFieldPreferences()`, `api.updateDisplayFieldPreferences(fieldKeys: string[])`.

- [ ] **Step 1: Write the types**

In `web/src/types.ts` (near the other settings-related types):

```ts
export interface AiImportSettings {
  auto_summary_enabled: boolean;
  auto_score_enabled: boolean;
  default_score_template_id: string | null;
  trigger_manual_upload: boolean;
  trigger_mailbox_import: boolean;
}

export interface DisplayFieldPreferences {
  display_field_keys: string[];
}
```

- [ ] **Step 2: Add the api methods**

In `web/src/api.ts` inside `createApiClient` (near the other settings/lifecycle calls):

```ts
getAiImportSettings(): Promise<AiImportSettings> {
  return request<AiImportSettings>("/settings/ai-import");
},

updateAiImportSettings(input: AiImportSettings): Promise<AiImportSettings> {
  return request<AiImportSettings>("/settings/ai-import", {
    method: "PUT",
    body: JSON.stringify(input),
  });
},

getDisplayFieldPreferences(): Promise<DisplayFieldPreferences> {
  return request<DisplayFieldPreferences>("/settings/display-fields");
},

updateDisplayFieldPreferences(fieldKeys: string[]): Promise<DisplayFieldPreferences> {
  return request<DisplayFieldPreferences>("/settings/display-fields", {
    method: "PUT",
    body: JSON.stringify({ display_field_keys: fieldKeys }),
  });
},
```

Confirm `request` already sends `Content-Type: application/json` and handles 4xx as `ApiError` (it does — mirror neighboring calls).

- [ ] **Step 3: Type-check**

Run: `cd web && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/types.ts web/src/api.ts
git commit -m "feat: add settings center api client methods + types"
```

---

### Task 2: Extend settings section type + navigation state

**Files:**
- Modify: `web/src/features/workspace-shell/workspace-navigation-types.ts`
- Modify: `web/src/features/workspace-shell/useWorkspaceNavigation.ts`

**Interfaces:**
- Consumes: existing `WorkspaceSettingsSection` usage in `WorkspaceViewRouter.tsx` / `App.tsx` (they pass `activeSection` / `settingsSection` through unchanged).
- Produces:
  - `WorkspaceSettingsSection = "mailbox" | "data" | "ai-import" | "display-fields"`.
  - `settingsSectionFromHash` parses `ai-import` and `display-fields` (check the current hash format in the file — it maps `mailbox`/`data`, likely `#settings/<section>` or similar; follow its exact pattern).
  - Section visibility/validation: `ai-import` requires admin; `display-fields` requires any member.

- [ ] **Step 1: Extend the union type**

`web/src/features/workspace-shell/workspace-navigation-types.ts`:

```ts
export type WorkspaceSettingsSection =
  | "mailbox"
  | "data"
  | "ai-import"
  | "display-fields";
```

- [ ] **Step 2: Extend hash parsing + validation**

Read `useWorkspaceNavigation.ts` fully first. Update `settingsSectionFromHash` and the validation block (currently around lines 186-187, which checks `canManageMailbox`/`canManageCandidateData`) so that:

- `mailbox` valid only when `canManageMailbox`
- `data` valid only when `canManageCandidateData`
- `ai-import` valid only when `authSession?.role === "admin"`
- `display-fields` always valid for a signed-in member

Add `ai-import` and `display-fields` to the fallback logic so an out-of-permission hash falls back to the first allowed section (mirror the existing fallback).

- [ ] **Step 3: Type-check**

Run: `cd web && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/features/workspace-shell/workspace-navigation-types.ts web/src/features/workspace-shell/useWorkspaceNavigation.ts
git commit -m "feat: extend settings sections to ai-import and display-fields"
```

---

### Task 3: Settings center shell — Semi rebuild

**Files:**
- Rewrite: `web/src/features/workspace-settings/WorkspaceSettingsPage.tsx`
- Delete: `web/src/features/workspace-settings/workspace-settings.css`
- Modify (minimal): `web/src/features/workspace-shell/WorkspaceViewRouter.tsx` (pass the two new section render branches)

**Interfaces:**
- Consumes: `AiImportSettingsPanel` (Task 4), `DisplayFieldsSettingsPanel` (Task 5), existing `MailboxPage` / `CandidateDataLifecyclePage`, `WorkspaceSettingsSection`, `IconName`.
- Produces: a Semi `Layout` (Sider + Content) shell with a grouped `Navigation` sidebar; the content area renders the active section.

- [ ] **Step 1: Rewrite the shell**

Replace the custom `settings-navigation-*` markup with Semi. Representative structure (verify the exact `Navigation` grouping API against the installed Semi types; Semi supports a `type: "groupTitle"` item for group headers):

```tsx
import { Layout, Navigation } from "@douyinfe/semi-ui-19";
import type { WorkspaceSettingsSection } from "../workspace-shell/workspace-navigation-types";
import { AiImportSettingsPanel } from "./AiImportSettingsPanel";
import { DisplayFieldsSettingsPanel } from "./DisplayFieldsSettingsPanel";

function settingsGroups(
  canManageMailbox: boolean,
  canManageCandidateData: boolean,
  canManageAiImport: boolean,
): Array<{ group: string; items: Array<{ key: WorkspaceSettingsSection; label: string; icon: IconName }> }> {
  const workspaceItems = [];
  if (canManageMailbox) workspaceItems.push({ key: "mailbox", label: "收件邮箱", icon: "inbox" });
  if (canManageCandidateData) workspaceItems.push({ key: "data", label: "候选人数据与保留", icon: "gear" });
  if (canManageAiImport) workspaceItems.push({ key: "ai-import", label: "AI 导入处理", icon: "spark" });
  return [
    { group: "工作区设置", items: workspaceItems },
    { group: "个人偏好", items: [{ key: "display-fields", label: "筛选显示字段", icon: "eye" }] },
  ];
}
```

Render with `Layout`/`Layout.Sider`/`Layout.Content`, a `Navigation` whose items are the flattened group list (group headers as `type: "groupTitle"`), `selectedKeys={[currentSection]}`, and `onSelect={(data) => onSelectSection(data.itemKey as WorkspaceSettingsSection)}`. The content panel renders by `currentSection`:

```tsx
{currentSection === "mailbox" && (
  <MailboxPage embedded formatError={formatError} notify={notify} onImported={onImported} role={role} />
)}
{currentSection === "data" && (
  <CandidateDataLifecyclePage embedded formatError={formatError} notify={notify} onOpenLibrary={onOpenLibrary} />
)}
{currentSection === "ai-import" && (
  <AiImportSettingsPanel formatError={formatError} notify={notify} />
)}
{currentSection === "display-fields" && (
  <DisplayFieldsSettingsPanel formatError={formatError} notify={notify} />
)}
```

Keep the page heading (设置 · 当前工作区 + role pill) but render it with Semi `Typography.Title` / `Tag` instead of the custom `.settings-heading` markup. Remove the tab-arrow-key handler — `Navigation` manages keyboard interaction natively.

- [ ] **Step 2: Delete the custom CSS**

```bash
git rm web/src/features/workspace-settings/workspace-settings.css
```

Remove the now-unused CSS class names from the JSX (done in Step 1). If any layout tokens (spacing between Sider and Content) are needed, use Semi's `Layout` style props / theme tokens, not a new CSS file.

- [ ] **Step 3: Verify render**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: PASS. Manually (dev server) confirm the grouped sidebar renders and section switching works.

- [ ] **Step 4: Commit**

```bash
git add web/src/features/workspace-settings/WorkspaceSettingsPage.tsx web/src/features/workspace-shell/WorkspaceViewRouter.tsx
git rm --cached web/src/features/workspace-settings/workspace-settings.css
git commit -m "feat: rebuild settings center shell with Semi navigation"
```

---

### Task 4: AI 导入处理 panel (new)

**Files:**
- Create: `web/src/features/workspace-settings/AiImportSettingsPanel.tsx`

**Interfaces:**
- Consumes: `api.getAiImportSettings`, `api.updateAiImportSettings`, `api.listScoreTemplates` (existing), `BackofficeSelect`, `BackofficeButton`, Semi `Switch`, `RadioGroup`, `Toast`.
- Produces: `AiImportSettingsPanel({ formatError, notify }: { formatError: (e: unknown) => string; notify: (k: "success" | "error", m: string) => void })`.

- [ ] **Step 1: Write the panel**

State: `settings: AiImportSettings | null`, `templates: ScoreTemplate[]`, `saving: boolean`. Load both in `useEffect`. Render:

- **自动生成 AI 总结** — Semi `Switch` bound to `settings.auto_summary_enabled`.
- **自动评分** — Semi `Switch` bound to `settings.auto_score_enabled`; when on, the template `BackofficeSelect` becomes required (disable saving and show an inline `Toast.error("请先选择默认评分模板")` if off).
- **默认评分模板** — `BackofficeSelect` over `templates` (`value={settings.default_score_template_id ?? ""}`), option label = template name.
- **触发来源** — Semi `RadioGroup` with two options: 手动上传 / 邮箱入库 (values `trigger_manual_upload` / `trigger_mailbox_import`), each bound to its boolean.
- **保存** — `BackofficeButton tone="primary"`; on click validate, `api.updateAiImportSettings`, `notify("success", "AI 导入处理设置已保存。")`, then reload. On error `notify("error", formatError(err))`.

Add a Semi `Typography.Paragraph` (or `Alert`) note: "开启后，导入的简历将自动运行 AI 提取、总结与评分，会产生对应的模型调用费用。"

Representative save handler:

```tsx
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
  } catch (err) {
    notify("error", formatError(err));
  } finally {
    setSaving(false);
  }
};
```

- [ ] **Step 2: Type-check + build**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/src/features/workspace-settings/AiImportSettingsPanel.tsx
git commit -m "feat: add AI import processing settings panel"
```

---

### Task 5: 筛选显示字段 panel (new) + results pane wiring

**Files:**
- Create: `web/src/features/workspace-settings/DisplayFieldsSettingsPanel.tsx`
- Modify: `web/src/features/filter/ResultsPane.tsx` (use saved preference when present)
- Modify: `web/src/features/filter/FilterWorkspace.tsx` or `useCandidateSearchController.ts` (thread the preference into results, per how `ResultsPane` currently receives `appliedDraft` — read the data flow first)

**Interfaces:**
- Consumes: `api.getDisplayFieldPreferences`, `api.updateDisplayFieldPreferences`, `CandidateSearchDisplayFieldKey` (from `web/src/types.ts`), the display-field label map currently living in `ResultsPane`.
- Produces:
  - `DisplayFieldsSettingsPanel({ formatError, notify })`.
  - A shared `DISPLAY_FIELD_OPTIONS: Array<{ key: CandidateSearchDisplayFieldKey; label: string }>` module (move the label map out of `ResultsPane` into e.g. `web/src/features/filter/display-field-options.ts`) used by both the panel and `ResultsPane`.
  - `ResultsPane` shows the user's saved fields when a saved selection exists, else the existing auto-derived columns.

- [ ] **Step 1: Extract a shared display-field options module**

Create `web/src/features/filter/display-field-options.ts` exporting the 22 options (key + Chinese label) — reuse the exact labels currently in `ResultsPane`/`filter-model`. Update `ResultsPane` to import from it.

- [ ] **Step 2: Write the panel**

`DisplayFieldsSettingsPanel` renders Semi `CheckboxGroup` over `DISPLAY_FIELD_OPTIONS` plus a `BackofficeButton` 保存. Load current preference on mount; on save call `api.updateDisplayFieldPreferences(keys)` and toast. Show hint "选择后，筛选结果表将固定显示这些字段；未选择时沿用自动推断。"

- [ ] **Step 3: Wire the results pane**

Read how `ResultsPane` obtains columns (it currently computes via `activeResultDisplayColumns(appliedDraft)`). Change so that when a saved `display_field_keys` preference exists, columns = saved keys' labels; otherwise fall back to `activeResultDisplayColumns`. Thread the saved preference from `FilterWorkspace`/`useCandidateSearchController` into `ResultsPane` (load it once per mount via `api.getDisplayFieldPreferences`).

```ts
const savedColumns = (savedKeys.length
  ? savedKeys.map((key) => ({ key, label: displayFieldLabel(key) }))
  : activeResultDisplayColumns(appliedDraft));
```

- [ ] **Step 4: Type-check + build**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/workspace-settings/DisplayFieldsSettingsPanel.tsx web/src/features/filter/display-field-options.ts web/src/features/filter/ResultsPane.tsx web/src/features/filter/FilterWorkspace.tsx web/src/features/filter/useCandidateSearchController.ts
git commit -m "feat: add filter display-field settings panel and apply to results"
```

---

### Task 6: Mailbox section — master-detail Semi rebuild

**Files:**
- Modify: `web/src/features/mailbox/MailboxPage.tsx` (structure + JSX only)
- Rewrite: `web/src/features/mailbox/components/MailboxChannelList.tsx`
- Delete: mailbox custom CSS (grep `import "./mailbox.css"` / `mailbox-*.css` in `MailboxPage.tsx` and remove; delete the file(s))
- Modify: `web/src/features/mailbox/mailbox-model.ts` only if a status-class helper is no longer needed

**Interfaces:**
- Consumes: all existing state, handlers, and api calls in `MailboxPage.tsx` — unchanged.
- Produces: a left-column channel list (Semi `Tabs` with `tabPosition="left"` OR Semi `List` of selectable rows + a Semi `Button` "新建收件通道"), and a right content column with the connection form, status panel, source-tag rules, and retention/history sections rendered with Semi components.

**Step 1 — Read `MailboxPage.tsx` fully.** Identify these regions (confirmed present):
- channel list (`<MailboxChannelList ... />` ~line 1655)
- connection fields (`mailboxConnectionFields` — provider / identity / initial sync / connection)
- form actions (`mailboxFormActions`)
- status panel (`mailbox-status-panel` — fact-list)
- source-tag rules panel (`mailboxSourceTagRulesPanel`)
- retention panel (`mailbox-retention-panel`), history/imports list
- the setup/getting-started aside (when no channels)

Then convert each region per the mapping below, leaving every handler/state/API call untouched.

- [ ] **Step 2: Left channel list**

Rewrite `MailboxChannelList.tsx` to a left column: each channel rendered as a Semi `Tabs.Tab` (vertical) OR a `List` row with `Tag` for status. The current horizontal "panel above detail" container is removed. "新建收件通道" becomes a `BackofficeButton` at the top of the left column. Keep the existing `onCreate` / `onSelect` / `selectedMailboxId` props.

- [ ] **Step 3: Connection form + actions**

Replace the custom `.mailbox-form-section` / `.field-label` / native inputs with Semi `Form` or `BackofficeInput` / `BackofficeSelect` / Semi `Switch`. Keep exact field ids for e2e (`mailbox-display-name`, `imap-address`, `imap-host`, `imap-password`, `mailbox-sync-toggle`, `initial-sync-lookback-days`).

- [ ] **Step 4: Status panel + source-tag rules + retention/history**

- Status fact rows → Semi `Descriptions` or `Card` rows.
- Source-tag rules list/editor → Semi `Table` (or `List`) + the existing editor form with `BackofficeInput`/`Select`.
- Retention panel `<details>` → Semi `Collapse` or `Card`; retention run history → Semi `List`/`Table`.
- Keep all `status-pill`-driven logic but render via Semi `Tag` (`color="red"` for error, `"green"` for success, etc.).

- [ ] **Step 5: Delete mailbox custom CSS**

Remove the CSS imports and files (`mailbox.css` and any `mailbox-*.css`). Confirm nothing else imports them.

- [ ] **Step 6: Type-check + build + manual pass**

Run: `cd web && npx tsc --noEmit && npm run build`
Then manually exercise: create a channel, edit connection, toggle sync, add a source-tag rule, view retention/history. All must work as before.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/mailbox/
git rm web/src/features/mailbox/mailbox.css
git commit -m "feat: rebuild mailbox section with Semi master-detail layout"
```

---

### Task 7: Candidate data page — Semi rebuild

**Files:**
- Modify: `web/src/features/candidate-data/CandidateDataLifecyclePage.tsx` (JSX + styles only; keep all state/handlers/API calls)
- Delete: `web/src/features/candidate-data/candidate-data.css`

**Interfaces:**
- Consumes: existing state/handlers (already read: retention policy, deletions, exports, audit events, cleanup runs).
- Produces: the same page rendered with Semi — retention form as Semi `RadioGroup` + `InputNumber`/`BackofficeInput`, tables as Semi `Table`, lists as Semi `List`, status as Semi `Tag`, actions as `BackofficeButton`, embedded-mode sub-tabs as Semi `Tabs` (or keep the two-section split but with Semi `Tabs`).

- [ ] **Step 1: Retention policy form**

Replace the custom `radiogroup`/`choice-row` with Semi `RadioGroup` + `Radio`; the days input with `BackofficeInput` (keep `min`/`max`/`inputMode`). Keep the preview block (render as Semi `Alert` or `Card`) and the three action buttons as `BackofficeButton` (`primary`/`danger`/`default`).

- [ ] **Step 2: Tables → Semi `Table`**

Convert the deletions table and exports table to Semi `Table` with `columns` + `dataSource`. Keep every cell's content and the per-row action buttons (`恢复` / `下载` / `取消`) as `BackofficeButton`. Keep `aria-label`s meaningful for accessibility.

- [ ] **Step 3: Lists → Semi `List` + empty states**

Convert the audit list and cleanup-history list to Semi `List` (or keep as `<ol>`-style but with Semi `Tag`/typography). Empty states can use a compact Semi `Empty` or a small `Typography` block. Delete `candidate-data.css` and remove its import.

- [ ] **Step 4: Type-check + build + manual pass**

Run: `cd web && npx tsc --noEmit && npm run build`
Manual: set retention (preview + save + cleanup), view deletions/exports/audit.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/candidate-data/CandidateDataLifecyclePage.tsx
git rm web/src/features/candidate-data/candidate-data.css
git commit -m "feat: rebuild candidate data settings page with Semi"
```

---

### Task 8: e2e + full verification

**Files:**
- Modify: `web/e2e/critical-paths.spec.ts` and any spec asserting on removed custom CSS classes (`settings-navigation-item`, `mailbox-channel-row`, `candidate-data-task-navigation-item`, etc.)

- [ ] **Step 1: Update e2e selectors**

Grep `web/e2e/` for the removed class names and Semi-added test ids; update selectors to stable ids (add `data-testid` where Semi components lose the old hooks — prefer existing ids like `mailbox-display-name`, `settings-tab-*`).

- [ ] **Step 2: Add settings coverage**

Add e2e assertions for: settings sidebar groups render; AI 导入处理 toggle saves; 筛选显示字段 selection saves and changes the results-table columns (when a saved selection exists).

- [ ] **Step 3: Full verification**

Run: `cd web && npm run build && npm run test:e2e` (or the repo's e2e runner — check `web/package.json`).
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/e2e/
git commit -m "test: settings center e2e coverage"
```
