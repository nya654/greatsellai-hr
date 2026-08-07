import { lazy } from "react";
import type { MailboxProvider } from "../../../types";
import { TableSkeleton } from "../../../backoffice/ui/TableSkeleton";

const SemiRadioGroup = lazy(() => import("@douyinfe/semi-ui-19/lib/es/radio/radioGroup"));
const SemiRadio = lazy(() => import("@douyinfe/semi-ui-19/lib/es/radio"));

interface MailboxProviderPickerProps {
  disabled?: boolean;
  loading: boolean;
  onChange: (provider: MailboxProvider) => void;
  providers: MailboxProvider[];
  value: string;
}

function authenticationLabel(provider: MailboxProvider): string {
  if (provider.allows_custom_endpoint) return "服务器域名 + 授权码";
  return provider.authentication_mode === "oauth2" ? "网页授权" : "专用授权码";
}

/**
 * New channels select a reviewed provider. The generic IMAP option remains a
 * reviewed provider too, while the server validates any hostname separately.
 */
export function MailboxProviderPicker({
  disabled = false,
  loading,
  onChange,
  providers,
  value,
}: MailboxProviderPickerProps) {
  if (loading) {
    return <TableSkeleton />;
  }

  if (!providers.length) {
    return (
      <p role="alert" style={{ color: "var(--red)", fontSize: "0.875rem" }}>
        暂时无法读取可接入的邮箱服务商，请刷新后重试。
      </p>
    );
  }

  return (
    <SemiRadioGroup
      aria-label="邮箱服务商"
      name="mailbox-provider"
      onChange={(event) => {
        const provider = providers.find((item) => item.provider_key === event.target.value);
        if (provider) onChange(provider);
      }}
      type="card"
      value={value}
    >
      {providers.map((provider) => {
        const unavailable = !provider.available;
        return (
          <SemiRadio
            disabled={disabled || unavailable}
            extra={
              <span style={{ display: "block", color: "var(--ink-muted)", fontSize: "0.75rem", lineHeight: 1.4 }}>
                {unavailable ? "当前部署尚未启用该服务商。" : provider.help_text}
              </span>
            }
            key={provider.provider_key}
            value={provider.provider_key}
          >
            <strong>{provider.display_name}</strong>
            <small style={{ display: "block", color: "var(--ink-muted)", fontWeight: 400, fontSize: "0.8125rem" }}>
              {authenticationLabel(provider)}
            </small>
          </SemiRadio>
        );
      })}
    </SemiRadioGroup>
  );
}
