import { useCallback, useEffect, useState } from "react";
import type {
  WorkspaceNavigationView,
  WorkspaceSettingsSection,
  WorkspaceView,
} from "./workspace-navigation-types";

export type {
  WorkspaceNavigationView,
  WorkspaceSettingsSection,
  WorkspaceView,
} from "./workspace-navigation-types";

function settingsSectionFromHash(
  hash: string,
): WorkspaceSettingsSection | null {
  const value = hash
    .replace(/^#/, "")
    .trim()
    .replace(/^\/+|\/+$/g, "")
    .toLowerCase();

  if (value === "settings/mailbox" || value === "inbox") return "mailbox";
  if (value === "settings/data" || value === "data") return "data";
  return null;
}

function settingsHash(section: WorkspaceSettingsSection): string {
  return `#settings/${section}`;
}

function feedbackHash(): string {
  return "#feedback";
}

function navigationViewFromHash(hash: string): WorkspaceNavigationView | null {
  const value = hash
    .replace(/^#/, "")
    .trim()
    .replace(/^\/+|\/+$/g, "")
    .toLowerCase();

  return value === "favorites" ? "favorites" : null;
}

interface UseWorkspaceNavigationOptions {
  canManageCandidateData: boolean;
  canManageMailbox: boolean;
  hasSession: boolean;
}

/**
 * Keeps the workspace route, settings tab and browser hash in one place.
 * Permission decisions stay server-owned; this controller only redirects a
 * person away from a settings section that their current session cannot use.
 */
export function useWorkspaceNavigation({
  canManageCandidateData,
  canManageMailbox,
  hasSession,
}: UseWorkspaceNavigationOptions) {
  const [view, setView] = useState<WorkspaceView>(() =>
    navigationViewFromHash(window.location.hash) ??
    (window.location.hash.replace(/^#/, "").trim().toLowerCase() === "feedback"
      ? "feedback"
      : settingsSectionFromHash(window.location.hash)
        ? "settings"
        : "library"),
  );
  const [settingsSection, setSettingsSection] =
    useState<WorkspaceSettingsSection>(
      () => settingsSectionFromHash(window.location.hash) ?? "mailbox",
    );
  const canManageSettings = canManageMailbox || canManageCandidateData;

  const updateHash = useCallback(
    (nextHash: string, replace = false) => {
      if (window.location.hash === nextHash) return;
      const nextLocation = `${window.location.pathname}${window.location.search}${nextHash}`;
      if (replace) {
        window.history.replaceState(window.history.state, "", nextLocation);
      } else {
        window.history.pushState(window.history.state, "", nextLocation);
      }
    },
    [],
  );

  const updateSettingsHash = useCallback(
    (section: WorkspaceSettingsSection | null, replace = false) => {
      updateHash(section ? settingsHash(section) : "", replace);
    },
    [updateHash],
  );

  const navigateToView = useCallback(
    (nextView: WorkspaceNavigationView) => {
      setView(nextView);
      // Favorites is a personal worklist with a useful direct URL. Other
      // primary workspace views keep the existing clean root URL.
      updateHash(nextView === "favorites" ? "#favorites" : "");
    },
    [updateHash],
  );

  const openSettings = useCallback(
    (section: WorkspaceSettingsSection) => {
      setSettingsSection(section);
      setView("settings");
      updateSettingsHash(section);
    },
    [updateSettingsHash],
  );

  const openFeedback = useCallback(() => {
    setView("feedback");
    const nextHash = feedbackHash();
    if (window.location.hash === nextHash) return;
    window.history.pushState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}${nextHash}`,
    );
  }, []);

  useEffect(() => {
    const syncSettingsFromHash = () => {
      const navigationView = navigationViewFromHash(window.location.hash);
      if (navigationView) {
        setView(navigationView);
        return;
      }
      if (window.location.hash.replace(/^#/, "").trim().toLowerCase() === "feedback") {
        setView("feedback");
        return;
      }
      const section = settingsSectionFromHash(window.location.hash);
      if (!section) {
        // A browser Back action from a hash-routed view returns to the clean
        // workspace URL, whose canonical screen is the resume library.
        setView((current) =>
          current === "settings" || current === "favorites" || current === "feedback"
            ? "library"
            : current,
        );
        return;
      }
      setSettingsSection(section);
      setView("settings");
      updateSettingsHash(section, true);
    };

    syncSettingsFromHash();
    window.addEventListener("hashchange", syncSettingsFromHash);
    window.addEventListener("popstate", syncSettingsFromHash);
    return () => {
      window.removeEventListener("hashchange", syncSettingsFromHash);
      window.removeEventListener("popstate", syncSettingsFromHash);
    };
  }, [updateSettingsHash]);

  useEffect(() => {
    if (!hasSession || view !== "settings") return;
    const sectionAllowed =
      (settingsSection === "mailbox" && canManageMailbox) ||
      (settingsSection === "data" && canManageCandidateData);
    if (sectionAllowed) return;

    const fallbackSection = canManageMailbox
      ? "mailbox"
      : canManageCandidateData
        ? "data"
        : null;
    if (!fallbackSection) {
      setView("library");
      updateSettingsHash(null, true);
      return;
    }
    setSettingsSection(fallbackSection);
    updateSettingsHash(fallbackSection, true);
  }, [
    canManageCandidateData,
    canManageMailbox,
    hasSession,
    settingsSection,
    updateSettingsHash,
    view,
  ]);

  return {
    canManageSettings,
    navigateToView,
    openFeedback,
    openSettings,
    settingsSection,
    view,
  };
}
