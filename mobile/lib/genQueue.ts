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

export type JobKind = "capture" | "regenerate";

export type Job = {
  id: string; // local uuid
  kind: JobKind;
  // Capture-only
  uri?: string;
  filename?: string | null;
  screenshotId?: string | null;
  // Regenerate-only
  regenChatId?: string;
  regenContact?: string; // pre-known contact name for nicer chip
  // Both
  mode: GenerationMode;
  status: "running" | "ready" | "error";
  startedAt: number;
  result?: QuickCaptureResult;
  contact?: string;
  chatId?: string;
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
  const job: Job = {
    id: uuid(),
    kind: "capture",
    uri: input.uri,
    filename: input.filename,
    screenshotId: input.screenshotId,
    mode: input.mode || "fast",
    status: "running",
    startedAt: Date.now(),
  };
  jobs = [job, ...jobs];
  emitJobs();
  void runJob(input.token, job, input.refreshMe);
  return job;
}

/** Enqueue a regenerate-existing-chat job. Same lifecycle as capture
 *  jobs (dock chip, push, polling) — just no screenshot upload. */
export function enqueueRegenerate(input: {
  token: string;
  chatId: string;
  contact?: string;
  extraContext?: string;
  mode?: GenerationMode;
  refreshMe?: () => void;
}): Job {
  const job: Job = {
    id: uuid(),
    kind: "regenerate",
    regenChatId: input.chatId,
    regenContact: input.contact,
    mode: input.mode || "fast",
    status: "running",
    startedAt: Date.now(),
    contact: input.contact,
    chatId: input.chatId,
  };
  jobs = [job, ...jobs];
  emitJobs();
  void runRegenJob(input.token, job, input.extraContext || "", input.refreshMe);
  return job;
}

async function runJob(token: string, job: Job, refreshMe?: () => void) {
  // ── Step 1: upload — fast, completes before any backgrounding kills JS.
  let serverJobId: string;
  try {
    const r = await api.quickCaptureUpload(
      token,
      {
        uri: job.uri || "",
        name: job.filename || "screenshot.jpg",
        type: "image/jpeg",
      },
      "",
      job.mode,
    );
    serverJobId = r.job_id;
  } catch (e: any) {
    handleJobError(job.id, e);
    return;
  }
  await pollServerJob(token, job.id, serverJobId, refreshMe);
}

async function runRegenJob(
  token: string,
  job: Job,
  extraContext: string,
  refreshMe?: () => void,
) {
  if (!job.regenChatId) {
    handleJobError(job.id, new ApiError(0, "missing_chat_id"));
    return;
  }
  let serverJobId: string;
  try {
    const r = await api.regenerateUpload(
      token,
      job.regenChatId,
      extraContext,
      job.mode,
    );
    serverJobId = r.job_id;
  } catch (e: any) {
    handleJobError(job.id, e);
    return;
  }
  await pollServerJob(token, job.id, serverJobId, refreshMe);
}

/** Shared 1.5s polling loop. Same poll behavior whether we're waiting
 *  on a capture or a regenerate — the server's job table is unified. */
async function pollServerJob(
  token: string,
  localJobId: string,
  serverJobId: string,
  refreshMe?: () => void,
) {
  const POLL_MS = 1500;
  const MAX_S = 90;
  const startedAt = Date.now();
  while (true) {
    if (Date.now() - startedAt > MAX_S * 1000) {
      jobs = jobs.map((j) =>
        j.id === localJobId
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
    } catch {
      continue;
    }
    if (snapshot.status === "ready" && snapshot.result) {
      cacheRecentResult(snapshot.result);
      jobs = jobs.map((j) =>
        j.id === localJobId
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
      firePushReady(snapshot.result.contact || "your chat");
      return;
    }
    if (snapshot.status === "error") {
      const detail = snapshot.error_detail || "request_failed";
      if (
        detail === "pro_locked_free" ||
        detail === "daily_cap_free" ||
        detail === "lifetime_trial_exhausted"
      ) {
        openPaywall(detail);
      }
      jobs = jobs.map((j) =>
        j.id === localJobId
          ? { ...j, status: "error" as const, errorDetail: detail }
          : j,
      );
      emitJobs();
      return;
    }
  }
}

function handleJobError(localJobId: string, e: any) {
  const detail = e instanceof ApiError ? e.detail : "request_failed";
  if (
    detail === "pro_locked_free" ||
    detail === "daily_cap_free" ||
    detail === "lifetime_trial_exhausted"
  ) {
    openPaywall(detail);
  }
  jobs = jobs.map((j) =>
    j.id === localJobId
      ? { ...j, status: "error" as const, errorDetail: detail }
      : j,
  );
  emitJobs();
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

/** Returns the most recent "ready" or "running" regenerate job for
 *  a given chat. Used by the chat detail screen to:
 *    - hide the static "Regenerate replies" button while a regen is
 *      in flight (the dock chip becomes the loading indicator)
 *    - auto-refresh its own data when a regen finishes for this chat
 */
export function useLatestJobForChat(chatId: string | undefined): Job | null {
  const all = useJobs();
  if (!chatId) return null;
  // Newest first (jobs array is unshifted on enqueue).
  for (const j of all) {
    if (j.chatId === chatId || j.regenChatId === chatId) {
      return j;
    }
  }
  return null;
}
