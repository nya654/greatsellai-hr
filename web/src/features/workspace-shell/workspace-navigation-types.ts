export type WorkspaceNavigationView =
  | "library"
  | "filter"
  | "upload"
  | "score"
  | "match";

export type WorkspaceView = WorkspaceNavigationView | "settings";

export type WorkspaceSettingsSection = "mailbox" | "data";
