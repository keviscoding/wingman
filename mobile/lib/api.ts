// Thin REST client for the Wingman SaaS API. Auth header is injected
// from the AuthContext when present. Errors throw with the server-side
// `detail` string, so screens can render them directly.

import { API_URL } from "./config";

export type ReplyOption = {
  label: string;
  text: string;
  why?: string;
};

export type QuickCaptureResult = {
  chat_id: string;
  contact: string;
  transcript: { speaker: "me" | "them"; text: string }[];
  replies: ReplyOption[];
  read?: string;
  advice?: string;
  generated_at: number;
  model: string;
};

export type ChatSummary = {
  id: string;
  contact: string;
  msg_count: number;
  last_text: string;
  last_speaker: string;
  last_activity_at: number;
  has_replies: boolean;
};

export type Me = {
  user_id: string;
  email: string;
  display_name: string | null;
  plan: string;
  is_subscribed: boolean;
  subscription_until: number | null;
  lifetime_used: number;
  daily_used: number;
  pro_lifetime_used: number;
  pro_daily_used: number;
  free_lifetime_trial: number;
  free_pro_lifetime_trial: number;
  free_daily_limit: number;
  paid_daily_limit: number;
};

export type GenerationMode = "fast" | "pro";

export type AuthResponse = {
  token: string;
  expires_at: number;
  user_id: string;
  email: string;
  plan: string;
};

class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  options: RequestInit & { token?: string | null } = {},
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };
  if (options.token) headers.Authorization = `Bearer ${options.token}`;
  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers["Content-Type"]
  ) {
    headers["Content-Type"] = "application/json";
  }

  let resp: Response;
  try {
    resp = await fetch(`${API_URL}${path}`, { ...options, headers });
  } catch (err: any) {
    throw new ApiError(0, `network: ${err?.message || err}`);
  }

  let body: any = null;
  const ct = resp.headers.get("content-type") || "";
  try {
    body = ct.includes("application/json") ? await resp.json() : await resp.text();
  } catch {
    /* ignore */
  }

  if (!resp.ok) {
    const detail =
      (body && typeof body === "object" && body.detail) ||
      (typeof body === "string" && body) ||
      "request_failed";
    throw new ApiError(resp.status, String(detail));
  }
  return body as T;
}

export const api = {
  async signup(
    email: string,
    password: string,
    display_name?: string,
  ): Promise<AuthResponse> {
    return request<AuthResponse>("/api/v1/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name }),
    });
  },

  async login(email: string, password: string): Promise<AuthResponse> {
    return request<AuthResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  async me(token: string): Promise<Me> {
    return request<Me>("/api/v1/me", { token });
  },

  async listChats(token: string): Promise<{ chats: ChatSummary[] }> {
    return request<{ chats: ChatSummary[] }>("/api/v1/chats", { token });
  },

  async getChat(token: string, id: string): Promise<any> {
    return request<any>(`/api/v1/chats/${encodeURIComponent(id)}`, { token });
  },

  async deleteChat(token: string, id: string): Promise<void> {
    await request(`/api/v1/chats/${encodeURIComponent(id)}`, {
      method: "DELETE",
      token,
    });
  },

  async regenerate(
    token: string,
    id: string,
    extra_context = "",
    mode: GenerationMode = "fast",
  ): Promise<any> {
    return request<any>(
      `/api/v1/chats/${encodeURIComponent(id)}/regenerate`,
      {
        method: "POST",
        token,
        body: JSON.stringify({ extra_context, mode }),
      },
    );
  },

  async quickCapture(
    token: string,
    image: { uri: string; name?: string; type?: string },
    extra_context = "",
    mode: GenerationMode = "fast",
  ): Promise<QuickCaptureResult> {
    const form = new FormData();
    form.append("screenshot", {
      uri: image.uri,
      name: image.name || "screenshot.jpg",
      type: image.type || "image/jpeg",
    } as any);
    form.append("extra_context", extra_context);
    form.append("mode", mode);
    return request<QuickCaptureResult>("/api/v1/quick-capture", {
      method: "POST",
      token,
      body: form,
    });
  },

  async copyReply(
    token: string,
    chat_id: string,
    label: string,
    text: string,
  ): Promise<void> {
    await request(`/api/v1/replies/${encodeURIComponent(chat_id)}/copy`, {
      method: "POST",
      token,
      body: JSON.stringify({ label, text }),
    });
  },
};

export { ApiError };
