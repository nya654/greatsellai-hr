import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { Icon } from "../../icons";
import type { AnnouncementInbox } from "../../types";

function formatAnnouncementTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/** Displays a number as "99+" beyond three digits, keeping the badge compact. */
function badgeText(count: number): string {
  return count > 99 ? "99+" : String(count);
}

/**
 * The topbar bell for platform-wide system announcements.  Fetching the inbox
 * on mount keeps the unread badge live without opening the panel; opening the
 * panel acknowledges every active announcement (server-side, per user) so the
 * badge clears for exactly this account.
 */
export function AnnouncementBell() {
  const [inbox, setInbox] = useState<AnnouncementInbox | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  const unreadCount = inbox?.unread_count ?? 0;
  const items = inbox?.items ?? [];

  useEffect(() => {
    let active = true;
    api
      .getAnnouncementInbox()
      .then((next) => {
        if (!active) return;
        setInbox(next);
        setLoadFailed(false);
      })
      .catch(() => {
        if (active) setLoadFailed(true);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!isOpen) return;

    const closeFromOutside = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && rootRef.current?.contains(target)) return;
      setIsOpen(false);
    };
    const closeFromEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setIsOpen(false);
      window.requestAnimationFrame(() => triggerRef.current?.focus());
    };

    document.addEventListener("pointerdown", closeFromOutside);
    document.addEventListener("keydown", closeFromEscape);
    return () => {
      document.removeEventListener("pointerdown", closeFromOutside);
      document.removeEventListener("keydown", closeFromEscape);
    };
  }, [isOpen]);

  const togglePanel = async () => {
    if (isOpen) {
      setIsOpen(false);
      return;
    }
    setIsOpen(true);
    // Opening the panel acknowledges every active announcement.  The same call
    // also returns the freshest inbox, so a first open doubles as a load.
    try {
      setInbox(await api.markAnnouncementsRead());
      setLoadFailed(false);
    } catch {
      // Keep the panel open; the badge refreshes on the next load or open.
    }
  };

  return (
    <div className="announcement-bell" ref={rootRef}>
      <button
        aria-controls="announcement-bell-popover"
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-label={
          unreadCount > 0 ? `系统公告，${unreadCount} 条未读` : "系统公告"
        }
        className="announcement-bell-trigger"
        onClick={() => void togglePanel()}
        ref={triggerRef}
        type="button"
      >
        <Icon name="bell" size={18} />
        {unreadCount > 0 && (
          <span className="announcement-bell-badge" aria-hidden="true">
            {badgeText(unreadCount)}
          </span>
        )}
      </button>
      {isOpen && (
        <section
          aria-label="系统公告"
          className="announcement-bell-popover"
          id="announcement-bell-popover"
          role="dialog"
        >
          <header className="announcement-bell-header">
            <strong>系统公告</strong>
            {unreadCount > 0 && <small>{unreadCount} 条未读</small>}
          </header>
          {loadFailed ? (
            <p className="announcement-bell-empty">公告加载失败，请稍后重试。</p>
          ) : items.length === 0 ? (
            <p className="announcement-bell-empty">暂无公告。</p>
          ) : (
            <ul className="announcement-bell-list">
              {items.map((item) => (
                <li className="announcement-bell-item" key={item.announcement_id}>
                  <h4>{item.title}</h4>
                  <p>{item.body}</p>
                  <time dateTime={item.published_at ?? item.created_at}>
                    {formatAnnouncementTime(item.published_at ?? item.created_at)}
                  </time>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
