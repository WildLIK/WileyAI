import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  request,
  audioRequest,
  stream,
  type Settings,
  type Message,
  type Memory,
  type Doc,
  type Job,
  type CatalogItem,
  type Alias,
  type VoiceInfo,
} from "./api";
import { Productivity, Capabilities } from "./Productivity";

const tabs = [
  { id: "chat", icon: "◈", label: "Общение" },
  { id: "models", icon: "⬡", label: "Модели" },
  { id: "tasks", icon: "◷", label: "Задачи" },
  { id: "notes", icon: "▤", label: "Заметки" },
  { id: "memory", icon: "◎", label: "Память" },
  { id: "commands", icon: "⌘", label: "Команды" },
  { id: "capabilities", icon: "✳", label: "Возможности" },
  { id: "settings", icon: "⚙", label: "Настройки" },
];
const stamp = (value: string) =>
  new Date(value).toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });
const ModelAvatar = lazy(() =>
  import("./Avatar").then((module) => ({ default: module.Avatar })),
);
function Avatar({ path, speaking }: { path: string; speaking?: boolean }) {
  if (!path)
    return (
      <div className="avatar-stage">
        <div className="avatar-placeholder">
          <div className={"orb " + (speaking ? "speaking" : "")}>
            <span>W</span>
          </div>
          <span>
            Загрузите свой VRM-аватар
            <br />в настройках персонажа
          </span>
        </div>
      </div>
    );
  return (
    <Suspense
      fallback={
        <div className="avatar-stage avatar-placeholder">
          Загружаю 3D-компонент…
        </div>
      }
    >
      <ModelAvatar path={path} speaking={speaking} />
    </Suspense>
  );
}

export function App() {
  const view = new URLSearchParams(location.search).get("view") || "chat";
  const [tab, setTab] = useState(view === "settings" ? "settings" : "chat");
  const [settings, setSettings] = useState<Settings>();
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [documents, setDocuments] = useState<Doc[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [memoryDraft, setMemoryDraft] = useState("");
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [modelCategory, setModelCategory] = useState("llm");
  const [installed, setInstalled] = useState<{ id: string; size: number }[]>(
    [],
  );
  const [jobs, setJobs] = useState<Job[]>([]);
  const [aliasList, setAliasList] = useState<Alias[]>([]);
  const [alias, setAlias] = useState({ name: "", kind: "folder", target: "" });
  const [voice, setVoice] = useState<VoiceInfo>({
    available: false,
    voices: [],
    installed_stt: [],
    tts_available: false,
    silero_installed: false,
  });
  const [recording, setRecording] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [voiceDownloading, setVoiceDownloading] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [customModel, setCustomModel] = useState("");
  const [keyTouched, setKeyTouched] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const audioStream = useRef<MediaStream | null>(null);
  const speechAbort = useRef<AbortController | null>(null);
  const playback = useRef<{
    audio: HTMLAudioElement;
    finish: () => void;
  } | null>(null);
  const speechGeneration = useRef(0);
  const listEnd = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const upload = useRef<HTMLInputElement>(null);
  const channel = useRef<BroadcastChannel | null>(null);

  const fail = (error: unknown) => {
    if (error instanceof DOMException && error.name === "AbortError") return;
    setError(
      error instanceof Error ? error.message : "Не удалось выполнить действие",
    );
  };
  const run = async (action: () => Promise<void>) => {
    setError("");
    try {
      await action();
    } catch (error) {
      fail(error);
    }
  };
  const refreshModels = useCallback(async () => {
    const data = await request<{
      connected: boolean;
      installed: { id: string; size: number }[];
      error?: string;
    }>("/models");
    setConnected(data.connected);
    setInstalled(data.installed);
    return data;
  }, []);
  const refresh = useCallback(async () => {
    const [config, history, facts, files, items, aliases, voices] =
      await Promise.all([
        request<Settings>("/settings"),
        request<Message[]>("/messages"),
        request<Memory[]>("/memories"),
        request<Doc[]>("/documents"),
        request<CatalogItem[]>("/catalog"),
        request<{ custom: Alias[] }>("/aliases"),
        request<VoiceInfo>("/voice"),
      ]);
    setSettings(config);
    setMessages(history);
    setMemories(facts);
    setDocuments(files);
    setCatalog(items);
    setAliasList(aliases.custom);
    setVoice(voices);
    void refreshModels().catch(fail);
  }, [refreshModels]);
  const stop = useCallback(() => {
    abort.current?.abort();
    speechAbort.current?.abort();
    playback.current?.audio.pause();
    playback.current?.finish();
    if (recorder.current?.state === "recording") recorder.current.stop();
    void request("/voice/stop", "POST").catch(() => {});
    channel.current?.postMessage({ type: "speaking", value: false });
    setSpeaking(false);
  }, []);
  useEffect(() => {
    void refresh().catch(fail);
    channel.current = new BroadcastChannel("wiley-ui");
    channel.current.onmessage = (event) => {
      if (event.data.type === "settings")
        void request<Settings>("/settings").then(setSettings).catch(fail);
      if (event.data.type === "speaking")
        setSpeaking(Boolean(event.data.value));
      if (event.data.type === "draft") {
        setDraft(String(event.data.text));
        setTab("chat");
      }
      if (event.data.type === "stop") stop();
    };
    const offStop = window.wiley.onStop(stop);
    const offReminder = window.wiley.onReminder((title) =>
      setNotice("Напоминание: " + title),
    );
    const offOffline = window.wiley.onOffline(() =>
      setError("Ядро остановилось. Перезапустите WileyAI."),
    );
    return () => {
      offStop();
      offReminder();
      offOffline();
      channel.current?.close();
      audioStream.current?.getTracks().forEach((track) => track.stop());
    };
  }, [refresh, stop]);
  useEffect(() => {
    listEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, answer]);
  useEffect(() => {
    if (!jobs.some((job) => ["queued", "running"].includes(job.status))) return;
    const timer = setInterval(() => {
      request<Job[]>("/jobs")
        .then((data) => {
          setJobs(data);
          if (!data.some((job) => ["queued", "running"].includes(job.status)))
            void refreshModels();
        })
        .catch(fail);
    }, 1200);
    return () => clearInterval(timer);
  }, [jobs, refreshModels]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(timer);
  }, [notice]);

  async function save(next = settings) {
    if (!next) return;
    const saved = await request<Settings>("/settings", "PUT", {
      ...next,
      ...(keyTouched ? { api_key: apiKey } : {}),
    });
    setSettings(saved);
    setApiKey("");
    setKeyTouched(false);
    channel.current?.postMessage({ type: "settings" });
    setNotice("Настройки сохранены");
    await refreshModels();
  }
  async function speak(text: string) {
    speechAbort.current?.abort();
    playback.current?.audio.pause();
    playback.current?.finish();
    const generation = ++speechGeneration.current;
    const controller = new AbortController();
    speechAbort.current = controller;
    setSpeaking(true);
    channel.current?.postMessage({ type: "speaking", value: true });
    try {
      if (settings?.tts_engine === "silero") {
        const blob = await audioRequest(
          text,
          settings.tts_voice,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        const url = URL.createObjectURL(blob);
        try {
          const audio = new Audio(url);
          await new Promise<void>((resolve, reject) => {
            playback.current = { audio, finish: resolve };
            audio.onended = () => resolve();
            audio.onerror = () =>
              reject(new Error("Не удалось воспроизвести озвучку"));
            void audio.play().catch(reject);
          });
        } finally {
          URL.revokeObjectURL(url);
        }
      } else {
        await request(
          "/voice/speak",
          "POST",
          { text, voice: settings?.tts_voice || "" },
          controller.signal,
        );
      }
    } finally {
      if (generation === speechGeneration.current) {
        playback.current = null;
        setSpeaking(false);
        channel.current?.postMessage({ type: "speaking", value: false });
      }
    }
  }
  async function send(text = draft) {
    if (!text.trim() || busy) return;
    setError("");
    setDraft("");
    setAnswer("");
    setBusy(true);
    const controller = new AbortController();
    abort.current = controller;
    let completed = "";
    try {
      await stream(text, selectedDocs, controller.signal, (event) => {
        if (event.type === "user" && event.message)
          setMessages((items) => [...items, event.message!]);
        if (event.type === "delta") setAnswer((value) => value + event.text);
        if (event.type === "error") setError(event.text || "Ошибка модели");
        if (event.type === "done" && event.message) {
          completed = event.message.content;
          setMessages((items) => [...items, event.message!]);
          setAnswer("");
        }
      });
      if (completed && settings?.speak_answers)
        void speak(completed).catch(fail);
      void request<Memory[]>("/memories").then(setMemories);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError"))
        fail(error);
    } finally {
      setBusy(false);
      setAnswer("");
      abort.current = null;
    }
  }
  async function toggleRecording() {
    if (recording) {
      recorder.current?.stop();
      return;
    }
    if (!voice.available)
      throw new Error(
        "Сначала установите модуль речи: uv sync --extra dev --extra voice. Затем перезапустите приложение.",
      );
    if (!voice.installed_stt.includes(settings!.stt_model))
      throw new Error("Скачайте выбранную модель Whisper в разделе «Модели».");
    await request("/voice/stop", "POST");
    const media = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    audioStream.current = media;
    const audio = new MediaRecorder(media, { mimeType: "audio/webm" });
    recorder.current = audio;
    const chunks: BlobPart[] = [];
    audio.ondataavailable = (event) => chunks.push(event.data);
    audio.onstop = () => {
      media.getTracks().forEach((track) => track.stop());
      setRecording(false);
      setUploading(true);
      const data = new FormData();
      data.append(
        "file",
        new Blob(chunks, { type: "audio/webm" }),
        "speech.webm",
      );
      request<{ text: string }>("/voice/transcribe", "POST", data)
        .then((result) => {
          setDraft(result.text);
          input.current?.focus();
          if (!result.text)
            setNotice("Речь не распознана. Попробуйте ещё раз.");
        })
        .catch(fail)
        .finally(() => setUploading(false));
    };
    audio.start();
    setRecording(true);
  }
  async function download(item: CatalogItem) {
    if (item.kind === "stt" || item.kind === "tts") {
      setVoiceDownloading(item.id);
      try {
        await request("/voice/download", "POST", { model: item.id });
        setVoice(await request("/voice"));
        setNotice(
          item.kind === "stt"
            ? "Модель распознавания установлена"
            : "Модель озвучки установлена",
        );
      } finally {
        setVoiceDownloading("");
      }
    } else if (item.kind === "llm") {
      await request("/models/pull", "POST", { model: item.id });
      setJobs(await request("/jobs"));
    }
  }
  async function importModel() {
    const file = await window.wiley.pickFile("model");
    if (!file) return;
    const name = customModel.trim();
    if (!name)
      throw new Error(
        "Сначала укажите имя импортируемой модели, например wiley-local",
      );
    await request("/models/pull", "POST", { model: name, path: file });
    setJobs(await request("/jobs"));
  }
  async function chooseAvatar() {
    const file = await window.wiley.pickFile("avatar");
    if (file) await save({ ...settings!, avatar_path: file });
  }

  if (!settings)
    return (
      <div className="loading">
        <div className="logo-mark">W</div>
        <p>Запускаю локальное ядро…</p>
        {error && <p role="alert">{error}</p>}
      </div>
    );
  if (view === "avatar")
    return (
      <div className="pet-window">
        <div className="pet-drag">
          <span>◈ {settings.name}</span>
          <button
            aria-label="Открыть настройки"
            onClick={() => window.wiley.showWindow("settings")}
          >
            ⚙
          </button>
        </div>
        <Avatar path={settings.avatar_path} speaking={speaking} />
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <div className="pet-actions">
          <button onClick={() => window.wiley.showWindow("chat")}>
            Открыть чат
          </button>
          <button onClick={() => run(toggleRecording)}>
            {recording ? "■ Стоп" : "● Голос"}
          </button>
          <button
            title="Вернуть управление можно через иконку в трее или Ctrl+Shift+Esc"
            onClick={() => window.wiley.clickThrough(true)}
          >
            Пропуск кликов
          </button>
        </div>
        <p className="pet-note">
          {recording ? (
            "Слушаю. Нажмите «Стоп», когда закончите."
          ) : uploading ? (
            "Распознаю речь…"
          ) : draft ? (
            <button
              onClick={() =>
                run(async () => {
                  await window.wiley.showWindow("chat");
                  channel.current?.postMessage({ type: "draft", text: draft });
                })
              }
            >
              {draft}
            </button>
          ) : (
            "Перетащите за верхнюю панель"
          )}
        </p>
      </div>
    );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo-mark">W</div>
          <div>
            Wiley<span>AI</span>
            <small>PERSONAL ASSISTANT</small>
          </div>
        </div>
        <div className="workspace-label">МОЁ ПРОСТРАНСТВО</div>
        <nav>
          {tabs.map((item) => (
            <button
              key={item.id}
              className={tab === item.id ? "nav-item active" : "nav-item"}
              onClick={() => {
                setTab(item.id);
                setError("");
              }}
            >
              <span>{item.icon}</span>
              {item.label}
              {item.id === "memory" && <small>{memories.length}</small>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-badge">
            <i />
            Локальное ядро работает
          </div>
          <p>
            Ваше пространство.
            <br />
            Ваш характер. Ваш выбор.
          </p>
          <button
            className="subtle"
            onClick={() => window.wiley.showWindow("avatar")}
          >
            ↗ Показать аватара
          </button>
          <button className="subtle" onClick={() => window.wiley.quit()}>
            Выйти из WileyAI
          </button>
          <small>v0.1 · первый рабочий прототип</small>
        </div>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            WileyAI <span>/</span> {tabs.find((item) => item.id === tab)?.label}
          </div>
          <div className={"connection " + (connected ? "online" : "")}>
            <i />
            {connected ? settings.model : "Модель не подключена"}
          </div>
        </header>
        {error && (
          <div className="error global-message" role="alert">
            <span>{error}</span>
            <button aria-label="Закрыть ошибку" onClick={() => setError("")}>
              ×
            </button>
          </div>
        )}
        {notice && (
          <div className="notice global-message" role="status">
            {notice}
          </div>
        )}

        {tab === "chat" && (
          <div className="chat-layout">
            <section className="chat-panel">
              <div className="page-heading compact">
                <div>
                  <span className="eyebrow">ВСЕГДА РЯДОМ</span>
                  <h1>
                    Привет, я {settings.name}
                    <span className="mint">.</span>
                  </h1>
                  <p>Поговорим, разберём документ или откроем нужное.</p>
                </div>
                <button
                  className="outline"
                  onClick={() => window.wiley.showWindow("avatar")}
                >
                  ◈ Аватар
                </button>
              </div>
              <div className="messages" aria-live="polite">
                {!messages.length && (
                  <div className="welcome">
                    <div className="welcome-symbol">✳</div>
                    <h2>С чего начнём?</h2>
                    <p>
                      Можно просто поговорить. А знакомые команды
                      <br />я выполню даже без подключения нейросети.
                    </p>
                    <div className="suggestions">
                      {[
                        "Открой загрузки",
                        "Запомни: я предпочитаю короткие ответы",
                        "Расскажи, чем ты можешь помочь",
                      ].map((text) => (
                        <button key={text} onClick={() => setDraft(text)}>
                          {text}
                          <span>↗</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {messages.map((message) => (
                  <article
                    key={message.id}
                    className={"message " + message.role}
                  >
                    <div className="message-avatar">
                      {message.role === "user" ? "Вы" : "W"}
                    </div>
                    <div className="message-body">
                      <div className="message-meta">
                        {message.role === "user" ? "Вы" : settings.name}
                        <time>{stamp(message.created)}</time>
                        {message.role === "assistant" && (
                          <button
                            className="speak-button"
                            aria-label="Озвучить ответ"
                            onClick={() => run(() => speak(message.content))}
                          >
                            ♪
                          </button>
                        )}
                      </div>
                      <div className="message-text">{message.content}</div>
                    </div>
                  </article>
                ))}
                {busy && (
                  <article className="message assistant">
                    <div className="message-avatar">W</div>
                    <div className="message-body">
                      <div className="message-meta">
                        {settings.name}
                        <span className="thinking">отвечает</span>
                      </div>
                      <div className="message-text">
                        {answer || <span className="dots">•••</span>}
                      </div>
                    </div>
                  </article>
                )}
                <div ref={listEnd} />
              </div>
              {documents.length > 0 && (
                <div className="document-strip">
                  {documents.map((doc) => (
                    <div
                      className={
                        "doc-chip " +
                        (selectedDocs.includes(doc.id) ? "selected" : "")
                      }
                      key={doc.id}
                    >
                      <button
                        title="Включить документ в следующий вопрос"
                        onClick={() =>
                          setSelectedDocs((ids) =>
                            ids.includes(doc.id)
                              ? ids.filter((id) => id !== doc.id)
                              : [...ids, doc.id],
                          )
                        }
                      >
                        ▤ {doc.name}
                      </button>
                      <button
                        aria-label={"Удалить " + doc.name}
                        onClick={() =>
                          run(async () => {
                            await request("/documents/" + doc.id, "DELETE");
                            setDocuments((items) =>
                              items.filter((item) => item.id !== doc.id),
                            );
                            setSelectedDocs((ids) =>
                              ids.filter((id) => id !== doc.id),
                            );
                          })
                        }
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="composer-area">
                <form
                  className="composer"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void send();
                  }}
                >
                  <textarea
                    ref={input}
                    aria-label="Сообщение"
                    placeholder={
                      recording
                        ? "Идёт запись с микрофона…"
                        : "Напишите сообщение или команду…"
                    }
                    value={draft}
                    rows={2}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        void send();
                      }
                    }}
                  />
                  <div className="composer-tools">
                    <div>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label="Прикрепить документ"
                        disabled={uploading}
                        onClick={() => upload.current?.click()}
                      >
                        ＋
                      </button>
                      <button
                        type="button"
                        className={
                          "icon-button " + (recording ? "recording" : "")
                        }
                        aria-label={
                          recording ? "Остановить запись" : "Записать голос"
                        }
                        disabled={busy || uploading}
                        onClick={() => run(toggleRecording)}
                      >
                        {recording ? "■" : "♩"}
                      </button>
                      <span>
                        {recording
                          ? "Микрофон включён"
                          : uploading
                            ? "Обрабатываю файл…"
                            : "Shift + Enter — новая строка"}
                      </span>
                    </div>
                    {busy ? (
                      <button
                        className="send"
                        type="button"
                        onClick={stop}
                        aria-label="Остановить ответ"
                      >
                        ■
                      </button>
                    ) : (
                      <button
                        className="send"
                        type="submit"
                        disabled={!draft.trim() || recording}
                        aria-label="Отправить"
                      >
                        ↑
                      </button>
                    )}
                  </div>
                </form>
                <div className="composer-caption">
                  <span>
                    <i />
                    {settings.provider === "ollama"
                      ? "Локальная модель · "
                      : "Внешний провайдер · "}
                    {settings.model}
                  </span>
                  <span>Память остаётся в WileyAI</span>
                </div>
              </div>
              <input
                ref={upload}
                hidden
                type="file"
                accept=".txt,.md,.csv,.pdf,.docx"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (!file) return;
                  setUploading(true);
                  void run(async () => {
                    const data = new FormData();
                    data.append("file", file);
                    const doc = await request<Doc>("/documents", "POST", data);
                    setDocuments((items) => [...items, doc]);
                    setSelectedDocs((ids) => [...ids, doc.id]);
                    setNotice(
                      "Документ добавлен. Задайте вопрос по содержимому.",
                    );
                  }).finally(() => setUploading(false));
                  event.target.value = "";
                }}
              />
            </section>
            <aside className="companion-panel">
              <div className="companion-title">
                <span>ВАШ АССИСТЕНТ</span>
                <span className="live-dot" />
              </div>
              <Avatar path={settings.avatar_path} speaking={speaking} />
              <h2>{settings.name}</h2>
              <p>
                {speaking
                  ? "Говорю с вами"
                  : busy
                    ? "Обдумываю ответ"
                    : "Готов помочь"}
              </p>
              <div className="companion-details">
                <div>
                  <span>Профиль</span>
                  <strong>
                    {
                      {
                        eco: "Экономичный",
                        balanced: "Сбалансированный",
                        quality: "Качество",
                      }[settings.profile]
                    }
                  </strong>
                </div>
                <div>
                  <span>Память</span>
                  <strong>{memories.length} записей</strong>
                </div>
                <div>
                  <span>Голос</span>
                  <strong>
                    {settings.speak_answers ? "Ответы вслух" : "По запросу"}
                  </strong>
                </div>
              </div>
              <button
                className="outline full"
                onClick={() => setTab("settings")}
              >
                Настроить персонажа
              </button>
              <div className="tip">
                <span>ПОДСКАЗКА</span>
                <p>
                  «Запомни: …» — сохранит важное. Вы всегда можете посмотреть и
                  удалить записи.
                </p>
              </div>
            </aside>
          </div>
        )}

        {tab === "models" && (
          <section className="page scroll-page">
            <div className="page-heading">
              <div>
                <span className="eyebrow">СВОБОДА ВЫБОРА</span>
                <h1>Модели и голос</h1>
                <p>Компоненты меняются. Ваша история и память остаются.</p>
              </div>
              <button
                className="outline"
                onClick={() =>
                  run(async () => {
                    const status = await refreshModels();
                    if (!status.connected) throw new Error(status.error);
                    setVoice(await request("/voice"));
                    setNotice("Список обновлён");
                  })
                }
              >
                ↻ Обновить
              </button>
            </div>
            <div
              className="model-categories"
              role="tablist"
              aria-label="Категории моделей"
            >
              {[
                { id: "llm", name: "Мозг", hint: "Общение и понимание команд" },
                {
                  id: "tts",
                  name: "Озвучка",
                  hint: "Модель и голос ассистента",
                },
                {
                  id: "stt",
                  name: "Распознавание голоса",
                  hint: "Преобразование речи в текст",
                },
              ].map((category) => (
                <button
                  key={category.id}
                  role="tab"
                  aria-selected={modelCategory === category.id}
                  className={modelCategory === category.id ? "selected" : ""}
                  onClick={() => setModelCategory(category.id)}
                >
                  <strong>{category.name}</strong>
                  <span>{category.hint}</span>
                </button>
              ))}
            </div>
            <div className="section-label">
              КАТАЛОГ ·{" "}
              {
                { llm: "МОЗГ", tts: "ОЗВУЧКА", stt: "РАСПОЗНАВАНИЕ ГОЛОСА" }[
                  modelCategory
                ]
              }
            </div>
            <div className="model-grid">
              {catalog
                .filter((item) => item.kind === modelCategory)
                .map((item) => {
                  const ready =
                    item.kind === "llm"
                      ? installed.some((model) => model.id === item.id)
                      : item.kind === "stt"
                        ? voice.installed_stt.includes(item.id)
                        : item.engine === "silero"
                          ? voice.silero_installed
                          : voice.voices.length > 0;
                  const downloading =
                    jobs.some(
                      (job) =>
                        job.model === item.id &&
                        ["queued", "running"].includes(job.status),
                    ) || voiceDownloading === item.id;
                  return (
                    <article className="model-card" key={item.id}>
                      <div className="model-card-top">
                        <span className={"kind " + item.kind}>
                          {
                            {
                              llm: "МОЗГ",
                              tts: "ОЗВУЧКА",
                              stt: "РАСПОЗНАВАНИЕ",
                            }[item.kind]
                          }
                        </span>
                        <span className="muted">{item.engine}</span>
                      </div>
                      <h2>{item.name}</h2>
                      <p>{item.description}</p>
                      <div className="model-properties">
                        <span>{item.size}</span>
                        <span>{item.languages}</span>
                        <span>{item.license}</span>
                      </div>
                      <div className="model-card-footer">
                        <span className={ready ? "ready" : "muted"}>
                          {ready ? "● Установлена" : "Не установлена"}
                        </span>
                        {item.kind === "tts" && ready ? (
                          <button
                            className="outline"
                            onClick={() =>
                              run(async () => {
                                await save({
                                  ...settings,
                                  tts_engine:
                                    item.engine as Settings["tts_engine"],
                                  tts_voice: "",
                                });
                                setTab("settings");
                              })
                            }
                          >
                            Выбрать голос
                          </button>
                        ) : ready ? (
                          <button
                            className="outline"
                            disabled={busy}
                            onClick={() =>
                              run(async () => {
                                await save({
                                  ...settings,
                                  ...(item.kind === "llm"
                                    ? { model: item.id }
                                    : {
                                        stt_model:
                                          item.id as Settings["stt_model"],
                                      }),
                                });
                              })
                            }
                          >
                            Выбрать
                          </button>
                        ) : (
                          <button
                            className="primary"
                            disabled={
                              downloading ||
                              (item.kind !== "llm" && Boolean(voiceDownloading))
                            }
                            onClick={() => run(() => download(item))}
                          >
                            {downloading ? "Загружается…" : "↓ Скачать"}
                          </button>
                        )}
                      </div>
                    </article>
                  );
                })}
            </div>
            {jobs.length > 0 && (
              <div className="card">
                <h2>Загрузки</h2>
                {jobs.map((job) => (
                  <div className="download-row" key={job.id}>
                    <div>
                      <strong>{job.model}</strong>
                      <p>{job.detail}</p>
                      {job.total > 0 && (
                        <progress value={job.completed} max={job.total} />
                      )}
                    </div>
                    {["queued", "running"].includes(job.status) && (
                      <button
                        className="outline"
                        onClick={() =>
                          run(async () => {
                            await request("/jobs/" + job.id, "DELETE");
                            setJobs(await request("/jobs"));
                          })
                        }
                      >
                        Остановить
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
            {modelCategory === "llm" && (
              <div className="two-columns">
                <div className="card">
                  <h2>Своя модель GGUF</h2>
                  <p>
                    Импорт в выбранный сервер Ollama. Исходный файл сохраняется;
                    движок создаёт свою копию.
                  </p>
                  <label>
                    Имя модели
                    <input
                      placeholder="wiley-local"
                      value={customModel}
                      onChange={(event) => setCustomModel(event.target.value)}
                    />
                  </label>
                  <button
                    className="outline"
                    disabled={!customModel.trim()}
                    onClick={() => run(importModel)}
                  >
                    Выбрать файл и импортировать
                  </button>
                </div>
                <div className="card">
                  <h2>Установленные модели</h2>
                  {installed.length ? (
                    installed.map((item) => (
                      <div className="installed-row" key={item.id}>
                        <span>
                          {item.id}
                          <small>
                            {item.size
                              ? (item.size / 1e9).toFixed(1) + " ГБ на диске"
                              : "Модель сервера"}
                          </small>
                        </span>
                        <button
                          className="outline"
                          disabled={busy}
                          onClick={() =>
                            run(() => save({ ...settings, model: item.id }))
                          }
                        >
                          {settings.model === item.id ? "Выбрана" : "Выбрать"}
                        </button>
                      </div>
                    ))
                  ) : (
                    <p>Подключите сервер или скачайте модель из каталога.</p>
                  )}
                  <button
                    className="subtle"
                    onClick={() =>
                      run(async () => {
                        await request("/models/unload", "POST");
                        setNotice("Запрос на выгрузку модели отправлен");
                      })
                    }
                  >
                    Выгрузить активную модель из памяти
                  </button>
                </div>
              </div>
            )}
          </section>
        )}

        {(tab === "tasks" || tab === "notes") && (
          <Productivity key={tab} mode={tab} onError={fail} />
        )}
        {tab === "capabilities" && <Capabilities onError={fail} />}

        {tab === "memory" && (
          <section className="page scroll-page">
            <div className="page-heading">
              <div>
                <span className="eyebrow">ВАШ ОБЩИЙ КОНТЕКСТ</span>
                <h1>Память</h1>
                <p>
                  Только сохранённые вами факты. Просматривайте, добавляйте и
                  удаляйте.
                </p>
              </div>
              <span className="count-pill">{memories.length} записей</span>
            </div>
            <form
              className="card memory-form"
              onSubmit={(event) => {
                event.preventDefault();
                void run(async () => {
                  await request("/memories", "POST", { text: memoryDraft });
                  setMemoryDraft("");
                  setMemories(await request("/memories"));
                });
              }}
            >
              <textarea
                aria-label="Новая запись памяти"
                placeholder="Например: рабочие проекты находятся в D:\projects"
                value={memoryDraft}
                onChange={(event) => setMemoryDraft(event.target.value)}
              />
              <button className="primary" disabled={!memoryDraft.trim()}>
                Запомнить
              </button>
            </form>
            <div className="memory-list">
              {memories.map((item) => (
                <article className="card memory-card" key={item.id}>
                  <div className="memory-symbol">◎</div>
                  <div>
                    <p>{item.content}</p>
                    <small>
                      {new Date(item.created).toLocaleDateString("ru-RU")} ·
                      добавлено владельцем
                    </small>
                  </div>
                  <button
                    className="subtle danger"
                    aria-label={"Удалить запись " + item.content}
                    onClick={() =>
                      run(async () => {
                        await request("/memories/" + item.id, "DELETE");
                        setMemories((items) =>
                          items.filter((value) => value.id !== item.id),
                        );
                      })
                    }
                  >
                    Удалить
                  </button>
                </article>
              ))}
            </div>
            {!memories.length && (
              <div className="empty-state">
                Здесь появится то, что вы попросите запомнить.
              </div>
            )}
          </section>
        )}

        {tab === "commands" && (
          <section className="page scroll-page">
            <div className="page-heading">
              <div>
                <span className="eyebrow">ПОНЯТНЫЕ ДЕЙСТВИЯ</span>
                <h1>Команды Windows</h1>
                <p>
                  Привычные названия для папок, файлов, приложений и сайтов.
                </p>
              </div>
            </div>
            <div className="card builtin-commands">
              <span>УЖЕ МОЖНО СКАЗАТЬ</span>
              <p>
                «Открой загрузки» · «Запусти блокнот» · «Открой гитхаб» ·
                «Открой https://example.com»
              </p>
            </div>
            <form
              className="card"
              onSubmit={(event) => {
                event.preventDefault();
                void run(async () => {
                  await request("/aliases", "POST", alias);
                  setAlias({ name: "", kind: "folder", target: "" });
                  setAliasList(
                    (await request<{ custom: Alias[] }>("/aliases")).custom,
                  );
                });
              }}
            >
              <h2>Добавить своё название</h2>
              <div className="two-columns">
                <label>
                  Название
                  <input
                    placeholder="папка проектов"
                    value={alias.name}
                    onChange={(event) =>
                      setAlias((value) => ({
                        ...value,
                        name: event.target.value,
                      }))
                    }
                    required
                  />
                </label>
                <label>
                  Тип
                  <select
                    value={alias.kind}
                    onChange={(event) =>
                      setAlias((value) => ({
                        ...value,
                        kind: event.target.value,
                      }))
                    }
                  >
                    <option value="folder">Папка</option>
                    <option value="file">Файл</option>
                    <option value="app">Приложение</option>
                    <option value="url">Сайт</option>
                  </select>
                </label>
              </div>
              <label>
                Путь или адрес
                <div className="input-with-button">
                  <input
                    placeholder={
                      alias.kind === "url"
                        ? "https://example.com"
                        : "D:\projects"
                    }
                    value={alias.target}
                    onChange={(event) =>
                      setAlias((value) => ({
                        ...value,
                        target: event.target.value,
                      }))
                    }
                    required
                  />
                  {alias.kind !== "url" && (
                    <button
                      className="outline"
                      type="button"
                      onClick={() =>
                        run(async () => {
                          const file = await window.wiley.pickFile(alias.kind);
                          if (file)
                            setAlias((value) => ({ ...value, target: file }));
                        })
                      }
                    >
                      Обзор
                    </button>
                  )}
                </div>
              </label>
              <button
                className="primary"
                disabled={!alias.name.trim() || !alias.target.trim()}
              >
                Сохранить команду
              </button>
            </form>
            <div className="card">
              <h2>Мои команды</h2>
              {aliasList.map((item) => (
                <div className="alias-row" key={item.id}>
                  <div>
                    <strong>«Открой {item.name}»</strong>
                    <small>{item.target}</small>
                  </div>
                  <button
                    className="subtle danger"
                    onClick={() =>
                      run(async () => {
                        await request("/aliases/" + item.id, "DELETE");
                        setAliasList((items) =>
                          items.filter((value) => value.id !== item.id),
                        );
                      })
                    }
                  >
                    Удалить
                  </button>
                </div>
              ))}
              {!aliasList.length && (
                <p>Добавьте названия для того, что открываете чаще всего.</p>
              )}
            </div>
          </section>
        )}

        {tab === "settings" && (
          <section className="page scroll-page">
            <div className="page-heading">
              <div>
                <span className="eyebrow">ПОД ВАШ РИТМ</span>
                <h1>Настройки ассистента</h1>
                <p>Характер, подключение и голос — в одном месте.</p>
              </div>
              <button
                className="primary"
                disabled={busy}
                onClick={() => run(() => save())}
              >
                Сохранить
              </button>
            </div>
            <div className="settings-grid">
              <div className="card">
                <h2>Личность</h2>
                <label>
                  Имя
                  <input
                    value={settings.name}
                    onChange={(event) =>
                      setSettings({ ...settings, name: event.target.value })
                    }
                  />
                </label>
                <label>
                  Характер и манера общения
                  <textarea
                    rows={5}
                    value={settings.personality}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        personality: event.target.value,
                      })
                    }
                  />
                </label>
                <label>
                  Профиль производительности
                  <select
                    value={settings.profile}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        profile: event.target.value as Settings["profile"],
                      })
                    }
                  >
                    <option value="eco">
                      Экономичный · выгрузка через 1 минуту
                    </option>
                    <option value="balanced">Сбалансированный · 5 минут</option>
                    <option value="quality">Качество · 15 минут</option>
                  </select>
                </label>
              </div>
              <div className="card">
                <h2>Подключение модели</h2>
                <label>
                  Движок
                  <select
                    value={settings.provider}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        provider: event.target.value as Settings["provider"],
                        base_url:
                          event.target.value === "ollama"
                            ? "http://127.0.0.1:11434"
                            : "https://example.com/v1",
                      })
                    }
                  >
                    <option value="ollama">Ollama</option>
                    <option value="compatible">Совместимый API</option>
                  </select>
                </label>
                <label>
                  Адрес сервера
                  <input
                    value={settings.base_url}
                    onChange={(event) =>
                      setSettings({ ...settings, base_url: event.target.value })
                    }
                  />
                </label>
                <label>
                  Идентификатор модели
                  <input
                    value={settings.model}
                    onChange={(event) =>
                      setSettings({ ...settings, model: event.target.value })
                    }
                  />
                </label>
                <label>
                  Ключ API
                  <input
                    type="password"
                    autoComplete="off"
                    placeholder={
                      settings.has_api_key
                        ? "Ключ сохранён в Windows"
                        : "Если требуется провайдером"
                    }
                    value={apiKey}
                    onChange={(event) => {
                      setApiKey(event.target.value);
                      setKeyTouched(true);
                    }}
                  />
                </label>
                <label>
                  Контекст, токенов
                  <input
                    type="number"
                    min={1024}
                    max={32768}
                    step={1024}
                    value={settings.context_tokens}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        context_tokens: Number(event.target.value),
                      })
                    }
                  />
                </label>
                <p className="help">
                  Сохраните настройки, затем обновите список в разделе «Модели».
                  Облако подключается только по вашему выбору.
                </p>
              </div>
              <div className="card">
                <h2>Речь и озвучка</h2>
                <label>
                  Модель распознавания
                  <select
                    value={settings.stt_model}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        stt_model: event.target.value as Settings["stt_model"],
                      })
                    }
                  >
                    {["tiny", "base", "small"].map((value) => (
                      <option key={value} value={value}>
                        Whisper {value}
                        {voice.installed_stt.includes(value)
                          ? " · установлена"
                          : " · нужно скачать"}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Движок озвучки
                  <select
                    value={settings.tts_engine}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        tts_engine: event.target
                          .value as Settings["tts_engine"],
                        tts_voice: "",
                      })
                    }
                  >
                    <option value="silero">Silero · русский язык</option>
                    <option value="sapi">Системные голоса Windows</option>
                  </select>
                </label>
                <label>
                  Голос ассистента
                  <select
                    value={settings.tts_voice}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        tts_voice: event.target.value,
                      })
                    }
                  >
                    <option value="">
                      {settings.tts_engine === "silero"
                        ? "Ксения · по умолчанию"
                        : "Голос Windows по умолчанию"}
                    </option>
                    {(settings.tts_engine === "silero"
                      ? [
                          { name: "xenia", language: "Ксения · русский" },
                          { name: "baya", language: "Бая · русский" },
                          { name: "aidar", language: "Айдар · русский" },
                          {
                            name: "kseniya",
                            language: "Ксения, вариант · русский",
                          },
                        ]
                      : voice.voices
                    ).map((item) => (
                      <option key={item.name} value={item.name}>
                        {item.name} · {item.language}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={settings.speak_answers}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        speak_answers: event.target.checked,
                      })
                    }
                  />
                  Озвучивать ответы автоматически
                </label>
                <button
                  className="outline"
                  onClick={() =>
                    run(() => speak("Привет! Я Уайли. Давай начнём."))
                  }
                >
                  ♪ Прослушать голос
                </button>
                <p className="help">
                  После записи распознанный текст появится в поле сообщения: его
                  можно исправить перед отправкой.
                </p>
              </div>
              <div className="card">
                <h2>Персонаж на рабочем столе</h2>
                <p>
                  VRM 0.x / 1.0 со встроенными текстурами, до 64 МБ. Модель
                  хранится на вашем диске.
                </p>
                <div className="file-path">
                  {settings.avatar_path || "Аватар пока не выбран"}
                </div>
                <div className="button-row">
                  <button className="outline" onClick={() => run(chooseAvatar)}>
                    Загрузить VRM
                  </button>
                  <button
                    className="outline"
                    onClick={() => window.wiley.showWindow("avatar")}
                  >
                    Показать
                  </button>
                </div>
                <p className="help">
                  Ctrl + Shift + Space — открыть чат.
                  <br />
                  Ctrl + Shift + Esc — остановить ответ и озвучку, вернуть клики
                  аватару.
                </p>
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
