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
  try {
    const result = await api.quickCapture(
      token,
      {
        uri: job.uri,
        name: job.filename || "screenshot.jpg",
        type: "image/jpeg",
      },
      "",
      job.mode,
    );
    cacheRecentResult(result);
    jobs = jobs.map((j) =>
      j.id === job.id
        ? {
            ...j,
            status: "ready" as const,
            result,
            chatId: result.chat_id,
            contact: result.contact,
          }
        : j,
    );
    unseenChats = new Set(unseenChats).add(result.chat_id);
    emitJobs();
    emitUnseen();
    refreshMe?.();
    firePushReady(result.contact || "your chat");
  } catch (e: any) {
    const detail = e instanceof ApiError ? e.detail : "request_failed";
    jobs = jobs.map((j) =>
      j.id === job.id
        ? { ...j, status: "error" as const, errorDetail: detail }
        : j,
    );
    emitJobs();
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
