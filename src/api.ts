import type { ConversationState, Phase } from "./voice/conversation";

export interface Settings {
  name: string;
  personality: string;
  provider: "ollama" | "compatible";
  base_url: string;
  model: string;
  profile: "eco" | "balanced" | "quality";
  context_tokens: number;
  temperature: number;
  stt_model: "tiny" | "base" | "small";
  tts_engine: "silero" | "sapi";
  tts_voice: string;
  speak_answers: boolean;
  memory_suggestions: boolean;
  allow_file_open: boolean;
  allow_app_open: boolean;
  allow_web_open: boolean;
  command_understanding: boolean;
  search_enabled: boolean;
  search_provider: "searxng" | "brave";
  search_base_url: string;
  search_filter: "off" | "moderate" | "strict";
  audio_input_device_id: string;
  audio_output_device_id: string;
  conversation_silence_ms: number;
  conversation_threshold: number;
  avatar_path: string;
  has_api_key?: boolean;
  api_key?: string;
  has_search_api_key?: boolean;
  search_api_key?: string;
}
export interface Message {
  id: string;
  role: string;
  content: string;
  created: string;
  memory_context?: { id: string; content: string; revision: number }[];
  web_search?: WebSearch;
  conversation_id?: string;
}
export interface Chat {
  id: string;
  title: string;
  project_id: string | null;
  created: string;
  updated: string;
  messages: number;
}
export interface Project {
  id: string;
  name: string;
  chats: number;
}

export function scoped(route: string, conversationId: string) {
  return (
    route +
    (route.includes("?") ? "&" : "?") +
    "conversation_id=" +
    encodeURIComponent(conversationId)
  );
}
export function scopedRequest(conversationId: string) {
  return <T = unknown>(
    route: string,
    method = "GET",
    body?: unknown,
    signal?: AbortSignal,
  ) => request<T>(scoped(route, conversationId), method, body, signal);
}
export interface WebSearch {
  query: string;
  provider: string;
  checked_at: string;
  partial: boolean;
  results: { title: string; url: string; snippet: string }[];
}
export interface Memory {
  id: string;
  content: string;
  created: string;
  category: "fact" | "preference" | "profile";
  pinned: number;
  updated: string;
  revision: number;
  source_text: string | null;
}
export interface MemoryCandidate {
  id: string;
  content: string;
  category: Memory["category"];
  source_text: string;
  created: string;
}
export interface Doc {
  id: string;
  name: string;
  characters: number;
}
export interface Job {
  id: string;
  model: string;
  status: string;
  detail: string;
  total: number;
  completed: number;
}
export interface CatalogItem {
  id: string;
  name: string;
  kind: string;
  engine: string;
  description: string;
  size: string;
  languages: string;
  source: string;
  license: string;
}
export interface Alias {
  id: string;
  name: string;
  kind: string;
  target: string;
}
export interface VoiceInfo {
  available: boolean;
  voices: { name: string; language: string }[];
  installed_stt: string[];
  tts_available: boolean;
  silero_installed: boolean;
}
export interface BackupPreview {
  ticket: string;
  filename: string;
  created: string;
  counts: Record<string, number>;
  current_counts: Record<string, number>;
  pending_suggestions: number;
  current_pending_suggestions: number;
  name: string;
  provider: string;
  model: string;
  base_url: string;
}
declare global {
  interface Window {
    wiley: {
      connection(): Promise<{ url: string; token: string }>;
      showWindow(view: string): Promise<void>;
      pickFile(kind: string): Promise<string | null>;
      avatarBytes(): Promise<Uint8Array | null>;
      clickThrough(enabled: boolean): Promise<void>;
      quit(): Promise<void>;
      exportBackup(): Promise<{ path: string; bytes: number } | null>;
      previewBackup(): Promise<BackupPreview | null>;
      restoreBackup(options: {
        ticket: string;
        connections: boolean;
        aliases: boolean;
      }): Promise<{ recovery_path: string }>;
      onDataRestored(callback: () => void): () => void;
      conversationState(): Promise<ConversationState>;
      acquireConversation(): Promise<string>;
      updateConversation(id: string, phase: Phase): Promise<void>;
      releaseConversation(id: string): Promise<void>;
      stopConversation(): Promise<void>;
      onConversation(callback: (state: ConversationState) => void): () => void;
      onStop(callback: () => void): () => void;
      onReminder(callback: (title: string) => void): () => void;
      onOffline(callback: () => void): () => void;
    };
  }
}
let connection: { url: string; token: string };
export async function init() {
  if (!window.wiley)
    throw new Error("Откройте WileyAI через npm run dev или npm start");
  connection = await window.wiley.connection();
}
export async function request<T = unknown>(
  route: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const multipart = body instanceof FormData;
  const response = await fetch(connection.url + route, {
    method,
    headers: {
      Authorization: "Bearer " + connection.token,
      ...(!multipart && body !== undefined
        ? { "Content-Type": "application/json" }
        : {}),
    },
    body:
      body === undefined ? undefined : multipart ? body : JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "Проверьте введённые параметры",
    );
  }
  return response.json();
}
export async function audioRequest(
  text: string,
  voice: string,
  signal: AbortSignal,
  engine: Settings["tts_engine"] = "silero",
): Promise<Blob> {
  const response = await fetch(connection.url + "/voice/synthesize", {
    method: "POST",
    headers: {
      Authorization: "Bearer " + connection.token,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text, voice, engine }),
    signal,
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Ошибка синтеза речи");
  }
  return response.blob();
}
export async function stream(
  text: string,
  document_ids: string[],
  signal: AbortSignal,
  onEvent: (event: {
    type: string;
    text?: string;
    message?: Message;
    seconds?: number;
    changed?: string[];
  }) => void,
  mode: "text" | "conversation" = "text",
  web_search = false,
  conversation_id?: string,
) {
  const request_id = crypto.randomUUID();
  let stopping: Promise<unknown> | undefined;
  const cancel = () => {
    stopping = request("/chat/stop", "POST", { request_id }).catch(() => {});
  };
  signal.addEventListener("abort", cancel, { once: true });
  try {
    const response = await fetch(connection.url + "/chat", {
      method: "POST",
      headers: {
        Authorization: "Bearer " + connection.token,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text,
        document_ids,
        mode,
        web_search,
        request_id,
        conversation_id,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }),
      signal,
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Не удалось отправить сообщение");
    }
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let pending = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      const parts = pending.split("\n\n");
      pending = parts.pop() || "";
      for (const part of parts)
        if (part.startsWith("data: ")) onEvent(JSON.parse(part.slice(6)));
    }
  } finally {
    signal.removeEventListener("abort", cancel);
    await stopping;
  }
}
