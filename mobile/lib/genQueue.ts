// Global generation queue.
//
// Goals:
//   • Lift "is a quick-capture in flight?" out of the Home screen's
//     local state so it survives navigation. Switching to chats list
//     mid-generation must NOT cancel the request.
//   • Allow multiple concurrent generations (queue another while the
//     first is still running).
//   • Surface activity on every screen via a persistent dock chip.
//   • Track which chats have completed-but-unseen replies so we can
//     paint a green dot in chat lists / on the back button.
//
// Implementation: module-level store + pub/sub. No Context — works
// from any screen including ones not children of a provider.

import { useEffect, useState } from "react";
import { api, ApiError, GenerationMode, QuickCaptureResult } from "./api";
import { cacheRecentResult } from "./recentResult";
import { openPaywall } from "./paywallStore";
import { firePushReady } from "./pushNotify";

export type Job = {
  id: string; // local uuid
  uri: string;
  filename?: string | null;
  screenshotId?: string | null;
  mode: GenerationMode;
  status: "running" | "ready" | "error";
  startedAt: number;
  // Populated when status === 'ready'
  result?: QuickCaptureResult;
  contact?: string;
  chatId?: string;
  // Populated when status === 'error'
  errorDetail?: string;
};

let jobs: Job[] = [];
const jobListeners = new Set<(jobs: Job[]) => void>();

// Chat IDs whose replies have completed but the user hasn't opened
// the detail screen yet. Cleared when chat detail mounts for that id.
let unseenChats = new Set<string>();
const unseenListeners = new Set<(set: Set<string>) => void>();

function emitJobs() {
  jobListeners.forEach((fn) => fn(jobs));
}

function emitUnseen() {
  unseenListeners.forEach((fn) => fn(new Set(unseenChats)));
}

function uuid(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

/* ───────────── Mutators ───────────── */

export function enqueueJob(input: {
  token: string;
  uri: string;
  filename?: string | null;
  screenshotId?: string | null;
  mode?: GenerationMode;
  refreshMe?: () => void;
}): Job {
  // Dedup guard. If the same screenshot is already in-flight (queued
  // or running) we return the existing job rather than fan out into
  // multiple parallel uploads. This was triggering when a user took a
  // screenshot in another app and returned to Muzo — both AppState
  // 'active' and useFocusEffect would fire scan(true) close together,
  // and although we have a scanInFlight ref, occasional timing
  // variance let two enqueueJob calls slip through with the same
  // MediaLibrary asset id. Catching it here is robust regardless.
  if (input.screenshotId) {
    const existing = jobs.find(
      (j) =>
        j.screenshotId === input.screenshotId &&
        (j.status === "queued" || j.status === "running"),
    );
    if (existing) return existing;
  }
  // Also dedup against same URI within the last 2s — covers the
  // manual-pick path where there's no MediaLibrary id but the same
  // file URI gets passed twice in quick succession.
  if (!input.screenshotId) {
    const recent = jobs.find(
      (j) =>
        j.uri === input.uri &&
        (j.status === "queued" || j.status === "running") &&
        Date.now() - j.startedAt < 2000,
    );
    if (recent) return recent;
  }

  const job: Job = {
    id: uuid(),
    uri: input.uri,
    filename: input.filename,
    screenshotId: input.screenshotId,
    mode: input.mode || "fast",
    status: "running",
    startedAt: Date.now(),
  };
  jobs = [job, ...jobs];
  emitJobs();
  // Fire-and-forget: the job runs in the background even if every
  // screen unmounts.
  void runJob(input.token, job, input.refreshMe);
  return job;
}

async function runJob(token: string, job: Job, refreshMe?: () => void) {
  // ── Step 1: upload — fast, completes before any backgrounding kills JS.
  let serverJobId: string;
  try {
    const r = await api.quickCaptureUpload(
      token,
      {
        uri: job.uri,
        name: job.filename || "screenshot.jpg",
        type: "image/jpeg",
      },
      "",
      job.mode,
    );
    serverJobId = r.job_id;
  } catch (e: any) {
    const detail = e instanceof ApiError ? e.detail : "request_failed";
    if (
      detail === "pro_locked_free" ||
      detail === "daily_cap_free" ||
      detail === "lifetime_trial_exhausted" ||
      detail === "daily_cap_paid_pro"
    ) {
      openPaywall(detail as any);
    }
    jobs = jobs.map((j) =>
      j.id === job.id
        ? { ...j, status: "error" as const, errorDetail: detail }
        : j,
    );
    emitJobs();
    return;
  }

  // ── Step 2: poll the server until the job is ready / errored.
  // The HTTP request is short-lived (~200ms each) so it survives
  // background → foreground transitions cleanly. If the JS bridge IS
  // suspended, the next poll on resume picks up where we left off.
  // The server-fired push notification is the secondary trigger:
  // even if polling falls behind, the user already got the bing.
  const startedAt = job.startedAt;
  const POLL_MS = 1500;
  const MAX_S = 90;
  while (true) {
    if (Date.now() - startedAt > MAX_S * 1000) {
      jobs = jobs.map((j) =>
        j.id === job.id
          ? { ...j, status: "error" as const, errorDetail: "timeout" }
          : j,
      );
      emitJobs();
      return;
    }
    await new Promise((res) => setTimeout(res, POLL_MS));
    let snapshot;
    try {
      snapshot = await api.getJob(token, serverJobId);
    } catch (e: any) {
      // Transient — keep polling. Real failures will surface on the
      // next poll or via the timeout above.
      continue;
    }

    if (snapshot.status === "ready" && snapshot.result) {
      cacheRecentResult(snapshot.result);
      jobs = jobs.map((j) =>
        j.id === job.id
          ? {
              ...j,
              status: "ready" as const,
              result: snapshot.result,
              chatId: snapshot.result!.chat_id,
              contact: snapshot.result!.contact,
            }
          : j,
      );
      unseenChats = new Set(unseenChats).add(snapshot.result.chat_id);
      emitJobs();
      emitUnseen();
      refreshMe?.();
      // Fallback in-app trigger when the server's push didn't reach
      // (rare, but safer to fire both).
      firePushReady(snapshot.result.contact || "your chat");
      return;
    }
    if (snapshot.status === "error") {
      const detail = snapshot.error_detail || "request_failed";
      if (
        detail === "pro_locked_free" ||
        detail === "daily_cap_free" ||
        detail === "lifetime_trial_exhausted" ||
        detail === "daily_cap_paid_pro"
      ) {
        openPaywall(detail as any);
      }
      jobs = jobs.map((j) =>
        j.id === job.id
          ? { ...j, status: "error" as const, errorDetail: detail }
          : j,
      );
      emitJobs();
      return;
    }
    // queued or running → keep polling
  }
}

/** Remove a job (e.g. after the user opens its chat or dismisses it). */
export function clearJob(id: string) {
  jobs = jobs.filter((j) => j.id !== id);
  emitJobs();
}

/** Remove every "ready" or "error" job — leaves running ones alone. */
export function clearFinished() {
  jobs = jobs.filter((j) => j.status === "running");
  emitJobs();
}

/** Mark a chat's replies as seen — clears the dot indicator. */
export function markChatSeen(chatId: string) {
  if (unseenChats.has(chatId)) {
    unseenChats = new Set(unseenChats);
    unseenChats.delete(chatId);
    emitUnseen();
  }
}

/* ───────────── Hooks ───────────── */

export function useJobs(): Job[] {
  const [snap, setSnap] = useState(jobs);
  useEffect(() => {
    const fn = (j: Job[]) => setSnap(j);
    jobListeners.add(fn);
    setSnap(jobs); // sync to current
    return () => {
      jobListeners.delete(fn);
    };
  }, []);
  return snap;
}

export function useRunningCount(): number {
  return useJobs().filter((j) => j.status === "running").length;
}

export function useReadyJobs(): Job[] {
  return useJobs().filter((j) => j.status === "ready");
}

export function useUnseenChats(): Set<string> {
  const [snap, setSnap] = useState(unseenChats);
  useEffect(() => {
    const fn = (s: Set<string>) => setSnap(s);
    unseenListeners.add(fn);
    setSnap(new Set(unseenChats));
    return () => {
      unseenListeners.delete(fn);
    };
  }, []);
  return snap;
}

export function useHasUnseen(): boolean {
  return useUnseenChats().size > 0;
}
