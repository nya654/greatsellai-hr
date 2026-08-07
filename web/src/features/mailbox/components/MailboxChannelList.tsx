import { lazy } from "react";
import type { MailboxConfig } from "../../../types";
import { Icon } from "../../../icons";
import { BackofficeButton } from "../../../backoffice/ui/BackofficeButton";
import { TableSkeleton } from "../../../backoffice/ui/TableSkeleton";
import {
  mailboxAuthenticationModeLabel,
  mailboxChannelStatus,
  mailboxChannelStatusClass,
  mailboxProviderDisplayName,
} from "../mailbox-model";
import { MailboxStatusTag } from "./MailboxStatusTag";

const SemiList = lazy(() => import("@douyinfe/semi-ui-19/lib/es/list"));
const SemiListItem = lazy(() => import("@douyinfe/semi-ui-19/lib/es/list/item"));
const SemiTitle = lazy(() => import("@douyinfe/semi-ui-19/lib/es/typography/title"));
const SemiParagraph = lazy(() => import("@douyinfe/semi-ui-19/lib/es/typography/paragraph"));
const SemiEmpty = lazy(() => import("@douyinfe/semi-ui-19/lib/es/empty"));

interface MailboxChannelListProps {
  isCreating: boolean;
  loading: boolean;
  mailboxes: MailboxConfig[];
  selectedMailboxId: string | null;
  onCreate: () => void;
  onSelect: (config: MailboxConfig) => void;
}

/**
 * Channel navigation is deliberately its own component. It remains above the
 * detail area on desktop as well as narrow screens, so this does not recreate
 * the old left/right split settings layout.
 */
export function MailboxChannelList({
  isCreating,
  loading,
  mailboxes,
  selectedMailboxId,
  onCreate,
  onSelect,
}: MailboxChannelListProps) {
  return (
    <section className="panel" aria-label="收件通道">
      <div className="panel-heading">
        <div>
          <SemiTitle heading={3} style={{ margin: 0 }}>收件通道</SemiTitle>
          <SemiParagraph type="tertiary" style={{ margin: "4px 0 0" }}>每个通道独立保存首次入库范围与同步状态。</SemiParagraph>
        </div>
        <span className="tiny-badge">{mailboxes.length}</span>
      </div>
      {loading ? (
        <TableSkeleton />
      ) : mailboxes.length ? (
        <SemiList
          dataSource={mailboxes}
          renderItem={(item) => {
            const config = item as MailboxConfig;
            const selected = !isCreating && config.mailbox_id === selectedMailboxId;
            return (
              <SemiListItem
                extra={<MailboxStatusTag className={mailboxChannelStatusClass(config)}>{mailboxChannelStatus(config)}</MailboxStatusTag>}
                key={config.mailbox_id}
                main={
                  <button
                    aria-pressed={selected}
                    onClick={() => onSelect(config)}
                    style={{ display: "block", textAlign: "left", width: "100%", padding: 0, border: 0, background: "none", cursor: "pointer", color: "inherit", font: "inherit" }}
                    type="button"
                  >
                    <strong>{config.display_name}</strong>
                    <span style={{ display: "block", color: "var(--ink-muted)", fontSize: "0.8125rem" }}>
                      {mailboxProviderDisplayName(config)} · {mailboxAuthenticationModeLabel(config.authentication_mode)}
                    </span>
                    <span style={{ display: "block", fontSize: "0.875rem" }}>{config.email_address || "尚未配置收件邮箱"}</span>
                  </button>
                }
                style={
                  selected
                    ? { background: "var(--blue-tint)", border: "1px solid var(--blue)", borderRadius: "var(--radius-sm)" }
                    : undefined
                }
              />
            );
          }}
        />
      ) : (
        <SemiEmpty title="还没有收件通道" description="新建时可选择从现在开始，或回溯指定天数的简历附件。" />
      )}
      <BackofficeButton
        icon={<Icon name="plus" size={16} />}
        onClick={onCreate}
      >
        新建收件通道
      </BackofficeButton>
    </section>
  );
}
