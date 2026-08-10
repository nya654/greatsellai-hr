import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Icon } from "../../icons";
import type { Announcement } from "../../types";
import { adminApi, adminErrorMessage } from "../admin-api";
import type { RequestState } from "../admin-types";
import {
  AdminEmpty,
  AdminError,
  AdminLoading,
  AdminPageHeader,
  AdminStatus,
  formatDate,
} from "../AdminComponents";

const EMPTY_DRAFT = { title: "", body: "" };

type BusyAction = "" | "save" | "publish" | "unpublish" | "delete";

/** Platform-wide system announcements: create-now-publish-live, manual lifecycle. */
export function AdminAnnouncementsPage() {
  const [state, setState] = useState<RequestState>("loading");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [items, setItems] = useState<Announcement[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<{ title: string; body: string } | null>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [busyAction, setBusyAction] = useState<BusyAction>("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const loadRequestRef = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++loadRequestRef.current;
    setState("loading");
    setError("");
    try {
      const next = await adminApi.listAnnouncements(true);
      if (requestId !== loadRequestRef.current) return;
      setItems(next);
      setSelectedId((current) =>
        current && next.some((item) => item.announcement_id === current)
          ? current
          : next[0]?.announcement_id ?? null,
      );
      setState("ready");
    } catch (loadError) {
      if (requestId !== loadRequestRef.current) return;
      setError(adminErrorMessage(loadError));
      setState("error");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Reset the editor whenever the selection or mode changes (not while typing).
  useEffect(() => {
    setConfirmDelete(false);
    if (creating) {
      setDraft(EMPTY_DRAFT);
      return;
    }
    const item = items.find((candidate) => candidate.announcement_id === selectedId) ?? null;
    setDraft(item ? { title: item.title, body: item.body } : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [creating, selectedId]);

  const selected = items.find((item) => item.announcement_id === selectedId) ?? null;

  const startCreate = () => {
    setCreating(true);
    setSelectedId(null);
    setReason("");
    setError("");
    setNotice("");
  };

  const selectItem = (item: Announcement) => {
    setCreating(false);
    setSelectedId(item.announcement_id);
    setReason("");
    setError("");
    setNotice("");
  };

  const submitSave = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft || !reason.trim() || saving) return;
    const wasCreating = creating;
    setBusyAction("save");
    setSaving(true);
    setNotice("");
    setError("");
    try {
      const input = { title: draft.title.trim(), body: draft.body.trim(), reason: reason.trim() };
      const saved = wasCreating
        ? await adminApi.createAnnouncement(input)
        : selectedId
          ? await adminApi.updateAnnouncement(selectedId, input)
          : null;
      if (!saved) return;
      setItems((current) =>
        wasCreating
          ? [saved, ...current]
          : current.map((item) => item.announcement_id === saved.announcement_id ? saved : item),
      );
      setCreating(false);
      setSelectedId(saved.announcement_id);
      setDraft({ title: saved.title, body: saved.body });
      setReason("");
      setNotice(wasCreating ? "公告已创建并立即发布给所有工作台用户。" : "公告内容已更新。");
    } catch (saveError) {
      setError(adminErrorMessage(saveError));
    } finally {
      setSaving(false);
      setBusyAction("");
    }
  };

  const togglePublish = async () => {
    if (!selected || !reason.trim() || saving) return;
    const publish = !selected.is_published;
    setBusyAction(publish ? "publish" : "unpublish");
    setSaving(true);
    setNotice("");
    setError("");
    try {
      const updated = publish
        ? await adminApi.publishAnnouncement(selected.announcement_id, reason.trim())
        : await adminApi.unpublishAnnouncement(selected.announcement_id, reason.trim());
      setItems((current) =>
        current.map((item) => item.announcement_id === updated.announcement_id ? updated : item),
      );
      setDraft({ title: updated.title, body: updated.body });
      setReason("");
      setNotice(publish ? "公告已发布，所有工作台用户现在都能看到。" : "公告已下架，工作台不再展示。");
    } catch (toggleError) {
      setError(adminErrorMessage(toggleError));
    } finally {
      setSaving(false);
      setBusyAction("");
    }
  };

  const removeAnnouncement = async () => {
    if (!selected || !reason.trim() || saving) return;
    setBusyAction("delete");
    setSaving(true);
    setNotice("");
    setError("");
    try {
      await adminApi.deleteAnnouncement(selected.announcement_id, reason.trim());
      const remaining = items.filter((item) => item.announcement_id !== selected.announcement_id);
      setItems(remaining);
      setSelectedId(remaining[0]?.announcement_id ?? null);
      setCreating(false);
      setReason("");
      setNotice("公告已删除，所有用户对该公告的已读状态一并清除。");
    } catch (deleteError) {
      setError(adminErrorMessage(deleteError));
    } finally {
      setSaving(false);
      setBusyAction("");
    }
  };

  const showEditor = state === "ready" && (items.length > 0 || creating);

  return (
    <section className="admin-page-frame" aria-labelledby="admin-announcements-title">
      <AdminPageHeader
        actions={<button className="button" onClick={() => void load()} type="button"><Icon name="refresh" size={16} />刷新公告</button>}
        description="创建即发布给所有工作台用户；可随时下架、编辑或删除，变更都会写入平台审计。"
        title="公告管理"
      />
      {state === "loading" && <div className="admin-panel"><AdminLoading label="正在读取公告…" /></div>}
      {state === "error" && <div className="admin-panel"><AdminError message={error} onRetry={() => void load()} /></div>}
      {state === "ready" && items.length === 0 && !creating && (
        <div className="admin-panel">
          <AdminEmpty
            action={<button className="button button-primary" onClick={startCreate} type="button">新建第一条公告</button>}
            description="还没有系统公告。新建后立即对全部工作台用户可见。"
            title="暂无公告"
          />
        </div>
      )}
      {showEditor && (
        <div className="admin-plan-layout">
          <nav aria-label="公告列表" className="admin-plan-list">
            <button className={creating ? "is-selected" : ""} onClick={startCreate} type="button">
              <span><strong>新建公告</strong><small>创建后立即发布</small></span>
              <Icon name="plus" size={16} />
            </button>
            {items.map((item) => (
              <button
                aria-current={!creating && selectedId === item.announcement_id ? "page" : undefined}
                className={!creating && selectedId === item.announcement_id ? "is-selected" : ""}
                key={item.announcement_id}
                onClick={() => selectItem(item)}
                type="button"
              >
                <span><strong>{item.title}</strong><small>{formatDate(item.published_at ?? item.created_at, true)}</small></span>
                <AdminStatus status={item.is_published ? "active" : "inactive"} label={item.is_published ? "已发布" : "已下架"} />
              </button>
            ))}
          </nav>
          {draft && (
            <form className="admin-panel admin-plan-editor" onSubmit={(event) => void submitSave(event)}>
              <div className="admin-section-heading">
                <div><h2>{creating ? "新建公告" : "编辑公告"}</h2><p>{creating ? "保存后立即发布给所有工作台用户。" : selected?.is_published ? "当前已发布，所有工作台用户可见。" : "当前已下架，工作台不再展示。"}</p></div>
                {selected && <AdminStatus status={selected.is_published ? "active" : "inactive"} label={selected.is_published ? "已发布" : "已下架"} />}
              </div>
              <div className="admin-form-grid">
                <label className="admin-announcement-span-2"><span>公告标题</span><input className="field" maxLength={200} onChange={(event) => setDraft({ ...draft, title: event.target.value })} required value={draft.title} /></label>
                <label className="admin-announcement-span-2"><span>公告正文</span><textarea className="textarea-field" maxLength={5000} onChange={(event) => setDraft({ ...draft, body: event.target.value })} placeholder="纯文本正文，会原样展示在每位用户工作台铃铛的公告面板中。" required rows={8} value={draft.body} /></label>
              </div>
              <label className="admin-reason-field"><span>变更原因（平台审计）</span><textarea className="textarea-field" maxLength={500} onChange={(event) => { setReason(event.target.value); setConfirmDelete(false); }} placeholder="填写发布背景、调整依据或删除原因" required rows={3} value={reason} /></label>
              {error && <p className="admin-form-error" role="alert">{error}</p>}
              {notice && <p className="admin-form-success" role="status">{notice}</p>}
              <div className="admin-form-actions">
                <button className="button" disabled={saving} onClick={() => { setReason(""); setError(""); setNotice(""); }} type="button">清空</button>
                <button className="button button-primary" disabled={saving || !draft.title.trim() || !draft.body.trim() || !reason.trim()} type="submit">
                  {saving && busyAction === "save" ? <><i className="spinner" />正在保存</> : creating ? "发布公告" : "保存修改"}
                </button>
              </div>
              {!creating && selected && (
                <section className="admin-announcement-actions">
                  <div className="admin-detail-section-heading"><h3>{selected.is_published ? "下架公告" : "发布公告"}</h3></div>
                  <p>{selected.is_published ? "下架后工作台铃铛不再展示，每位用户的已读状态会保留。" : "发布后立即出现在所有工作台用户的铃铛中，未读数量会随之更新。"}</p>
                  <button
                    className={`button${selected.is_published ? " button-ghost" : " button-primary"}`}
                    disabled={saving || !reason.trim()}
                    onClick={() => void togglePublish()}
                    type="button"
                  >{saving && busyAction === (selected.is_published ? "unpublish" : "publish") ? <><i className="spinner" />正在处理</> : selected.is_published ? "下架公告" : "发布公告"}</button>
                  <div className="admin-detail-section-heading admin-announcement-delete-heading"><h3>删除公告</h3></div>
                  <p>删除后不可恢复，所有用户对该公告的已读状态一并清除。</p>
                  <button
                    className={`button button-danger-ghost${confirmDelete ? " is-confirm" : ""}`}
                    disabled={saving || !reason.trim()}
                    onClick={() => {
                      if (!confirmDelete) { setConfirmDelete(true); return; }
                      void removeAnnouncement();
                    }}
                    type="button"
                  >{saving && busyAction === "delete" ? <><i className="spinner" />正在删除</> : confirmDelete ? "再次点击确认删除" : "删除公告"}</button>
                </section>
              )}
            </form>
          )}
        </div>
      )}
    </section>
  );
}
