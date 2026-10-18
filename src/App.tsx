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
  scoped,
  audioRequest,
  stream,
  type Settings,
  type Message,
  type Memory,
  type MemoryCandidate,
  type Doc,
  type Job,
  type CatalogItem,
  type Alias,
  type VoiceInfo,
  type Chat,
  type Project,
  type SpeechSettings,
  type ReadingProgress,
  cloudOptions,
} from "./api";
import { Productivity, Capabilities } from "./Productivity";
import { MemoryPanel, MemorySuggestions } from "./Memory";
import { BackupPanel } from "./Backups";
import { ComponentPanel } from "./Components";
import { UpdateNotice, UpdatesPanel } from "./Updates";
import { SetupWizard, type SetupProgress } from "./Setup";
import { SearchSettings, SearchSources } from "./WebSearch";
import { ChatSpaces } from "./ChatSpaces";
import { RoutinePanel, ToolAccess } from "./Routines";
import { DeviceAudio } from "./DeviceAudio";
import { Applications } from "./Applications";
import { YandexMusic } from "./YandexMusic";
import { ActionLog } from "./ActionLog";
import { NebulaBackground } from "./NebulaBackground";
import { CalendarPanel } from "./Calendar";
import { DocumentPanel } from "./Documents";
import { MonitorPanel, ResourceBadge } from "./Monitor";
import { SettingsNavigation, type SettingsSection } from "./SettingsNavigation";
import { DocumentContext } from "./DocumentContext";
import { DocumentReadingProgress } from "./DocumentReadingProgress";
import { AppearancePanel, ThemeSwitch } from "./AppearancePanel";
import { applyAppearance, type Appearance } from "./appearance";
import { ProcessStatus, type ProcessKind } from "./ProcessStatus";
import { CloudSpeechSettings } from "./voice/CloudSpeech";
import { OpenVoiceSettings } from "./voice/OpenVoice";
import { usesOpenVoice, selectSpeechEngine } from "./voice/speechEngine";
import { ChatMessages, type HistoryFocus } from "./ChatMessages";
import { HistorySearch, type HistoryHit } from "./HistorySearch";
import { historyParts } from "./historyText";
import {
  Conversation,
  phaseLabels,
  type ConversationState,
} from "./voice/conversation";
import { Microphone } from "./voice/microphone";
import { ConversationControl } from "./voice/ConversationControl";
import { AudioDevices } from "./voice/AudioDevices";
import { SpeechOutput } from "./voice/output";
import {
  microphoneConstraints,
  microphoneError,
  playAudio,
} from "./voice/devices";

const tabs = [
  { id: "chat", icon: "◈", label: "Общение" },
  { id: "models", icon: "⬡", label: "Модели" },
  { id: "tasks", icon: "◷", label: "Задачи" },
  { id: "calendar", icon: "▦", label: "Календарь" },
  { id: "notes", icon: "▤", label: "Заметки" },
  { id: "documents", icon: "▧", label: "Документы" },
  { id: "memory", icon: "◎", label: "Память" },
  { id: "commands", icon: "⌘", label: "Команды" },
  { id: "capabilities", icon: "✳", label: "Возможности" },
  { id: "monitor", icon: "▥", label: "Нагрузка" },
  { id: "settings", icon: "⚙", label: "Настройки" },
];
const stamp = (value: string) =>
  new Date(value).toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });
const attachmentKey = (chat: string) => "wiley-attachments-" + chat;
function readAttachments(chat: string): string[] {
  try {
    const ids: unknown = JSON.parse(
      localStorage.getItem(attachmentKey(chat)) || "[]",
    );
    return Array.isArray(ids)
      ? ids
          .filter(
            (id): id is string =>
              typeof id === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(id),
          )
          .slice(0, 10)
      : [];
  } catch {
    return [];
  }
}
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
  const [appearanceSaving, setAppearanceSaving] = useState(false);
  const appearanceSave = useRef<Promise<void>>(Promise.resolve());
  const appearanceVersion = useRef(0);
  useEffect(() => {
    if (settings) applyAppearance(settings);
  }, [settings?.ui_theme, settings?.ui_motion, settings?.ui_glass]);
  const [setup, setSetup] = useState<SetupProgress | null>(null);
  const [setupOpen, setSetupOpen] = useState(false);
  useEffect(() => {
    if (view !== "chat") return;
    let active = true;
    void request<SetupProgress>("/setup")
      .then((value) => {
        if (active) {
          setSetup(value);
          setSetupOpen(value.active);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [view]);
  const [settingsSection, setSettingsSection] =
    useState<SettingsSection>("personality");
  const savedSettings = useRef<Settings | undefined>(undefined);
  const voiceSave = useRef<Promise<void>>(Promise.resolve());
  const [voiceSaving, setVoiceSaving] = useState(false);
  const voiceSaveVersion = useRef(0);
  const settingsEpoch = useRef(0);
  const acceptSettings = useCallback(
    (config: Settings, preserveDraft = true) => {
      settingsEpoch.current++;
      const previous = savedSettings.current;
      savedSettings.current = config;
      setSettings((draft) => {
        if (!draft || !previous || !preserveDraft) return config;
        const merged = { ...config };
        for (const key of Object.keys(draft) as (keyof Settings)[])
          if (draft[key] !== previous[key])
            Object.assign(merged, { [key]: draft[key] });
        return merged;
      });
    },
    [],
  );
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [replyLimit, setReplyLimit] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [chats, setChats] = useState<Chat[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeChatId, setActiveChatId] = useState(
    localStorage.getItem("wiley-active-chat") || "",
  );
  const activeChatRef = useRef(activeChatId);
  const historyWindow = useRef<{ chat: string; anchor: string } | null>(null);
  const [historyWindowVisible, setHistoryWindowVisible] = useState(false);
  const [historySearch, setHistorySearch] = useState<{
    scope: "chat" | "space";
  } | null>(null);
  const [historyFocus, setHistoryFocus] = useState<HistoryFocus | null>(null);
  const historyFocusVersion = useRef(0);
  const messagePath = useCallback(
    (id: string) =>
      scoped(
        "/messages" +
          (historyWindow.current?.chat === id
            ? "?around=" + encodeURIComponent(historyWindow.current.anchor)
            : ""),
        id,
      ),
    [],
  );
  function resetHistory() {
    historyWindow.current = null;
    setHistoryWindowVisible(false);
    setHistoryFocus(null);
  }
  useEffect(() => {
    const find = (event: KeyboardEvent) => {
      if (
        historySearch ||
        busyRef.current ||
        conversationEnabled.current ||
        chatLoadingRef.current ||
        document.querySelector('[role="dialog"]')
      )
        return;
      if (
        (event.ctrlKey || event.metaKey) &&
        !event.altKey &&
        event.key.toLowerCase() === "f"
      ) {
        event.preventDefault();
        setHistorySearch({ scope: tab === "chat" ? "chat" : "space" });
      }
    };
    window.addEventListener("keydown", find);
    return () => window.removeEventListener("keydown", find);
  }, [tab, historySearch]);
  const [chatLoading, setChatLoading] = useState(true);
  const chatLoadingRef = useRef(true);
  const chatLoadEpoch = useRef(0);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    localStorage.getItem("wiley-sidebar-collapsed") === "true",
  );
  const [companionOpen, setCompanionOpen] = useState(
    localStorage.getItem("wiley-companion-open") !== "false",
  );
  const conversationEnabled = useRef(false);
  const [draft, setDraft] = useState("");
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const chatDrafts = useRef(new Map<string, string>());
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [searchNext, setSearchNext] = useState(false);
  const [stage, setStage] = useState("");
  const [readingProgress, setReadingProgress] =
    useState<ReadingProgress | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [speechPhase, setSpeechPhase] = useState<
    "preparing" | "playing" | null
  >(null);
  const [conversation, setConversation] = useState<ConversationState>({
    active: false,
    owner: false,
    phase: "idle",
  });
  conversationEnabled.current = conversation.active;
  const currentChat = chats.find((item) => item.id === activeChatId);
  const currentProject = projects.find(
    (item) => item.id === currentChat?.project_id,
  );
  const scopeName = currentProject
    ? "Память проекта «" + currentProject.name + "»"
    : "Общая память";
  const [documents, setDocuments] = useState<Doc[]>([]);
  const [selectedDocs, setSelectedDocsState] = useState<string[]>(() =>
    readAttachments(activeChatId),
  );
  const selectedDocsRef = useRef(selectedDocs);
  selectedDocsRef.current = selectedDocs;
  const setSelectedDocs = useCallback(
    (
      update: string[] | ((ids: string[]) => string[]),
      chatId = activeChatRef.current,
    ) => {
      const ids =
        typeof update === "function" ? update(selectedDocsRef.current) : update;
      selectedDocsRef.current = ids;
      setSelectedDocsState(ids);
      if (chatId)
        localStorage.setItem(attachmentKey(chatId), JSON.stringify(ids));
    },
    [],
  );
  const documentRefreshEpoch = useRef(0);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [memoryCandidates, setMemoryCandidates] = useState<MemoryCandidate[]>(
    [],
  );
  const memoryRefreshEpoch = useRef(0);
  const modelRefreshEpoch = useRef(0);
  const dataEpoch = useRef(0);
  const [restoredVersion, setRestoredVersion] = useState(0);
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
    silero_v5_6_installed: false,
    qwen3_available: false,
    qwen3_installed: false,
    qwen3_voices: [],
    piper_available: false,
    piper_voices: [],
  });
  const [recording, setRecording] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadKind, setUploadKind] = useState<"speech" | "document">("speech");
  const [voiceDownloading, setVoiceDownloading] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [searchKey, setSearchKey] = useState("");
  const [searchKeyTouched, setSearchKeyTouched] = useState(false);
  const [customModel, setCustomModel] = useState("");
  const [keyTouched, setKeyTouched] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  const conversationRef = useRef<{
    session: Conversation;
    lease: string;
  } | null>(null);
  const conversationStarting = useRef<{
    lease: string;
    controller: AbortController;
  } | null>(null);
  const conversationEpoch = useRef(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const audioStream = useRef<MediaStream | null>(null);
  const manualAbort = useRef<AbortController | null>(null);
  const manualGeneration = useRef(0);
  const manualDiscard = useRef(false);
  const speechAbort = useRef<AbortController | null>(null);
  const localSpeechId = useRef("");
  const activeSpeechIds = useRef(new Set<string>());
  const speechGeneration = useRef(0);
  const [scrollRequest, setScrollRequest] = useState(0);
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
    const epoch = ++modelRefreshEpoch.current;
    const dataVersion = dataEpoch.current;
    const data = await request<{
      connected: boolean;
      installed: { id: string; size: number }[];
      error?: string;
    }>("/models");
    if (
      epoch === modelRefreshEpoch.current &&
      dataVersion === dataEpoch.current
    ) {
      setConnected(data.connected);
      setInstalled(data.installed);
    }
    return data;
  }, []);
  const refreshMemories = useCallback(async () => {
    const epoch = ++memoryRefreshEpoch.current;
    const id = activeChatRef.current;
    if (!id) return;
    const [facts, candidates, history] = await Promise.all([
      request<Memory[]>(scoped("/memories", id)),
      request<MemoryCandidate[]>(scoped("/memory-candidates", id)),
      request<Message[]>(messagePath(id)),
    ]);
    if (epoch !== memoryRefreshEpoch.current) return;
    setMemories(facts);
    setMemoryCandidates(candidates);
    // Refresh references without overwriting an answer currently streaming.
    // The server checks record revisions, including memories outside the list limit.
    const references = new Map(
      history.map((item) => [item.id, item.memory_context]),
    );
    setMessages((current) =>
      current.map((item) =>
        references.has(item.id)
          ? { ...item, memory_context: references.get(item.id) }
          : item,
      ),
    );
  }, []);
  const memoryChanged = useCallback(async () => {
    await refreshMemories();
    channel.current?.postMessage({ type: "memory-changed" });
  }, [refreshMemories]);
  const refreshDocuments = useCallback(async () => {
    const ticket = ++documentRefreshEpoch.current;
    const epoch = dataEpoch.current;
    const chatId = activeChatRef.current;
    const include = encodeURIComponent(selectedDocsRef.current.join(","));
    const files = await request<Doc[]>(
      scoped("/documents?include=" + include, chatId),
    );
    if (
      ticket !== documentRefreshEpoch.current ||
      epoch !== dataEpoch.current ||
      chatId !== activeChatRef.current
    )
      return;
    setDocuments(files);
    setSelectedDocs((ids) =>
      ids.filter((id) => files.some((file) => file.id === id)),
    );
  }, []);
  const documentsChanged = useCallback(async () => {
    await refreshDocuments();
    channel.current?.postMessage({ type: "documents-changed" });
  }, [refreshDocuments]);
  function toggleDocument(doc: Doc) {
    documentRefreshEpoch.current++;
    setDocuments((items) =>
      items.some((item) => item.id === doc.id) ? items : [...items, doc],
    );
    setSelectedDocs((ids) =>
      ids.includes(doc.id)
        ? ids.filter((id) => id !== doc.id)
        : ids.length < 10
          ? [...ids, doc.id]
          : ids,
    );
  }
  const refresh = useCallback(async () => {
    const configEpoch = settingsEpoch.current;
    documentRefreshEpoch.current++;
    const loading = ++chatLoadEpoch.current;
    chatLoadingRef.current = true;
    setChatLoading(true);
    try {
      const epoch = dataEpoch.current;
      const [chatList, projectList] = await Promise.all([
        request<Chat[]>("/conversations"),
        request<Project[]>("/projects"),
      ]);
      if (epoch !== dataEpoch.current) return;
      setChats(chatList);
      setProjects(projectList);
      const id = chatList.some((chat) => chat.id === activeChatRef.current)
        ? activeChatRef.current
        : chatList[0]?.id;
      if (!id) return;
      if (id !== activeChatRef.current) {
        resetHistory();
        setReplyLimit("");
        setDraft(chatDrafts.current.get(id) || "");
        setSelectedDocs(readAttachments(id), id);
        setSearchNext(false);
        setMessages([]);
        setDocuments([]);
        setMemories([]);
        setMemoryCandidates([]);
      }
      for (const key of chatDrafts.current.keys()) {
        if (!chatList.some((chat) => chat.id === key))
          chatDrafts.current.delete(key);
      }
      activeChatRef.current = id;
      setActiveChatId(id);
      localStorage.setItem("wiley-active-chat", id);
      const [
        config,
        history,
        facts,
        files,
        items,
        aliases,
        voices,
        candidates,
      ] = await Promise.all([
        request<Settings>("/settings"),
        request<Message[]>(messagePath(id)),
        request<Memory[]>(scoped("/memories", id)),
        request<Doc[]>(
          scoped(
            "/documents?include=" +
              encodeURIComponent(selectedDocsRef.current.join(",")),
            id,
          ),
        ),
        request<CatalogItem[]>("/catalog"),
        request<{ custom: Alias[] }>("/aliases"),
        request<VoiceInfo>("/voice"),
        request<MemoryCandidate[]>(scoped("/memory-candidates", id)),
      ]);
      if (epoch !== dataEpoch.current) return;
      if (configEpoch === settingsEpoch.current) acceptSettings(config);
      setMessages(history);
      setMemories(facts);
      setMemoryCandidates(candidates);
      setDocuments(files);
      setSelectedDocs((ids) =>
        ids.filter((id) => files.some((file) => file.id === id)),
      );
      setCatalog(items);
      setAliasList(aliases.custom);
      setVoice(voices);
      void refreshModels().catch(fail);
    } finally {
      if (loading === chatLoadEpoch.current) {
        chatLoadingRef.current = false;
        setChatLoading(false);
      }
    }
  }, [refreshModels, acceptSettings]);
  const selectChat = useCallback(
    async (id: string, broadcast = true, around?: string) => {
      if (busyRef.current || conversationEnabled.current)
        throw new Error("Завершите ответ или разговор перед сменой чата.");
      if (around) {
        historyWindow.current = { chat: id, anchor: around };
        setHistoryWindowVisible(true);
        setHistoryFocus(null);
      } else resetHistory();
      chatDrafts.current.set(activeChatRef.current, draftRef.current);
      activeChatRef.current = id;
      setActiveChatId(id);
      if (broadcast) setTab("chat");
      setDraft(chatDrafts.current.get(id) || "");
      setMessages([]);
      setMemories([]);
      setMemoryCandidates([]);
      setSelectedDocs(readAttachments(id));
      stopAudio();
      setDocuments([]);
      setSearchNext(false);
      setError("");
      setNotice("");
      setReplyLimit("");
      dataEpoch.current++;
      memoryRefreshEpoch.current++;
      await refresh();
      if (broadcast)
        channel.current?.postMessage({ type: "chat-selected", id });
    },
    [refresh],
  );
  async function openHistoryResult(hit: HistoryHit, terms: string[]) {
    setHistorySearch(null);
    setTab("chat");
    try {
      await selectChat(hit.conversation_id, false, hit.id);
      if (activeChatRef.current !== hit.conversation_id)
        throw new Error("Найденный чат уже удалён или изменён");
      setHistoryFocus({
        id: hit.id,
        version: ++historyFocusVersion.current,
        terms,
      });
    } catch (error) {
      if (historyWindow.current?.anchor === hit.id) {
        resetHistory();
        await refresh().catch(() => {});
      }
      throw error;
    }
  }
  async function returnToLatest() {
    await selectChat(activeChatRef.current, false);
    setTab("chat");
    setScrollRequest((value) => value + 1);
  }
  const spacesChanged = useCallback(
    async (id?: string) => {
      setNotice("");
      if (id) await selectChat(id);
      else {
        dataEpoch.current++;
        memoryRefreshEpoch.current++;
        setRestoredVersion((value) => value + 1);
        await refresh();
      }
      channel.current?.postMessage({ type: "spaces-changed" });
    },
    [refresh, selectChat],
  );
  const reportSpeech = useCallback(
    (id: string, value: boolean, broadcast = true) => {
      if (value) activeSpeechIds.current.add(id);
      else activeSpeechIds.current.delete(id);
      setSpeaking(activeSpeechIds.current.size > 0);
      if (broadcast)
        channel.current?.postMessage({ type: "speaking", id, value });
    },
    [],
  );
  const stopAudio = useCallback(() => {
    speechAbort.current?.abort();
    setSpeechPhase(null);
    if (localSpeechId.current) reportSpeech(localSpeechId.current, false);
  }, [reportSpeech]);
  const interruptLocal = useCallback(() => {
    if (conversationRef.current) {
      conversationRef.current.session.interrupt();
      abort.current?.abort();
    }
    stopAudio();
  }, [stopAudio]);
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (
        event.key !== "Escape" ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey ||
        event.metaKey
      )
        return;
      interruptLocal();
      channel.current?.postMessage({ type: "interrupt-speech" });
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [interruptLocal]);
  const endConversation = useCallback(async () => {
    conversationEpoch.current++;
    const starting = conversationStarting.current;
    conversationStarting.current = null;
    if (starting) {
      starting.controller.abort();
      void window.wiley.releaseConversation(starting.lease);
    }
    const current = conversationRef.current;
    conversationRef.current = null;
    stopAudio();
    if (current) {
      try {
        await current.session.stop();
      } finally {
        await window.wiley.releaseConversation(current.lease);
      }
    }
  }, [stopAudio]);
  const stop = useCallback(() => {
    abort.current?.abort();
    manualAbort.current?.abort();
    manualGeneration.current++;
    manualDiscard.current = true;
    if (recorder.current?.state === "recording") recorder.current.stop();
    audioStream.current?.getTracks().forEach((track) => track.stop());
    setRecording(false);
    setUploading(false);
    stopAudio();
    void endConversation().catch(fail);
  }, [endConversation, stopAudio]);
  useEffect(() => {
    void refresh().catch(fail);
    channel.current = new BroadcastChannel("wiley-ui");
    channel.current.onmessage = (event) => {
      if (event.data.type === "settings") {
        const epoch = dataEpoch.current;
        const configEpoch = settingsEpoch.current;
        void request<Settings>("/settings")
          .then((config) => {
            if (epoch === dataEpoch.current) {
              if (configEpoch === settingsEpoch.current) acceptSettings(config);
              void refreshModels().catch(fail);
            }
          })
          .catch(fail);
      }
      if (event.data.type === "speaking")
        reportSpeech(
          String(event.data.id || "legacy"),
          Boolean(event.data.value),
          false,
        );
      if (event.data.type === "interrupt-speech") interruptLocal();
      if (
        event.data.type === "speech-state-request" &&
        speechAbort.current &&
        !speechAbort.current.signal.aborted
      )
        channel.current?.postMessage({
          type: "speaking",
          id: localSpeechId.current,
          value: true,
        });
      if (event.data.type === "draft") {
        setDraft(String(event.data.text));
        setTab("chat");
      }
      if (event.data.type === "stop") stop();
      if (event.data.type === "chat-selected")
        void selectChat(String(event.data.id), false).catch(fail);
      if (event.data.type === "spaces-changed") {
        dataEpoch.current++;
        memoryRefreshEpoch.current++;
        setRestoredVersion((value) => value + 1);
        void refresh().catch(fail);
      }
      if (event.data.type === "chat-updated") {
        const epoch = dataEpoch.current;
        void request<Message[]>(messagePath(activeChatRef.current))
          .then((history) => {
            if (epoch === dataEpoch.current) setMessages(history);
          })
          .catch(fail);
        void refreshMemories().catch(fail);
        void request<Chat[]>("/conversations").then(setChats).catch(fail);
      }
      if (event.data.type === "memory-changed")
        void refreshMemories().catch(fail);
      if (event.data.type === "documents-changed")
        void refreshDocuments().catch(fail);
    };
    channel.current.postMessage({ type: "speech-state-request" });
    const offStop = window.wiley.onStop(stop);
    const offConversation = window.wiley.onConversation(setConversation);
    void window.wiley.conversationState().then(setConversation).catch(fail);
    const offReminder = window.wiley.onReminder((title) => {
      setNotice("Напоминание: " + title);
      window.dispatchEvent(new Event("wiley-data-updated"));
    });
    const offOffline = window.wiley.onOffline(() => {
      stop();
      setError("Ядро остановилось. Перезапустите WileyAI.");
    });
    const offRestored = window.wiley.onDataRestored(() => {
      resetHistory();
      setHistorySearch(null);
      setReplyLimit("");
      settingsEpoch.current++;
      savedSettings.current = undefined;
      for (const key of Object.keys(localStorage))
        if (key.startsWith("wiley-attachments-")) localStorage.removeItem(key);
      dataEpoch.current++;
      stop();
      setSelectedDocs([]);
      setDraft("");
      chatDrafts.current.clear();
      setApiKey("");
      setKeyTouched(false);
      setSearchKey("");
      setSearchKeyTouched(false);
      setSearchNext(false);
      setAlias({ name: "", kind: "folder", target: "" });
      setRestoredVersion((value) => value + 1);
      setError("");
      memoryRefreshEpoch.current++;
      void refresh().catch(fail);
      window.dispatchEvent(new Event("wiley-data-updated"));
    });
    return () => {
      offStop();
      offConversation();
      offReminder();
      offOffline();
      offRestored();
      channel.current?.close();
      audioStream.current?.getTracks().forEach((track) => track.stop());
      const current = conversationRef.current;
      conversationRef.current = null;
      if (current)
        void current.session
          .stop()
          .finally(() => window.wiley.releaseConversation(current.lease));
      conversationEpoch.current++;
      const starting = conversationStarting.current;
      conversationStarting.current = null;
      if (starting) {
        starting.controller.abort();
        void window.wiley.releaseConversation(starting.lease);
      }
    };
  }, [refresh, refreshMemories, refreshDocuments, selectChat, stop]);
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

  function saveVoice(patch: Partial<SpeechSettings>) {
    setSettings((current) => {
      if (!current) return current;
      // A service switch restores its full profile on the server. Keep the old
      // form disabled until that response arrives, rather than mixing services.
      if (patch.tts_service && patch.tts_service !== current.tts_service)
        return current;
      return { ...current, ...patch };
    });
    const version = ++voiceSaveVersion.current;
    setVoiceSaving(true);
    const pending = voiceSave.current
      .catch(() => {})
      .then(async () => {
        const config = await request<Settings>(
          "/settings/speech",
          "PUT",
          patch,
        );
        acceptSettings(config);
        channel.current?.postMessage({ type: "settings" });
        if (version === voiceSaveVersion.current) setNotice("Голос сохранён");
      });
    voiceSave.current = pending;
    void pending.catch(fail).finally(() => {
      if (version === voiceSaveVersion.current) setVoiceSaving(false);
    });
    return pending;
  }
  function saveAppearance(patch: Partial<Appearance>) {
    setSettings((current) => (current ? { ...current, ...patch } : current));
    const version = ++appearanceVersion.current;
    setAppearanceSaving(true);
    const pending = appearanceSave.current
      .catch(() => {})
      .then(async () => {
        const config = await request<Settings>(
          "/settings/appearance",
          "PATCH",
          patch,
        );
        acceptSettings(config);
        channel.current?.postMessage({ type: "settings" });
      });
    appearanceSave.current = pending;
    void pending
      .catch((error) => {
        fail(error);
        if (version === appearanceVersion.current && savedSettings.current) {
          const saved = savedSettings.current;
          setSettings((current) =>
            current
              ? {
                  ...current,
                  ui_theme: saved.ui_theme,
                  ui_motion: saved.ui_motion,
                  ui_glass: saved.ui_glass,
                }
              : current,
          );
        }
      })
      .finally(() => {
        if (version === appearanceVersion.current) setAppearanceSaving(false);
      });
  }
  async function save(next = settings) {
    await voiceSave.current;
    await appearanceSave.current;
    if (!next) return;
    if (conversation.active)
      throw new Error("Завершите разговор перед сменой моделей и настроек.");
    const saved = await request<Settings>("/settings", "PUT", {
      ...next,
      ...(keyTouched ? { api_key: apiKey } : {}),
      ...(searchKeyTouched ? { search_api_key: searchKey } : {}),
    });
    acceptSettings(saved, false);
    setApiKey("");
    setKeyTouched(false);
    setSearchKey("");
    setSearchKeyTouched(false);
    channel.current?.postMessage({ type: "settings" });
    setNotice("Настройки сохранены");
    await refreshModels();
  }
  function startSpeech(
    config: Settings,
    signal?: AbortSignal,
    onSpeaking?: () => void | Promise<void>,
  ) {
    channel.current?.postMessage({ type: "interrupt-speech" });
    stopAudio();
    const generation = ++speechGeneration.current;
    const speechId = crypto.randomUUID();
    const output = new SpeechOutput<Blob>(
      (text, signal) =>
        audioRequest(
          text,
          config.tts_voice,
          signal,
          config.tts_engine,
          config.tts_device,
          (device) => {
            if (
              config.tts_engine === "qwen3" &&
              generation === speechGeneration.current &&
              !signal.aborted
            )
              setNotice(
                device === "cpu"
                  ? "Qwen3-TTS: озвучка подготовлена на CPU"
                  : "Qwen3-TTS: озвучка подготовлена на видеокарте",
              );
          },
          speechId,
          config.tts_engine === "cloud" ? cloudOptions(config) : undefined,
          {
            openvoice_enabled: !!usesOpenVoice(config),
            openvoice_voice: config.openvoice_voice,
          },
        ),
      async (blob, signal) => {
        await onSpeaking?.();
        if (generation === speechGeneration.current) setSpeechPhase("playing");
        try {
          await playAudio(blob, config.audio_output_device_id || "", signal);
        } finally {
          if (generation === speechGeneration.current && !signal.aborted)
            setSpeechPhase("preparing");
        }
      },
      signal,
      {
        batchCharacters:
          config.tts_engine === "qwen3" || usesOpenVoice(config)
            ? 240
            : config.tts_engine === "cloud"
              ? 300
              : 0,
        ...(config.tts_engine === "cloud"
          ? {
              firstCharacters: 180,
              firstMinimum: 24,
              firstWaitMs: 200,
            }
          : {}),
      },
    );
    localSpeechId.current = speechId;
    speechAbort.current = output.controller;
    setSpeechPhase("preparing");
    reportSpeech(speechId, true);
    void output.done.catch(fail).finally(() => {
      reportSpeech(speechId, false);
      if (generation === speechGeneration.current) {
        setSpeechPhase(null);
        speechAbort.current = null;
        localSpeechId.current = "";
      }
      void request("/voice/session/" + speechId, "DELETE").catch(() => {});
    });
    return output;
  }
  async function speak(
    text: string,
    config = settings,
    signal?: AbortSignal,
    sample = false,
  ) {
    await voiceSave.current;
    if (conversation.active && !signal)
      throw new Error("Сначала завершите текущий разговор.");
    signal?.throwIfAborted();
    if (!config) return;
    const output = startSpeech(config, signal);
    if (sample) output.whole(text);
    else output.finish(text);
    await output.done;
  }
  async function send(
    text = draft,
    options: {
      signal?: AbortSignal;
      conversation?: boolean;
      speechConfig?: Settings;
      onSpeaking?: () => void | Promise<void>;
      fullDocument?: boolean;
      webSearch?: boolean;
    } = {},
  ) {
    try {
      await voiceSave.current;
    } catch (error) {
      if (options.conversation) throw error;
      fail(error);
      return "";
    }
    if (options.signal?.aborted)
      throw new DOMException("Ответ отменён", "AbortError");
    if (!text.trim() || busyRef.current || chatLoadingRef.current) return "";
    if (conversation.active && !options.conversation) {
      setNotice("Завершите разговор для ручной отправки сообщения.");
      return "";
    }
    setError("");
    setDraft("");
    setAnswer("");
    setReplyLimit("");
    stopAudio();
    setBusy(true);
    setStage("Отвечает…");
    setReadingProgress(null);
    const useSearch =
      !options.conversation &&
      !options.fullDocument &&
      (options.webSearch ?? searchNext);
    if (!options.conversation) setSearchNext(false);
    busyRef.current = true;
    const controller = new AbortController();
    abort.current = controller;
    const cancel = () => controller.abort();
    options.signal?.addEventListener("abort", cancel, { once: true });
    let completed = "";
    const chatId = activeChatRef.current;
    let streamError = "";
    let userAccepted = false;
    const config = options.speechConfig || savedSettings.current || settings;
    let output: SpeechOutput<Blob> | undefined;
    const startOutput = () => {
      if (!output && config && (options.conversation || config.speak_answers))
        output = startSpeech(config, controller.signal, options.onSpeaking);
      return output;
    };
    try {
      if (historyWindow.current) {
        const latest = await request<Message[]>(scoped("/messages", chatId));
        controller.signal.throwIfAborted();
        resetHistory();
        setMessages(latest);
      }
      await stream(
        text,
        selectedDocs,
        controller.signal,
        (event) => {
          if (chatId !== activeChatRef.current) return;
          if (event.type === "user" && event.message) {
            userAccepted = true;
            setScrollRequest((value) => value + 1);
            setMessages((items) => [...items, event.message!]);
          }
          if (event.type === "delta" && event.text) {
            setAnswer((value) => value + event.text);
            startOutput()?.push(event.text);
          }
          if (event.type === "stage") setStage(event.text || "Отвечает…");
          if (
            event.type === "progress" &&
            event.phase &&
            event.current !== undefined &&
            event.total !== undefined
          ) {
            setStage("Читаю документ…");
            setReadingProgress({
              phase: event.phase,
              current: event.current,
              total: event.total,
              text: event.text || "Чтение документа",
            });
          }
          if (event.type === "limit")
            setReplyLimit(event.text || "Ответ достиг лимита длины.");
          if (event.type === "error") {
            streamError = event.text || "Ошибка модели";
            setError(streamError);
          }
          if (event.type === "done" && event.message) {
            completed = event.message.content;
            setMessages((items) => [...items, event.message!]);
            setAnswer("");
          }
        },
        options.conversation ? "conversation" : "text",
        useSearch,
        chatId,
        !!options.fullDocument,
      );
      if (streamError) throw new Error(streamError);
      if (controller.signal.aborted)
        throw new DOMException("Ответ отменён", "AbortError");
      if (completed) startOutput()?.finish(completed);
      else output?.cancel();
      if (options.conversation) {
        setBusy(false);
        busyRef.current = false;
        await output?.done;
      }
      return completed;
    } catch (error) {
      output?.cancel();
      if (options.conversation) throw error;
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        if (
          !userAccepted &&
          chatId === activeChatRef.current &&
          !draftRef.current
        )
          setDraft(text);
        if (!userAccepted) void refreshDocuments().catch(() => {});
        fail(error);
      }
      return "";
    } finally {
      options.signal?.removeEventListener("abort", cancel);
      if (controller.signal.aborted && chatId === activeChatRef.current) {
        const epoch = dataEpoch.current;
        try {
          const history = await request<Message[]>(scoped("/messages", chatId));
          if (epoch === dataEpoch.current && chatId === activeChatRef.current)
            setMessages(history);
        } catch {
          /* The core may be shutting down. */
        }
      }
      setBusy(false);
      setReadingProgress(null);
      busyRef.current = false;
      setAnswer("");
      abort.current = null;
      void refreshMemories().catch(fail);
      void request<Chat[]>("/conversations").then(setChats).catch(fail);
      channel.current?.postMessage({ type: "chat-updated" });
      window.dispatchEvent(new Event("wiley-data-updated"));
    }
  }
  async function toggleConversation() {
    await voiceSave.current;
    if (conversation.active) {
      await window.wiley.stopConversation();
      return;
    }
    if (
      conversationRef.current ||
      chatLoadingRef.current ||
      busyRef.current ||
      recording ||
      uploading ||
      speaking
    )
      throw new Error("Дождитесь текущего действия перед началом разговора.");
    const epoch = ++conversationEpoch.current;
    const lease = await window.wiley.acquireConversation();
    const controller = new AbortController();
    if (epoch !== conversationEpoch.current) {
      await window.wiley.releaseConversation(lease);
      return;
    }
    conversationStarting.current = { lease, controller };
    let session: Conversation | null = null;
    try {
      const config = await request<Settings>(
        "/settings",
        "GET",
        undefined,
        controller.signal,
      );
      if (epoch !== conversationEpoch.current) return;
      session = new Conversation({
        capture: new Microphone(
          config.audio_input_device_id,
          config.stt_environment === "music",
        ),
        listenWhileThinking: config.conversation_listen_while_thinking,
        onPending: (count, full) => {
          if (count)
            setNotice(
              full
                ? "Очередь заполнена: 3 фразы. Дождитесь обработки; следующие фразы пока не сохраняются."
                : `Следующая фраза сохранена. В очереди: ${count}. Обработаю после текущего ответа.`,
            );
          else
            setNotice((value) =>
              /^(?:Следующая фраза сохранена\.|Очередь заполнена:)/.test(value)
                ? ""
                : value,
            );
        },
        speech: {
          threshold: config.conversation_threshold,
          silenceMs: config.conversation_silence_ms,
          noiseCalibrationMs: config.stt_environment === "music" ? 600 : 0,
        },
        prepare: async (signal) => {
          await request("/voice/prepare", "POST", undefined, signal);
        },
        onPhase: (phase) => {
          if (phase === "idle") void window.wiley.releaseConversation(lease);
          else void window.wiley.updateConversation(lease, phase);
        },
        onError: (error) => {
          if (conversationRef.current?.session === session)
            conversationRef.current = null;
          fail(error);
        },
        onTurn: async (audio, signal, phase) => {
          const data = new FormData();
          data.append("file", audio, "utterance.wav");
          const result = await request<{ text: string }>(
            "/voice/transcribe",
            "POST",
            data,
            signal,
          );
          if (signal.aborted)
            throw new DOMException("Разговор остановлен", "AbortError");
          const text = result.text.trim();
          if (!text) return;
          if (
            ["заверши разговор", "выключи режим разговора"].includes(
              text.toLowerCase().replace(/[.!?]+$/, ""),
            )
          ) {
            await endConversation();
            setNotice("Разговор завершён.");
            return;
          }
          phase("thinking");
          const turnConfig = await request<Settings>(
            "/settings",
            "GET",
            undefined,
            signal,
          );
          const completed = await send(text, {
            signal,
            conversation: true,
            speechConfig: turnConfig,
            onSpeaking: async () => {
              await session?.waitForPhrase(signal);
              signal.throwIfAborted();
              phase("speaking");
            },
          });
          if (signal.aborted)
            throw new DOMException("Разговор остановлен", "AbortError");
          if (!completed)
            throw new Error("Ответ не получен. Начните разговор заново.");
        },
      });
      conversationStarting.current = null;
      conversationRef.current = { session, lease };
      await session.start();
    } catch (error) {
      const cancelled =
        controller.signal.aborted || epoch !== conversationEpoch.current;
      if (!cancelled) {
        await endConversation();
        throw error;
      }
    } finally {
      if (conversationStarting.current?.lease === lease)
        conversationStarting.current = null;
      if (!session?.active) await window.wiley.releaseConversation(lease);
    }
  }
  function interruptConversation() {
    interruptLocal();
    channel.current?.postMessage({ type: "interrupt-speech" });
  }
  async function toggleRecording() {
    if (recording) {
      recorder.current?.stop();
      return;
    }
    if (chatLoadingRef.current) return;
    if (conversation.active || conversationRef.current)
      throw new Error("Сначала завершите режим разговора.");
    if (!voice.available)
      throw new Error(
        "Сначала установите компонент Whisper в разделе «Модели → Компоненты», затем перезапустите приложение.",
      );
    if (!voice.installed_stt.includes(settings!.stt_model))
      throw new Error("Скачайте выбранную модель Whisper в разделе «Модели».");
    stopAudio();
    const generation = ++manualGeneration.current;
    manualDiscard.current = false;
    const controller = new AbortController();
    manualAbort.current = controller;
    const config = await request<Settings>(
      "/settings",
      "GET",
      undefined,
      controller.signal,
    );
    controller.signal.throwIfAborted();
    if (generation !== manualGeneration.current) return;
    const media = await navigator.mediaDevices
      .getUserMedia(
        microphoneConstraints(
          config.audio_input_device_id,
          config.stt_environment === "music",
        ),
      )
      .catch((error) => {
        throw microphoneError(error);
      });
    if (generation !== manualGeneration.current) {
      media.getTracks().forEach((track) => track.stop());
      return;
    }
    audioStream.current = media;
    const audio = new MediaRecorder(media, { mimeType: "audio/webm" });
    recorder.current = audio;
    const chunks: BlobPart[] = [];
    audio.ondataavailable = (event) => chunks.push(event.data);
    audio.onstop = () => {
      media.getTracks().forEach((track) => track.stop());
      setRecording(false);
      if (manualDiscard.current || generation !== manualGeneration.current)
        return;
      setUploading(true);
      setUploadKind("speech");
      const data = new FormData();
      data.append(
        "file",
        new Blob(chunks, { type: "audio/webm" }),
        "speech.webm",
      );
      request<{ text: string }>(
        "/voice/transcribe",
        "POST",
        data,
        controller.signal,
      )
        .then((result) => {
          if (
            controller.signal.aborted ||
            generation !== manualGeneration.current
          )
            return;
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

  const activity: {
    id: string;
    kind: ProcessKind;
    label: string;
    detail?: string;
  }[] = [];
  if (busy && (tab !== "chat" || view === "avatar"))
    activity.push({
      id: "brain",
      kind: readingProgress
        ? "document"
        : /ищу|поиск/i.test(stage)
          ? "search"
          : "brain",
      label: stage || "Готовлю ответ…",
    });
  if (speaking)
    activity.push({
      id: "voice",
      kind: speechPhase === "playing" ? "voice" : "brain",
      label:
        speechPhase === "playing"
          ? "Озвучиваю ответ"
          : speechPhase === "preparing"
            ? "Готовлю озвучку…"
            : "Озвучка в другом окне",
      detail:
        speechPhase === "preparing"
          ? "Ожидаю готовую фразу и звук"
          : "Escape — остановить",
    });
  if (
    recording ||
    (conversation.active &&
      conversation.owner &&
      ["listening", "hearing"].includes(conversation.phase))
  )
    activity.push({
      id: "listen",
      kind: "listen",
      label: "Слушаю вас",
      detail: "Микрофон включён",
    });
  if (uploading)
    activity.push({
      id: "upload",
      kind: uploadKind === "speech" ? "voice" : "upload",
      label: uploadKind === "speech" ? "Распознаю речь…" : "Добавляю документ…",
    });
  if (voiceDownloading)
    activity.push({
      id: "voice-download",
      kind: "download",
      label: "Загружаю голосовую модель…",
    });
  if (jobs.some((job) => ["queued", "running"].includes(job.status)))
    activity.push({
      id: "model-download",
      kind: "download",
      label: "Загрузка модели",
      detail: "Ход загрузки — в разделе «Модели»",
    });

  if (!settings)
    return (
      <div className="loading">
        <div className="logo-mark">W</div>
        <p>Запускаю локальное ядро…</p>
        <ProcessStatus kind="brain" label="Подключаю компоненты…" compact />
        {error && <p role="alert">{error}</p>}
      </div>
    );
  if (setupOpen && setup)
    return (
      <SetupWizard
        initial={setup}
        initialSettings={settings}
        onSaved={(config) => {
          acceptSettings(config);
          channel.current?.postMessage({ type: "settings" });
        }}
        onClose={() => {
          setSetupOpen(false);
          void refresh().catch(fail);
        }}
      />
    );
  if (view === "avatar")
    return (
      <div className="pet-window">
        <div className="pet-drag">
          <span>◈ {settings.name}</span>
        </div>
        <Avatar path={settings.avatar_path} speaking={speaking} />
        {activity.slice(0, 2).map((item) => (
          <ProcessStatus key={item.id} {...item} compact />
        ))}
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <div className="pet-actions">
          <button onClick={() => window.wiley.showWindow("chat")}>
            Открыть чат
          </button>
          <button
            disabled={conversation.active}
            onClick={() => run(toggleRecording)}
          >
            {recording ? "■ Стоп" : "● Голос"}
          </button>
          <button
            title="Вернуть управление можно через иконку в трее или Ctrl+Shift+Esc"
            onClick={() => window.wiley.clickThrough(true)}
          >
            Пропуск кликов
          </button>
          <button
            className="pet-settings"
            title="Настройки"
            aria-label="Открыть настройки"
            onClick={() => window.wiley.showWindow("settings")}
          >
            <span aria-hidden="true">⚙</span>
          </button>
        </div>
        <ConversationControl
          compact
          state={conversation}
          speaking={speaking}
          onToggle={() => run(toggleConversation)}
          onInterrupt={interruptConversation}
          disabled={busy || recording || uploading || speaking}
        />
        <p className="pet-note">
          {conversation.active ? (
            conversation.owner ? (
              phaseLabels[conversation.phase]
            ) : (
              "Разговор в другом окне"
            )
          ) : recording ? (
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
    <div
      className={"app-shell " + (sidebarCollapsed ? "sidebar-collapsed" : "")}
    >
      {settings.ui_theme === "nebula" && (
        <NebulaBackground motion={settings.ui_motion} />
      )}
      <aside className="sidebar">
        <div className="brand">
          <div className="logo-mark">W</div>
          <div className="brand-text">
            Wiley<span>AI</span>
            <small>PERSONAL ASSISTANT</small>
          </div>
        </div>
        <nav>
          {tabs.map((item) => (
            <button
              key={item.id}
              className={tab === item.id ? "nav-item active" : "nav-item"}
              aria-label={item.icon + " " + item.label}
              title={item.label}
              onClick={() => {
                setTab(item.id);
                setError("");
              }}
            >
              <span>{item.icon}</span>
              <b className="nav-label">{item.label}</b>
              {item.id === "memory" && <small>{memories.length}</small>}
            </button>
          ))}
        </nav>
        <ChatSpaces
          chats={chats}
          projects={projects}
          active={activeChatId}
          disabled={
            busy || conversation.active || uploading || recording || chatLoading
          }
          onSelect={selectChat}
          onChanged={spacesChanged}
          onError={fail}
          onSearch={() => setHistorySearch({ scope: "space" })}
        />
        <div className="sidebar-bottom">
          <button
            className="subtle"
            aria-label="Показать аватара"
            title="Показать аватара"
            onClick={() => window.wiley.showWindow("avatar")}
          >
            ◈ <span>Показать аватара</span>
          </button>
          <button className="subtle" onClick={() => window.wiley.quit()}>
            Выйти из WileyAI
          </button>
        </div>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <button
            className="panel-toggle"
            aria-label={
              sidebarCollapsed
                ? "Развернуть левую панель"
                : "Свернуть левую панель"
            }
            title={
              sidebarCollapsed
                ? "Развернуть левую панель"
                : "Свернуть левую панель"
            }
            onClick={() => {
              setSidebarCollapsed(!sidebarCollapsed);
              localStorage.setItem(
                "wiley-sidebar-collapsed",
                String(!sidebarCollapsed),
              );
            }}
          >
            ☰
          </button>
          <div className="breadcrumb">
            {tab === "chat" ? currentProject?.name || "Общие чаты" : "WileyAI"}{" "}
            <span>/</span> {tabs.find((item) => item.id === tab)?.label}
          </div>
          {activity.filter(
            (item) =>
              item.id !== "listen" &&
              (!conversation.active || item.id !== "voice"),
          ).length > 0 && (
            <div
              className="activity-dock"
              aria-label="Текущие процессы"
              title={activity.map((item) => item.label).join(" · ")}
            >
              <ProcessStatus
                {...activity.find(
                  (item) =>
                    item.id !== "listen" &&
                    (!conversation.active || item.id !== "voice"),
                )!}
                compact
              />
              {activity.length > 1 && (
                <small className="activity-count">+{activity.length - 1}</small>
              )}
            </div>
          )}
          {tab === "chat" && (
            <button
              className="panel-toggle"
              aria-label={
                companionOpen
                  ? "Свернуть панель аватара"
                  : "Развернуть панель аватара"
              }
              title={
                companionOpen
                  ? "Свернуть панель аватара"
                  : "Развернуть панель аватара"
              }
              onClick={() => {
                setCompanionOpen(!companionOpen);
                localStorage.setItem(
                  "wiley-companion-open",
                  String(!companionOpen),
                );
              }}
            >
              ◈
            </button>
          )}
          <div className="global-controls" aria-label="Общие инструменты">
            <button
              className="outline global-search"
              aria-label="Открыть поиск"
              title="Поиск по истории и в интернете · Ctrl+F"
              disabled={
                busy ||
                conversation.active ||
                chatLoading ||
                recording ||
                uploading
              }
              onClick={() =>
                setHistorySearch({ scope: tab === "chat" ? "chat" : "space" })
              }
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                aria-hidden="true"
              >
                <circle cx="10.5" cy="10.5" r="6.5" />
                <path d="m16 16 5 5" />
              </svg>
              <span>Поиск</span>
            </button>
            <ConversationControl
              toolbar
              state={conversation}
              speaking={speaking}
              onToggle={() => run(toggleConversation)}
              onInterrupt={interruptConversation}
              disabled={
                busy || recording || uploading || speaking || chatLoading
              }
            />
          </div>
          <ThemeSwitch value={settings} onChange={saveAppearance} />
          {tab !== "monitor" && (
            <ResourceBadge onOpen={() => setTab("monitor")} />
          )}
          <div className={"connection " + (connected ? "online" : "")}>
            <i />
            {connected ? settings.model : "Модель не подключена"}
          </div>
        </header>
        <UpdateNotice />
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
              <div className="chat-toolbar">
                <div>
                  <h1>{currentChat?.title || "Новый чат"}</h1>
                  <small>{scopeName}</small>
                </div>
              </div>
              {historyWindowVisible && (
                <div className="history-window-banner">
                  <span>
                    Показан фрагмент переписки вокруг найденного сообщения
                  </span>
                  <button
                    className="subtle"
                    disabled={busy || chatLoading || conversation.active}
                    onClick={() => void run(returnToLatest)}
                  >
                    Вернуться к последним сообщениям
                  </button>
                </div>
              )}
              <ChatMessages
                chat={activeChatId}
                requestKey={scrollRequest}
                target={historyFocus}
                onLatest={
                  historyWindowVisible
                    ? () => void run(returnToLatest)
                    : undefined
                }
              >
                {chatLoading && (
                  <ProcessStatus
                    kind="document"
                    label="Загружаю чат…"
                    compact
                  />
                )}
                {!chatLoading && !messages.length && (
                  <div className="welcome">
                    <h2>Привет, я {settings.name}.</h2>
                    <p>
                      Можно просто поговорить. А знакомые команды
                      <br />я выполню даже без подключения нейросети.
                    </p>
                    <div className="suggestions">
                      {[
                        "Открой загрузки",
                        "Запомни: я предпочитаю короткие ответы",
                        "Напомни завтра в 10 купить хлеб",
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
                    className={
                      "message " +
                      message.role +
                      (historyFocus?.id === message.id ? " history-hit" : "")
                    }
                    data-message-id={message.id}
                    tabIndex={historyFocus?.id === message.id ? -1 : undefined}
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
                      <div className="message-text">
                        {historyFocus?.id === message.id
                          ? historyParts(
                              message.content,
                              historyFocus.terms,
                            ).map((part, index) =>
                              part.match ? (
                                <mark data-history-match key={index}>
                                  {part.text}
                                </mark>
                              ) : (
                                part.text
                              ),
                            )
                          : message.content}
                      </div>
                      {message.role === "assistant" &&
                        message.id === messages.at(-1)?.id &&
                        !busy &&
                        !historyWindowVisible && (
                          <div className="button-row">
                            <button
                              className="subtle"
                              disabled={conversation.active || chatLoading}
                              onClick={() =>
                                void send(
                                  "Продолжи предыдущий ответ с места остановки, без повторения уже написанного.",
                                )
                              }
                            >
                              Продолжить ответ
                            </button>
                            {replyLimit && (
                              <small role="status">{replyLimit}</small>
                            )}
                          </div>
                        )}
                      <SearchSources
                        message={message}
                        onError={fail}
                        onNotice={setNotice}
                      />
                      <DocumentContext message={message} />
                      {Boolean(message.memory_context?.length) && (
                        <details className="memory-context">
                          <summary>Передано в контекст из памяти</summary>
                          <ul>
                            {message.memory_context!.map((item) => (
                              <li key={item.id}>{item.content}</li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </div>
                  </article>
                ))}
                {busy && (
                  <article className="message assistant" aria-busy="true">
                    <div className="message-avatar">W</div>
                    <div className="message-body">
                      <div className="message-meta">
                        {settings.name}
                        <span className="thinking">{stage}</span>
                      </div>
                      <div className="message-text">
                        <ProcessStatus
                          kind={
                            readingProgress
                              ? "document"
                              : /ищу|поиск/i.test(stage)
                                ? "search"
                                : "brain"
                          }
                          label={stage || "Готовлю ответ…"}
                          detail={
                            answer
                              ? "Ответ появляется по мере готовности"
                              : "Обрабатываю запрос"
                          }
                          compact={Boolean(answer)}
                        />
                        {readingProgress && (
                          <DocumentReadingProgress
                            value={readingProgress}
                            onStop={stop}
                          />
                        )}
                        {answer}
                      </div>
                    </div>
                  </article>
                )}
                <MemorySuggestions
                  key={restoredVersion}
                  compact
                  memories={memories}
                  conversationId={activeChatId}
                  candidates={memoryCandidates}
                  onChanged={memoryChanged}
                  onError={fail}
                  onOpen={() => setTab("memory")}
                />
              </ChatMessages>
              {selectedDocs.length > 0 && (
                <div className="document-strip">
                  {documents
                    .filter((doc) => selectedDocs.includes(doc.id))
                    .map((doc) => (
                      <div
                        className={
                          "doc-chip " +
                          (selectedDocs.includes(doc.id) ? "selected" : "")
                        }
                        key={doc.id}
                      >
                        <button
                          title="Открыть библиотеку документов"
                          aria-label={"▤ " + doc.name}
                          onClick={() => setTab("documents")}
                        >
                          ▤ {doc.name}
                          <small>
                            {" "}
                            · {doc.characters.toLocaleString("ru-RU")} символов
                            текста
                          </small>
                        </button>
                        <button
                          aria-label={"Убрать из вопроса " + doc.name}
                          disabled={busy || conversation.active || chatLoading}
                          onClick={() => toggleDocument(doc)}
                        >
                          ×
                        </button>
                      </div>
                    ))}
                  <button
                    type="button"
                    className="outline full-document-button"
                    disabled={
                      busy ||
                      recording ||
                      uploading ||
                      conversation.active ||
                      chatLoading
                    }
                    title="Последовательно прочитать все части выбранных файлов. Для большой книги это может занять длительное время; облачная модель расходует свой тариф."
                    onClick={() =>
                      void send(
                        draft.trim() ||
                          "Перескажи целиком прикреплённые документы, сохрани порядок событий и объясни, чем заканчивается текст.",
                        { fullDocument: true },
                      )
                    }
                  >
                    Пересказать целиком
                  </button>
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
                    disabled={conversation.active || chatLoading}
                    placeholder={
                      chatLoading
                        ? "Загружаю чат…"
                        : conversation.active
                          ? "Идёт голосовой разговор…"
                          : recording
                            ? "Идёт запись с микрофона…"
                            : searchNext
                              ? "Что найти в интернете?"
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
                        disabled={
                          uploading || conversation.active || chatLoading
                        }
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
                        disabled={
                          busy ||
                          uploading ||
                          conversation.active ||
                          (!recording && chatLoading)
                        }
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
                    <button
                      type="button"
                      className={
                        "search-toggle " + (searchNext ? "selected" : "")
                      }
                      aria-label="Поиск в интернете для следующего сообщения"
                      aria-pressed={searchNext}
                      disabled={busy || conversation.active || recording}
                      onClick={() => {
                        if (!settings.search_enabled) {
                          setSettingsSection("search");
                          setTab("settings");
                          setNotice(
                            "Подключите поисковый сервис и разрешите веб-поиск в настройках.",
                          );
                        } else setSearchNext((value) => !value);
                      }}
                    >
                      ⌕ Поиск
                    </button>
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
                        disabled={
                          !draft.trim() ||
                          recording ||
                          conversation.active ||
                          chatLoading
                        }
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
                  <span>{scopeName}</span>
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
                  setUploadKind("document");
                  void run(async () => {
                    const data = new FormData();
                    data.append("file", file);
                    const chatId = activeChatRef.current;
                    const doc = await request<Doc>(
                      scoped("/documents", chatId),
                      "POST",
                      data,
                    );
                    if (chatId !== activeChatRef.current) return;
                    const canAttach = selectedDocsRef.current.length < 10;
                    toggleDocument(doc);
                    channel.current?.postMessage({ type: "documents-changed" });
                    setNotice(
                      canAttach
                        ? "Документ добавлен. Задайте вопрос по содержимому."
                        : "Документ загружен. Для вопроса можно выбрать до 10 файлов в разделе «Документы».",
                    );
                  }).finally(() => setUploading(false));
                  event.target.value = "";
                }}
              />
            </section>
            {companionOpen && (
              <aside className="companion-panel">
                <div className="companion-title">
                  <span>ВАШ АССИСТЕНТ</span>
                  <span className="live-dot" />
                  <button
                    className="panel-toggle"
                    aria-label="Скрыть аватара"
                    onClick={() => {
                      setCompanionOpen(false);
                      localStorage.setItem("wiley-companion-open", "false");
                    }}
                  >
                    ×
                  </button>
                </div>
                <Avatar path={settings.avatar_path} speaking={speaking} />
                <h2>{settings.name}</h2>
                <p>
                  {speaking
                    ? "Говорю с вами"
                    : busy
                      ? "Обдумываю ответ"
                      : settings.grammatical_gender === "feminine"
                        ? "Готова помочь"
                        : settings.grammatical_gender === "masculine"
                          ? "Готов помочь"
                          : "На связи"}
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
                  onClick={() => {
                    setSettingsSection("personality");
                    setTab("settings");
                  }}
                >
                  Настроить персонажа
                </button>
                <div className="tip">
                  <span>ПОДСКАЗКА</span>
                  <p>
                    «Запомни: …» — сохранит важное. Вы всегда можете посмотреть
                    и удалить записи.
                  </p>
                </div>
              </aside>
            )}
          </div>
        )}

        {tab === "monitor" && <MonitorPanel />}
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
            <ComponentPanel
              onReady={() =>
                void run(async () => {
                  await refreshModels();
                })
              }
            />
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
                          : item.engine === "silero_v5_6"
                            ? voice.silero_v5_6_installed
                            : item.engine === "qwen3"
                              ? voice.qwen3_installed
                              : item.engine === "piper"
                                ? voice.piper_available &&
                                  voice.piper_voices?.some(
                                    (v) => v.name === item.voice && v.installed,
                                  )
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
                                  tts_voice: item.voice || "",
                                  openvoice_enabled: false,
                                });
                                setSettingsSection("speech");
                                setTab("settings");
                              })
                            }
                          >
                            Выбрать голос
                          </button>
                        ) : ready ? (
                          <button
                            className="outline"
                            disabled={busy || conversation.active}
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
                          disabled={busy || conversation.active}
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
          <Productivity
            key={tab + restoredVersion + activeChatId}
            mode={tab}
            conversationId={activeChatId}
            onError={fail}
          />
        )}
        {tab === "documents" && activeChatId && !chatLoading && (
          <DocumentPanel
            key={restoredVersion + activeChatId + scopeName}
            conversationId={activeChatId}
            projectName={currentProject?.name}
            selected={selectedDocs}
            disabled={
              busy ||
              conversation.active ||
              uploading ||
              recording ||
              chatLoading
            }
            onToggle={toggleDocument}
            onChanged={documentsChanged}
            onChat={() => setTab("chat")}
            onError={fail}
          />
        )}
        {tab === "calendar" && activeChatId && !chatLoading && (
          <CalendarPanel
            key={restoredVersion + activeChatId + scopeName}
            conversationId={activeChatId}
            scopeName={scopeName}
            onError={fail}
          />
        )}
        {tab === "capabilities" && <Capabilities onError={fail} />}

        {tab === "memory" && (
          <MemoryPanel
            key={restoredVersion + activeChatId + scopeName}
            memories={memories}
            conversationId={activeChatId}
            scopeName={scopeName}
            candidates={memoryCandidates}
            onChanged={memoryChanged}
            onError={fail}
            suggestionsEnabled={settings.memory_suggestions}
          />
        )}

        {tab === "commands" && (
          <section className="page scroll-page">
            <div className="page-heading">
              <div>
                <span className="eyebrow">ПОНЯТНЫЕ ДЕЙСТВИЯ</span>
                <h1>Команды и сценарии</h1>
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
            <Applications
              aliases={aliasList}
              disabled={busy || conversation.active || recording || uploading}
              onError={fail}
              onChanged={async () =>
                setAliasList(
                  (await request<{ custom: Alias[] }>("/aliases")).custom,
                )
              }
            />
            <ToolAccess
              onError={fail}
              onSaved={async () => {
                acceptSettings(await request<Settings>("/settings"));
                channel.current?.postMessage({ type: "settings" });
              }}
            />
            <DeviceAudio />
            <YandexMusic
              onChanged={async () => {
                acceptSettings(await request<Settings>("/settings"));
                channel.current?.postMessage({ type: "settings" });
              }}
            />
            <ActionLog />
            <RoutinePanel
              key={activeChatId + ":" + restoredVersion}
              conversationId={activeChatId}
              scopeName={scopeName}
              aliasesVersion={JSON.stringify(aliasList)}
              disabled={
                busy ||
                conversation.active ||
                recording ||
                uploading ||
                chatLoading
              }
              onError={fail}
              onRun={async (text) => {
                setTab("chat");
                await send(text);
              }}
            />
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
          <section className="page scroll-page settings-page">
            <div className="page-heading settings-heading">
              <div>
                <h1>Настройки ассистента</h1>
                <p>
                  Выберите раздел. Черновики сохраняются при переходе между
                  разделами.
                </p>
              </div>
              <button
                className="primary"
                disabled={
                  busy || conversation.active || voiceSaving || appearanceSaving
                }
                onClick={() => run(() => save())}
              >
                Сохранить
              </button>
            </div>
            <div className="settings-shell">
              <SettingsNavigation
                active={settingsSection}
                onChange={setSettingsSection}
              />
              <div className="settings-content">
                <div
                  id="settings-panel-appearance"
                  role="tabpanel"
                  aria-labelledby="settings-tab-appearance"
                  hidden={settingsSection !== "appearance"}
                  className="settings-panel"
                >
                  <AppearancePanel
                    value={settings}
                    onChange={saveAppearance}
                    saving={appearanceSaving}
                  />
                </div>
                <div
                  id="settings-panel-personality"
                  role="tabpanel"
                  aria-labelledby="settings-tab-personality"
                  hidden={settingsSection !== "personality"}
                  className="settings-panel"
                >
                  <div className="card">
                    <h2>Личность</h2>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={settings.memory_suggestions}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            memory_suggestions: event.target.checked,
                          })
                        }
                      />
                      Предлагать память из разговоров
                    </label>
                    <p className="help">
                      Локальные предложения из новых реплик. Они сохраняются в
                      память только после принятия.
                    </p>
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
                      Род речи персонажа
                      <select
                        aria-label="Род речи персонажа"
                        value={settings.grammatical_gender}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            grammatical_gender: event.target
                              .value as Settings["grammatical_gender"],
                          })
                        }
                      >
                        <option value="feminine">
                          Женский · готова, поняла
                        </option>
                        <option value="masculine">
                          Мужской · готов, понял
                        </option>
                        <option value="neutral">Без указания рода</option>
                      </select>
                    </label>
                    <p className="help">
                      Определяет, как Уайли говорит о себе. Эта настройка не
                      зависит от выбранного голоса.
                    </p>
                  </div>
                </div>
                <div
                  id="settings-panel-brain"
                  role="tabpanel"
                  aria-labelledby="settings-tab-brain"
                  hidden={settingsSection !== "brain"}
                  className="settings-panel"
                >
                  <div className="card">
                    <h2>Подключение модели</h2>
                    <label>
                      Движок
                      <select
                        aria-label="Движок"
                        value={settings.provider}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            provider: event.target
                              .value as Settings["provider"],
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
                          setSettings({
                            ...settings,
                            base_url: event.target.value,
                          })
                        }
                      />
                    </label>
                    <label>
                      Идентификатор модели
                      <input
                        value={settings.model}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            model: event.target.value,
                          })
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
                    <label>
                      Максимальная длина ответа, токенов
                      <input
                        type="number"
                        min={256}
                        max={8192}
                        step={256}
                        value={settings.response_tokens}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            response_tokens: Number(event.target.value),
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
                        <option value="balanced">
                          Сбалансированный · 5 минут
                        </option>
                        <option value="quality">Качество · 15 минут</option>
                      </select>
                    </label>
                    <details className="settings-help">
                      <summary>Контекст и подключение</summary>
                      <p className="help">
                        На ответ выделяется до половины выбранного контекста.
                        Если лимит достигнут, появится пояснение и кнопка
                        продолжения. Увеличение контекста требует больше памяти.
                      </p>
                      <p className="help">
                        Сохраните настройки, затем обновите список в разделе
                        «Модели». Облако подключается только по вашему выбору.
                      </p>
                    </details>
                  </div>
                </div>
                <div
                  id="settings-panel-speech"
                  role="tabpanel"
                  aria-labelledby="settings-tab-speech"
                  hidden={settingsSection !== "speech"}
                  className="settings-panel"
                >
                  <div className="card">
                    <h2>Речь и озвучка</h2>
                    <p className="help">
                      Движок, голос и автоматическая озвучка сохраняются сразу.{" "}
                      {voiceSaving
                        ? "Сохраняю…"
                        : "Ответы читаются по мере готовности фраз."}
                    </p>
                    <label>
                      Движок озвучки
                      <select
                        aria-label="Движок озвучки"
                        value={
                          usesOpenVoice(settings)
                            ? "openvoice"
                            : settings.tts_engine
                        }
                        onChange={(event) =>
                          saveVoice(
                            selectSpeechEngine(event.target.value, settings),
                          )
                        }
                      >
                        <option value="silero">Silero · русский язык</option>
                        <option value="silero_v5_6">
                          Silero 5.6 · выразительная интонация
                        </option>
                        <option value="piper">
                          Piper · дополнительные голоса
                        </option>
                        <option value="openvoice">
                          OpenVoice · тембр Миты поверх Piper / Silero
                        </option>
                        <option value="qwen3">
                          Qwen3-TTS · экспериментальный
                        </option>
                        <option value="sapi">Системные голоса Windows</option>
                        <option value="cloud">Облачная озвучка · API</option>
                      </select>
                    </label>
                    {settings.tts_engine !== "cloud" && (
                      <label>
                        Голос ассистента
                        <select
                          aria-label="Голос ассистента"
                          value={settings.tts_voice}
                          onChange={(event) =>
                            saveVoice({
                              tts_voice: event.target.value,
                            })
                          }
                        >
                          <option value="">
                            {settings.tts_engine.startsWith("silero")
                              ? "Ксения · по умолчанию"
                              : settings.tts_engine === "piper"
                                ? "Ирина · по умолчанию"
                                : settings.tts_engine === "qwen3"
                                  ? "Serena · по умолчанию"
                                  : "Голос Windows по умолчанию"}
                          </option>
                          {(settings.tts_engine.startsWith("silero")
                            ? [
                                { name: "xenia", language: "Ксения · русский" },
                                { name: "baya", language: "Бая · русский" },
                                { name: "aidar", language: "Айдар · русский" },
                                {
                                  name: "eugene",
                                  language: "Евгений · русский",
                                },
                                {
                                  name: "kseniya",
                                  language: "Ксения, вариант · русский",
                                },
                              ]
                            : settings.tts_engine === "piper"
                              ? (voice.piper_voices || []).map((v) => ({
                                  name: v.name,
                                  language:
                                    v.label +
                                    (v.installed
                                      ? " · установлен"
                                      : " · нужно скачать"),
                                }))
                              : settings.tts_engine === "qwen3"
                                ? voice.qwen3_voices || []
                                : voice.voices
                          ).map((item) => (
                            <option key={item.name} value={item.name}>
                              {item.name} · {item.language}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    {usesOpenVoice(settings) && (
                      <OpenVoiceSettings
                        settings={settings}
                        onChange={saveVoice}
                        disabled={
                          speaking || conversation.active || voiceSaving
                        }
                        onError={fail}
                        onNotice={setNotice}
                      />
                    )}
                    {settings.tts_engine === "cloud" && (
                      <CloudSpeechSettings
                        settings={settings}
                        onChange={saveVoice}
                        flush={() => voiceSave.current}
                        disabled={
                          speaking || conversation.active || voiceSaving
                        }
                        onError={fail}
                        onNotice={setNotice}
                      />
                    )}
                    {settings.tts_engine === "qwen3" && (
                      <>
                        <label>
                          Устройство Qwen3-TTS
                          <select
                            aria-label="Устройство Qwen3-TTS"
                            value={settings.tts_device}
                            onChange={(event) =>
                              saveVoice({
                                tts_device: event.target
                                  .value as Settings["tts_device"],
                              })
                            }
                          >
                            <option value="auto">
                              Автоматически · CUDA при свободной памяти, иначе
                              CPU
                            </option>
                            <option value="cuda">
                              Видеокарта NVIDIA · CUDA
                            </option>
                            <option value="cpu">
                              Процессор · CPU, медленнее
                            </option>
                          </select>
                        </label>
                        <details className="settings-help">
                          <summary>
                            Установка и производительность Qwen3-TTS
                          </summary>
                          <p className="help">
                            {voice.qwen3_available
                              ? "Отдельный движок установлен."
                              : "Установите компонент Qwen3-TTS CPU в разделе «Модели → Компоненты»."}{" "}
                            {voice.qwen3_installed
                              ? "Веса установлены."
                              : "Скачайте веса в «Модели → Озвучка»."}{" "}
                            Для CUDA нужно минимум 3,5 ГБ свободной видеопамяти.
                            Длинные ответы читаются частями. Паузы зависят от
                            скорости подготовки следующей фразы; дополнительная
                            ОЗУ сама по себе не ускоряет синтез. В
                            автоматическом режиме занятая или недоступная
                            видеокарта заменяется CPU. Модель загружается один
                            раз на ответ и читает готовые фразы; при остановке
                            память освобождается. На CPU возможна долгая
                            подготовка. Русская речь у готовых тембров может
                            иметь акцент. Для мягкого женского голоса попробуйте
                            Serena.
                          </p>
                        </details>
                      </>
                    )}
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={settings.speak_answers}
                        onChange={(event) =>
                          saveVoice({
                            speak_answers: event.target.checked,
                          })
                        }
                      />
                      Озвучивать ответы автоматически
                    </label>
                    <button
                      className="outline"
                      disabled={speaking || conversation.active || voiceSaving}
                      onClick={() =>
                        run(() =>
                          speak(
                            "Привет! Я Уайли. Давай начнём.",
                            settings,
                            undefined,
                            true,
                          ),
                        )
                      }
                    >
                      ♪ Прослушать голос
                    </button>
                    <p className="help">
                      Escape останавливает озвучку. Ctrl+Shift+Esc работает и в
                      других приложениях. Локальные голоса скачиваются в «Модели
                      → Озвучка», облачные настраиваются выше.
                    </p>
                  </div>
                </div>
                <div
                  id="settings-panel-microphone"
                  role="tabpanel"
                  aria-labelledby="settings-tab-microphone"
                  hidden={settingsSection !== "microphone"}
                  className="settings-panel"
                >
                  <AudioDevices
                    settings={settings}
                    onChange={setSettings}
                    disabled={
                      settingsSection !== "microphone" ||
                      busy ||
                      recording ||
                      uploading ||
                      speaking ||
                      conversation.active
                    }
                  />
                  <div className="card">
                    <h2>Распознавание и разговор</h2>
                    <label>
                      Условия записи
                      <select
                        value={settings.stt_environment}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            stt_environment: event.target
                              .value as Settings["stt_environment"],
                          })
                        }
                      >
                        <option value="normal">Обычная комната</option>
                        <option value="music">Музыка и шум</option>
                      </select>
                    </label>
                    <p className="help">
                      «Музыка и шум» отключает автоусиление фона, фильтрует
                      крайние частоты микрофона разговора и строже отсекает
                      участки без речи. Первые 0,6 секунды после включения
                      разговора помолчите — измеряется фон. Громкий вокал может
                      распознаваться как речь; наушники или более тихая музыка
                      помогут больше.
                    </p>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={settings.conversation_listen_while_thinking}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            conversation_listen_while_thinking:
                              event.target.checked,
                          })
                        }
                      />
                      Слушать, пока модель думает
                    </label>
                    <p className="help">
                      Следующие фразы сохраняются в очередь (до трёх) и
                      обрабатываются после текущего ответа. Во время собственной
                      озвучки и короткой паузы после неё приём фраз
                      приостановлен. Завершение разговора или «Перебить» очищает
                      очередь. Изменения применятся после сохранения и нового
                      включения разговора.
                    </p>
                    <label>
                      Модель распознавания
                      <select
                        value={settings.stt_model}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            stt_model: event.target
                              .value as Settings["stt_model"],
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
                      Точность распознавания
                      <select
                        value={settings.stt_quality}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            stt_quality: event.target
                              .value as Settings["stt_quality"],
                          })
                        }
                      >
                        <option value="accurate">
                          Точнее · немного медленнее
                        </option>
                        <option value="balanced">
                          Баланс точности и скорости
                        </option>
                        <option value="fast">
                          Быстрее · возможны неточности
                        </option>
                      </select>
                    </label>
                    <p className="help">
                      «Точнее» проверяет больше вариантов и может работать
                      дольше. Для русского языка рекомендуем Whisper small.
                      После записи распознанный текст появится в поле сообщения:
                      его можно исправить перед отправкой.
                    </p>
                    <label>
                      Пауза до конца реплики, мс
                      <input
                        type="number"
                        min={500}
                        max={2500}
                        step={100}
                        value={settings.conversation_silence_ms}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            conversation_silence_ms: Number(event.target.value),
                          })
                        }
                      />
                    </label>
                    <label>
                      Порог голоса в режиме разговора
                      <input
                        type="number"
                        min={0.003}
                        max={0.1}
                        step={0.003}
                        value={settings.conversation_threshold}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            conversation_threshold: Number(event.target.value),
                          })
                        }
                      />
                    </label>
                    <p className="help">
                      В режиме разговора отправка и озвучка автоматические. Если
                      фразы обрываются, увеличьте паузу. При срабатывании на
                      фоновый шум увеличьте порог. Перебить ответ пока можно
                      кнопкой; голосовое перебивание ещё не включено.
                    </p>
                  </div>
                  <div className="card voice-resources">
                    <h2>Память моделей речи</h2>
                    <label>
                      Автовыгрузка Whisper, Silero и Piper
                      <select
                        aria-label="Автовыгрузка Whisper, Silero и Piper"
                        value={settings.voice_idle_timeout}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            voice_idle_timeout: event.target
                              .value as Settings["voice_idle_timeout"],
                          })
                        }
                      >
                        <option value="profile">
                          По профилю производительности
                        </option>
                        <option value="1m">Через 1 минуту простоя</option>
                        <option value="5m">Через 5 минут простоя</option>
                        <option value="15m">Через 15 минут простоя</option>
                        <option value="never">Оставлять загруженными</option>
                      </select>
                    </label>
                    <p className="help">
                      {settings.voice_idle_timeout === "profile"
                        ? `По выбранному профилю: ${{ eco: "1 минута", balanced: "5 минут", quality: "15 минут" }[settings.profile]} простоя.`
                        : settings.voice_idle_timeout === "never"
                          ? "Whisper, Silero и Piper остаются загруженными в простое."
                          : "Срок считается отдельно для распознавания, Silero и Piper."}{" "}
                      После выгрузки первое обращение займёт больше времени.
                      Нажмите «Сохранить», чтобы применить выбор.
                    </p>
                    <button
                      className="outline"
                      disabled={
                        busy ||
                        recording ||
                        speaking ||
                        conversation.active ||
                        voiceSaving
                      }
                      onClick={() =>
                        run(async () => {
                          const result = await request<{ unloaded: string[] }>(
                            "/voice/unload",
                            "POST",
                          );
                          setNotice(
                            result.unloaded.length
                              ? "Модели речи выгружены: " +
                                  result.unloaded.join(", ")
                              : "Модели речи уже выгружены",
                          );
                        })
                      }
                    >
                      Освободить память речи
                    </button>
                    <details className="settings-help">
                      <summary>Как освобождается память</summary>
                      <p className="help">
                        Модели загрузятся с диска при следующем обращении. Веса,
                        выбранные голоса и история сохраняются. Временные
                        процессы Qwen и OpenVoice управляются сессией озвучки и
                        завершаются отдельно.
                      </p>
                    </details>
                  </div>
                </div>
                <div
                  id="settings-panel-search"
                  role="tabpanel"
                  aria-labelledby="settings-tab-search"
                  hidden={settingsSection !== "search"}
                  className="settings-panel"
                >
                  <SearchSettings
                    settings={settings}
                    onChange={setSettings}
                    secret={searchKey}
                    onSecret={(value) => {
                      setSearchKey(value);
                      setSearchKeyTouched(true);
                    }}
                  />
                </div>
                <div
                  id="settings-panel-avatar"
                  role="tabpanel"
                  aria-labelledby="settings-tab-avatar"
                  hidden={settingsSection !== "avatar"}
                  className="settings-panel"
                >
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
                      <button
                        className="outline"
                        onClick={() => run(chooseAvatar)}
                      >
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
                      Ctrl + Shift + Esc — остановить ответ и озвучку, вернуть
                      клики аватару.
                    </p>
                  </div>
                </div>
                <div
                  id="settings-panel-data"
                  role="tabpanel"
                  aria-labelledby="settings-tab-data"
                  hidden={settingsSection !== "data"}
                  className="settings-panel"
                >
                  <BackupPanel
                    disabled={
                      busy ||
                      conversation.active ||
                      recording ||
                      uploading ||
                      speaking
                    }
                    onError={fail}
                    onNotice={setNotice}
                  />
                  <UpdatesPanel />
                  <div className="card setup-launcher">
                    <h2>Первоначальная настройка</h2>
                    <p className="help">
                      Подключение мозга, установка компонентов, голос и проверка
                      устройств — по шагам. Можно вернуться к месту остановки.
                    </p>
                    <button
                      className="outline"
                      disabled={
                        busy ||
                        conversation.active ||
                        recording ||
                        uploading ||
                        speaking
                      }
                      onClick={() =>
                        void run(async () => {
                          const current =
                            await request<SetupProgress>("/setup");
                          const value = await request<SetupProgress>(
                            "/setup",
                            "PUT",
                            {
                              active: true,
                              ...(current.completed || current.step === 0
                                ? {
                                    completed: false,
                                    step: 0,
                                    mode:
                                      settings.provider === "ollama"
                                        ? "local"
                                        : "cloud",
                                    voice_mode: settings.speak_answers
                                      ? "keep"
                                      : "text",
                                  }
                                : {}),
                            },
                          );
                          setSetup(value);
                          setSetupOpen(true);
                        })
                      }
                    >
                      Открыть мастер настройки
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}
      </main>
      {historySearch && activeChatId && (
        <HistorySearch
          chat={activeChatId}
          project={
            projects.find((item) => item.id === currentChat?.project_id)?.name
          }
          initialScope={historySearch.scope}
          onClose={() => setHistorySearch(null)}
          onWebSearch={(query) => {
            setHistorySearch(null);
            if (!settings.search_enabled) {
              setSettingsSection("search");
              setTab("settings");
              setNotice(
                "Подключите поисковый сервис и разрешите веб-поиск в настройках.",
              );
            } else {
              setTab("chat");
              void send(query, { webSearch: true });
            }
          }}
          onSelect={(hit, terms) =>
            void run(() => openHistoryResult(hit, terms))
          }
          disabled={
            busy || conversation.active || chatLoading || recording || uploading
          }
        />
      )}
    </div>
  );
}
