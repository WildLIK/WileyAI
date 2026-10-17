import type { ConversationState, Phase } from "./voice/conversation";

export interface Settings {
  name: string;
  grammatical_gender: "feminine" | "masculine" | "neutral";
  personality: string;
  provider: "ollama" | "compatible";
  base_url: string;
  model: string;
  profile: "eco" | "balanced" | "quality";
  context_tokens: number;
  response_tokens: number;
  temperature: number;
  stt_model: "tiny" | "base" | "small";
  tts_engine: "silero" | "silero_v5_6" | "piper" | "sapi" | "qwen3" | "cloud";
  tts_service: "openrouter" | "routerai" | "compatible";
  tts_base_url: string;
  tts_model: string;
  tts_cloud_voice: string;
  tts_format: "auto" | "mp3" | "pcm" | "wav";
  tts_style: string;
  tts_use_reference: boolean;
  tts_connections?: Partial<
    Record<Settings["tts_service"], Omit<CloudOptions, "tts_service">>
  >;
  tts_saved_voices?: SavedSpeechVoice[];
  openvoice_enabled: boolean;
  openvoice_voice: "mita" | "kind-mita" | "serena" | "custom";
  tts_device: "auto" | "cpu" | "cuda";
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
export type CloudOptions = Pick<
  Settings,
  | "tts_service"
  | "tts_base_url"
  | "tts_model"
  | "tts_cloud_voice"
  | "tts_format"
  | "tts_style"
  | "tts_use_reference"
>;
export type SpeechSettings = Pick<
  Settings,
  | "tts_engine"
  | "tts_voice"
  | "tts_device"
  | "speak_answers"
  | "openvoice_enabled"
  | "openvoice_voice"
> &
  CloudOptions;
export interface SavedSpeechVoice {
  id: string;
  name: string;
  voice: string;
  service: Settings["tts_service"];
  base_url: string;
  model: string;
}
export function cloudOptions(config: Settings): CloudOptions {
  return {
    tts_service: config.tts_service,
    tts_base_url: config.tts_base_url,
    tts_model: config.tts_model,
    tts_cloud_voice: config.tts_cloud_voice,
    tts_format: config.tts_format,
    tts_style: config.tts_style,
    tts_use_reference: config.tts_use_reference,
  };
}
export interface Message {
  id: string;
  role: string;
  content: string;
  created: string;
  memory_context?: { id: string; content: string; revision: number }[];
  web_search?: WebSearch;
  conversation_id?: string;
  document_context?: DocumentFragment[];
}
export interface DocumentFragment {
  document_id: string;
  name: string;
  offset: number;
  text: string;
  total: number;
}
export interface ReadingProgress {
  phase: "reading" | "reducing" | "answering";
  current: number;
  total: number;
  text: string;
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
  scope: "chat" | "project";
  project_id: string | null;
  preview?: string;
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
  voice?: string;
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
  silero_v5_6_installed: boolean;
  qwen3_available: boolean;
  qwen3_installed: boolean;
  qwen3_voices: { name: string; language: string }[];
  piper_available: boolean;
  piper_voices: { name: string; label: string; installed: boolean }[];
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
        : Array.isArray(error.detail) &&
            typeof error.detail[0]?.msg === "string"
          ? error.detail[0].msg.replace(/^Value error, /, "")
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
  device: Settings["tts_device"] = "auto",
  onDevice?: (device: "cpu" | "cuda") => void,
  session_id?: string,
  cloud?: CloudOptions,
  conversion?: Pick<Settings, "openvoice_enabled" | "openvoice_voice">,
): Promise<Blob> {
  signal.throwIfAborted();
  const request_id = crypto.randomUUID();
  const cancel = () => {
    void request("/voice/stop", "POST", { request_id }).catch(() => {});
  };
  signal.addEventListener("abort", cancel, { once: true });
  try {
    const response = await fetch(connection.url + "/voice/synthesize", {
      method: "POST",
      headers: {
        Authorization: "Bearer " + connection.token,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text,
        voice,
        engine,
        device,
        request_id,
        session_id,
        cloud,
        ...conversion,
      }),
      signal,
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Ошибка синтеза речи");
    }
    const actualDevice = response.headers.get("X-Wiley-TTS-Device");
    if (actualDevice === "cpu" || actualDevice === "cuda")
      onDevice?.(actualDevice);
    return await response.blob();
  } finally {
    signal.removeEventListener("abort", cancel);
  }
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
    phase?: ReadingProgress["phase"];
    current?: number;
    total?: number;
  }) => void,
  mode: "text" | "conversation" = "text",
  web_search = false,
  conversation_id?: string,
  full_document = false,
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
        full_document,
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
