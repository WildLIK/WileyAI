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
  avatar_path: string;
  has_api_key?: boolean;
  api_key?: string;
}
export interface Message {
  id: string;
  role: string;
  content: string;
  created: string;
}
export interface Memory {
  id: string;
  content: string;
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
declare global {
  interface Window {
    wiley: {
      connection(): Promise<{ url: string; token: string }>;
      showWindow(view: string): Promise<void>;
      pickFile(kind: string): Promise<string | null>;
      avatarBytes(): Promise<Uint8Array | null>;
      clickThrough(enabled: boolean): Promise<void>;
      quit(): Promise<void>;
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
): Promise<Blob> {
  const response = await fetch(connection.url + "/voice/synthesize", {
    method: "POST",
    headers: {
      Authorization: "Bearer " + connection.token,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text, voice }),
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
  }) => void,
) {
  const response = await fetch(connection.url + "/chat", {
    method: "POST",
    headers: {
      Authorization: "Bearer " + connection.token,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text, document_ids }),
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
}
