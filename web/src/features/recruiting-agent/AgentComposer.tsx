import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
} from "react";
import { Icon } from "../../icons";

export type AgentReferenceKind =
  | "candidate"
  | "job"
  | "filter"
  | "talent_profile";

export interface AgentReference {
  /** Kept only in React state. Active references are always server-issued. */
  referenceId: string;
  kind: AgentReferenceKind;
  label: string;
  description?: string;
}

const referenceKindLabel: Record<AgentReferenceKind, string> = {
  candidate: "候选人",
  job: "关联 JD",
  filter: "当前筛选",
  talent_profile: "人才画像",
};

interface AgentComposerProps {
  value: string;
  references: AgentReference[];
  availableReferences: AgentReference[];
  disabled: boolean;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  onChange: (value: string) => void;
  onRemoveReference: (referenceId: string) => void;
  onSelectReference: (reference: AgentReference) => void;
  onSubmit: () => void;
}

function referenceMatchesQuery(reference: AgentReference, query: string): boolean {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return true;
  return [
    reference.label,
    reference.description,
    referenceKindLabel[reference.kind],
  ].some((value) => value?.toLocaleLowerCase().includes(normalized));
}

function referenceIcon(reference: AgentReference): "user" | "briefcase" | "filter" | "spark" {
  if (reference.kind === "candidate") return "user";
  if (reference.kind === "job") return "briefcase";
  if (reference.kind === "filter") return "filter";
  return "spark";
}

export function AgentComposer({
  value,
  references,
  availableReferences,
  disabled,
  inputRef,
  onChange,
  onRemoveReference,
  onSelectReference,
  onSubmit,
}: AgentComposerProps) {
  const menuId = useId();
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({});

  const selectedIds = useMemo(
    () => new Set(references.map((reference) => reference.referenceId)),
    [references],
  );
  const matches = useMemo(
    () => availableReferences.filter((reference) => (
      !selectedIds.has(reference.referenceId) && referenceMatchesQuery(reference, query)
    )),
    [availableReferences, query, selectedIds],
  );
  const activeOptionId = matches[activeIndex]
    ? `${menuId}-option-${activeIndex}`
    : undefined;

  const positionMenu = () => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const width = Math.min(22 * 16, window.innerWidth - 24);
    const left = Math.min(
      Math.max(12, rect.left),
      Math.max(12, window.innerWidth - width - 12),
    );
    setMenuStyle({
      position: "fixed",
      width,
      left,
      bottom: Math.max(12, window.innerHeight - rect.top + 12),
    });
  };

  const closeMenu = (restoreFocus = false) => {
    setMenuOpen(false);
    setQuery("");
    setActiveIndex(0);
    if (restoreFocus) window.requestAnimationFrame(() => inputRef.current?.focus());
  };

  const openMenu = () => {
    if (disabled) return;
    positionMenu();
    setMenuOpen(true);
    setActiveIndex(0);
  };

  useEffect(() => {
    if (!menuOpen) return undefined;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        !menuRef.current?.contains(target)
        && !triggerRef.current?.contains(target)
      ) {
        closeMenu();
      }
    };
    const reposition = () => positionMenu();
    document.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [menuOpen]);

  useEffect(() => {
    if (activeIndex >= matches.length) setActiveIndex(Math.max(0, matches.length - 1));
  }, [activeIndex, matches.length]);

  const selectReference = (reference: AgentReference) => {
    onSelectReference(reference);
    closeMenu(true);
  };

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (menuOpen) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenu(true);
        return;
      }
      if (event.key === "ArrowDown" && matches.length) {
        event.preventDefault();
        setActiveIndex((current) => (current + 1) % matches.length);
        return;
      }
      if (event.key === "ArrowUp" && matches.length) {
        event.preventDefault();
        setActiveIndex((current) => (current - 1 + matches.length) % matches.length);
        return;
      }
      if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
        const active = matches[activeIndex];
        if (active) {
          event.preventDefault();
          selectReference(active);
          return;
        }
      }
    }
    if (event.key === "@" && !event.nativeEvent.isComposing) {
      event.preventDefault();
      openMenu();
      return;
    }
    if (
      event.key === "Enter"
      && !event.shiftKey
      && !event.repeat
      && !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      onSubmit();
    }
  };

  const handleMenuKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeMenu(true);
      return;
    }
    if (event.key === "ArrowDown" && matches.length) {
      event.preventDefault();
      setActiveIndex((current) => (current + 1) % matches.length);
      return;
    }
    if (event.key === "ArrowUp" && matches.length) {
      event.preventDefault();
      setActiveIndex((current) => (current - 1 + matches.length) % matches.length);
      return;
    }
    if (event.key === "Enter" && !event.nativeEvent.isComposing) {
      const active = matches[activeIndex];
      if (active) {
        event.preventDefault();
        selectReference(active);
      }
    }
  };

  return (
    <div className="agent-composer">
      <form
        className="agent-input-row"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <div className="agent-composer-surface">
          {references.length > 0 && (
            <div className="agent-reference-chip-list" aria-label="已引用内容">
              {references.map((reference) => (
                <span className="agent-reference-chip" key={reference.referenceId}>
                  <Icon name={referenceIcon(reference)} size={14} />
                  <span>{reference.label}</span>
                  <button
                    aria-label={`移除引用：${reference.label}`}
                    disabled={disabled}
                    onClick={() => onRemoveReference(reference.referenceId)}
                    type="button"
                  >
                    <Icon name="close" size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}
          <label className="sr-only" htmlFor="agent-message">向招聘助手提问</label>
          <textarea
            disabled={disabled}
            id="agent-message"
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="描述要查找、比较或核验的内容，输入 @ 引用相关资料"
            ref={inputRef}
            rows={2}
            value={value}
          />
          <div className="agent-composer-actions">
            <button
              aria-controls={`${menuId}-list`}
              aria-expanded={menuOpen}
              aria-haspopup="listbox"
              aria-label="添加引用"
              className="agent-reference-trigger"
              disabled={disabled}
              onClick={openMenu}
              ref={triggerRef}
              type="button"
            >
              @
            </button>
            <span className="agent-composer-keyboard-hint" aria-hidden="true">
              Enter 发送
            </span>
            <button
              aria-label="发送提问"
              className="button button-primary agent-send-button"
              disabled={disabled || !value.trim()}
              type="submit"
            >
              <Icon name="arrow-right" size={17} />
            </button>
          </div>
        </div>
      </form>
      {menuOpen && (
        <div
          className="agent-reference-menu"
          id={menuId}
          ref={menuRef}
          style={menuStyle}
        >
          <div className="agent-reference-menu-search">
            <Icon name="search" size={15} />
            <input
              aria-activedescendant={activeOptionId}
              aria-autocomplete="list"
              aria-controls={`${menuId}-list`}
              aria-expanded="true"
              aria-haspopup="listbox"
              aria-label="搜索要引用的资料"
              autoFocus
              onChange={(event) => {
                setQuery(event.target.value);
                setActiveIndex(0);
              }}
              onKeyDown={handleMenuKeyDown}
              placeholder="搜索可引用内容"
              role="combobox"
              value={query}
            />
            <button aria-label="关闭引用菜单" onClick={() => closeMenu(true)} type="button">
              <Icon name="close" size={14} />
            </button>
          </div>
          <div
            aria-label="选择要引用的资料"
            className="agent-reference-menu-list"
            id={`${menuId}-list`}
            role="listbox"
          >
            {matches.length ? matches.map((reference, index) => (
              <button
                aria-selected={index === activeIndex}
                className={index === activeIndex ? "is-active" : undefined}
                id={`${menuId}-option-${index}`}
                key={reference.referenceId}
                onMouseEnter={() => setActiveIndex(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => selectReference(reference)}
                role="option"
                type="button"
              >
                <Icon name={referenceIcon(reference)} size={16} />
                <span>
                  <strong>{reference.label}</strong>
                  {reference.description && <small>{reference.description}</small>}
                </span>
                <em>{referenceKindLabel[reference.kind]}</em>
              </button>
            )) : (
              <p className="agent-reference-menu-empty">当前没有可引用的内容。</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
