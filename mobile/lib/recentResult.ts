// In-memory cache for the most recent quick-capture result.
// Lets the chat detail screen render the freshly-generated replies
// instantly (no API round trip), then falls back to GET /chats/{id}
// for any older chat the user opens via the list.

import { QuickCaptureResult } from "./api";

type CachedDetail = {
  id: string;
  contact: string;
  messages: { speaker: "me" | "them"; text: string }[];
  replies: { label: string; text: string; why?: string }[];
  read?: string;
  advice?: string;
  cachedAt: number;
};

let cached: CachedDetail | null = null;

export function cacheRecentResult(r: QuickCaptureResult) {
  cached = {
    id: r.chat_id,
    contact: r.contact,
    messages: r.transcript,
    replies: r.replies,
    read: r.read,
    advice: r.advice,
    cachedAt: Date.now(),
  };
}

export function takeCachedResult(chatId: string): CachedDetail | null {
  if (cached && cached.id === chatId && Date.now() - cached.cachedAt < 5 * 60_000) {
    return cached;
  }
  return null;
}

export function clearCachedResult() {
  cached = null;
}
