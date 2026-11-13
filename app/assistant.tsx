"use client";

// The whole app: assistant-ui on the outside, Managed Agents underneath.
//
//   ManagedAgentsRuntimeProvider  — sessions are the thread list; the
//                                    active session's event log is the thread
//   ThreadListSidebar             — the session list (list/new/archive/delete)
//   Thread                        — the conversation, rendered from folded
//                                    events, with our per-tool cards and the
//                                    approval gate
//
// The toolkit and suggestions register through useAui, exactly as any
// assistant-ui app does; the only thing Managed-Agents-specific here is the
// runtime provider.

import { AuiProvider, Suggestions, Tools, useAui } from "@assistant-ui/react";
import { BookOpenIcon, FileSpreadsheetIcon } from "lucide-react";
import { AnalystSidebar } from "@/components/analyst-sidebar";
import { Thread } from "@/components/assistant-ui/thread";
import { SessionFiles } from "@/components/session-files";
import { ManagedAgentsToolFallback, toolkit } from "@/components/tool-uis";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { CONFERENCE } from "@/lib/conference-config";
import { ManagedAgentsRuntimeProvider, useActiveSessionSnapshot } from "@/lib/managed-agents/runtime-provider";

function Welcome() {
  return (
    <div className="aui-thread-welcome-root mb-6 flex flex-col items-center px-4 text-center">
      <h1 className="fade-in slide-in-from-bottom-1 animate-in fill-mode-both font-semibold text-2xl duration-200">
        Conference exhibitor desk
      </h1>
      <p className="fade-in slide-in-from-bottom-1 animate-in fill-mode-both mt-2 max-w-md text-muted-foreground text-sm delay-75 duration-200">
        Explore {CONFERENCE.partnerCount} partners, {CONFERENCE.sessionCount} agenda
        entries, {CONFERENCE.speakerRecordCount} speaker records, and sourced company
        capabilities.
      </p>
    </div>
  );
}

// A thin status strip: relay problems and the "connecting" state, plus the
// files that belong to the open session.
function SessionStatusBar() {
  const { sessionId, isTailing, isLoaded, transportError, lastError } = useActiveSessionSnapshot();
  if (!sessionId) return null;
  return (
    <div className="mx-auto flex w-full max-w-(--thread-max-width) flex-col gap-1 px-4 pt-2">
      <SessionFiles />
      <div className="flex flex-wrap items-center gap-2 px-1 text-muted-foreground text-xs">
        <span className="flex items-center gap-1.5">
          <FileSpreadsheetIcon className="size-3.5" />
          Directory loaded
        </span>
        <span className="text-border">/</span>
        <span className="flex items-center gap-1.5">
          <BookOpenIcon className="size-3.5" />
          {CONFERENCE.capabilityClaimCount} capability claims sourced
        </span>
      </div>
      {transportError && (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-1.5 text-red-700 text-xs dark:text-red-400">
          {transportError}
        </div>
      )}
      {lastError && lastError.retryStatus === "retrying" && (
        <div className="rounded-md bg-muted px-3 py-1.5 text-muted-foreground text-xs">
          Transient error, the session is retrying: {lastError.message}
        </div>
      )}
      {isLoaded && !isTailing && !transportError && (
        <div className="px-1 text-[11px] text-muted-foreground">reconnecting to session…</div>
      )}
    </div>
  );
}

function Workspace() {
  // Register our tool cards and starter prompts on the assistant client.
  const aui = useAui({
    tools: Tools({ toolkit }),
    suggestions: Suggestions([
      {
        title: "Map the exhibitor ecosystem",
        label: "partners, agenda, capabilities",
        prompt: "Summarize the conference dataset: how many unique companies, sessions, speaker records, and sourced capability claims are available? Identify the most common capability categories and the biggest coverage gaps.",
      },
      {
        title: "Compare flyer-backed companies",
        label: "products and capabilities",
        prompt: "Build a concise comparison table of the five companies with flyer evidence: company, main product focus, standout capabilities, and cited brochure pages.",
      },
      {
        title: "Find agenda coverage gaps",
        label: "speakers, partners, sessions",
        prompt: "Which partner companies also appear in the agenda, which have website capability evidence but no speaking session, and which tracks contain the most partner participation?",
      },
    ]),
  });

  return (
    <AuiProvider value={aui}>
      <SidebarProvider>
        <div className="flex h-dvh w-full pr-0.5">
          <AnalystSidebar />
          <SidebarInset>
            <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
              <SidebarTrigger />
              <span className="truncate text-muted-foreground text-sm">
                {CONFERENCE.name} · {CONFERENCE.date}
              </span>
              <a
                href="/api/conference/directory"
                download
                className="ml-auto flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs hover:bg-muted"
              >
                <FileSpreadsheetIcon className="size-3.5" />
                Directory
              </a>
            </header>
            <div className="flex flex-1 flex-col overflow-hidden" style={{ ["--thread-max-width" as string]: "44rem" }}>
              <SessionStatusBar />
              <div className="min-h-0 flex-1">
                <Thread components={{ Welcome, ToolFallback: ManagedAgentsToolFallback }} />
              </div>
            </div>
          </SidebarInset>
        </div>
      </SidebarProvider>
    </AuiProvider>
  );
}

export function Assistant() {
  return (
    <ManagedAgentsRuntimeProvider>
      <Workspace />
    </ManagedAgentsRuntimeProvider>
  );
}
