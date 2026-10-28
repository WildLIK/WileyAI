import { useEffect, useRef, useState } from "react";
import {
  request,
  audioRequest,
  cloudOptions,
  type Settings,
  type VoiceInfo,
  type CatalogItem,
  type Job,
  errorText,
} from "./api";
import { ComponentPanel } from "./Components";
import { poll } from "./polling";
import { AudioDevices } from "./voice/AudioDevices";
import { playAudio } from "./voice/devices";

export interface SetupProgress {
  active: boolean;
  completed: boolean;
  step: number;
  mode: "local" | "cloud";
  voice_mode: "text" | "piper" | "sapi" | "keep";
  microphone: boolean;
}
type Check = {
  brain: {
    connected: boolean;
    model_available: boolean;
    models: { id: string; size: number }[];
    error: string;
  };
  speech: { recognition: boolean; synthesis: boolean; error: string };
  config: Settings;
};
const services = {
  openrouter: { name: "OpenRouter", url: "https://openrouter.ai/api/v1" },
  routerai: { name: "RouterAI", url: "https://routerai.ru/api/v1" },
  compatible: { name: "Другой совместимый API", url: "" },
};
const steps = ["Начало", "Мозг", "Голос и устройства", "Проверка"];

export function SetupWizard({
  initial,
  initialSettings,
  onSaved,
  onClose,
}: {
  initial: SetupProgress;
  initialSettings: Settings;
  onSaved: (config: Settings) => void;
  onClose: () => void;
}) {
  const [progress, setProgress] = useState(initial);
  const [config, setConfig] = useState(initialSettings);
  const matchingMode =
    (initial.mode === "local") === (initialSettings.provider === "ollama");
  const [model, setModel] = useState(
    matchingMode
      ? initialSettings.model
      : initial.mode === "local"
        ? "qwen3.5:4b"
        : "",
  );
  const [address, setAddress] = useState(
    matchingMode
      ? initialSettings.base_url
      : initial.mode === "local"
        ? "http://127.0.0.1:11434"
        : services.openrouter.url,
  );
  const [service, setService] = useState<keyof typeof services>(
    initialSettings.base_url === services.routerai.url
      ? "routerai"
      : initialSettings.base_url === services.openrouter.url
        ? "openrouter"
        : initialSettings.provider === "compatible"
          ? "compatible"
          : "openrouter",
  );
  const [key, setKey] = useState("");
  const [systemVoice, setSystemVoice] = useState(
    initialSettings.tts_engine === "sapi" ? initialSettings.tts_voice : "",
  );
  const [voice, setVoice] = useState<VoiceInfo | null>(null);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [check, setCheck] = useState<Check | null>(null);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const preview = useRef<AbortController | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const alive = useRef(true);
  const lastJob = useRef("");

  useEffect(() => {
    alive.current = true;
    void Promise.all([
      request<VoiceInfo>("/voice"),
      request<CatalogItem[]>("/catalog"),
    ])
      .then(([voices, items]) => {
        if (alive.current) {
          setVoice(voices);
          setCatalog(items);
        }
      })
      .catch((error) => {
        if (alive.current) setError(errorText(error));
      });
    const stop = () => preview.current?.abort();
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") stop();
    };
    window.addEventListener("keydown", escape);
    const unsubscribe = window.wiley.onStop(stop);
    return () => {
      alive.current = false;
      stop();
      unsubscribe();
      window.removeEventListener("keydown", escape);
    };
  }, []);
  useEffect(() => {
    heading.current?.focus();
  }, [progress.step]);
  useEffect(() => {
    if (progress.step !== 1) return;
    return poll(async (signal) => {
      const next = await request<Job[]>("/jobs", "GET", undefined, signal);
      if (!signal.aborted) setJobs(next);
    }, 1500);
  }, [progress.step]);
  const job = [...jobs].reverse().find((item) => item.model === model);
  const downloading = Boolean(
    job && ["queued", "running"].includes(job.status),
  );
  useEffect(() => {
    if (job?.status !== "done" || lastJob.current === job.id) return;
    lastJob.current = job.id;
    void request<Check>("/setup/check", "POST")
      .then((next) => {
        if (alive.current) setCheck(next);
      })
      .catch(() => {});
  }, [job?.id, job?.status]);

  async function action(label: string, work: () => Promise<void>) {
    setPending(label);
    setError("");
    setNotice("");
    preview.current?.abort();
    try {
      await work();
    } catch (error) {
      if (alive.current) setError(errorText(error));
    } finally {
      if (alive.current) setPending("");
    }
  }
  async function persist(patch: Partial<SetupProgress>) {
    const previous = progress;
    setProgress((current) => ({ ...current, ...patch }));
    try {
      const next = await request<SetupProgress>("/setup", "PUT", patch);
      if (alive.current) setProgress(next);
    } catch (error) {
      if (alive.current) setProgress(previous);
      throw error;
    }
  }
  async function save(patch: object) {
    const next = await request<Settings>("/setup/settings", "PATCH", patch);
    if (alive.current) {
      setConfig(next);
      setCheck(null);
      onSaved(next);
    }
    return next;
  }
  async function verify() {
    const next = await request<Check>("/setup/check", "POST");
    if (alive.current) {
      setCheck(next);
      setConfig(next.config);
      setVoice(await request<VoiceInfo>("/voice"));
    }
    return next;
  }
  async function saveBrain() {
    const url =
      progress.mode === "local"
        ? address
        : service === "compatible"
          ? address
          : services[service].url;
    const next = await save({
      provider: progress.mode === "local" ? "ollama" : "compatible",
      base_url: url.trim(),
      ...(model.trim() ? { model: model.trim() } : {}),
      ...(key ? { api_key: key } : {}),
    });
    setKey("");
    return next;
  }
  function voicePatch() {
    return {
      audio_input_device_id: config.audio_input_device_id,
      audio_output_device_id: config.audio_output_device_id,
      stt_model: config.stt_model,
      ...(progress.voice_mode === "keep"
        ? {}
        : progress.voice_mode === "text"
          ? { speak_answers: false }
          : {
              tts_engine: progress.voice_mode,
              tts_voice:
                progress.voice_mode === "piper" ? "irina" : systemVoice,
              speak_answers: true,
              openvoice_enabled: false,
            }),
    };
  }
  async function next() {
    if (progress.step === 1) {
      if (!model.trim()) throw new Error("Укажите модель для общения");
      await saveBrain();
    }
    if (progress.step === 2) await save(voicePatch());
    await persist({ step: progress.step + 1 });
    if (progress.step === 2) await verify();
  }
  async function downloadVoice(id: string) {
    await request("/voice/download", "POST", { model: id });
    const next = await request<VoiceInfo>("/voice");
    if (alive.current) {
      setVoice(next);
      setNotice("Модель установлена");
    }
  }
  async function sample() {
    if (preview.current) {
      preview.current.abort();
      return;
    }
    const controller = new AbortController();
    preview.current = controller;
    setPreviewing(true);
    setError("");
    try {
      const selected = { ...config, ...voicePatch() } as Settings;
      const audio = await audioRequest(
        `Привет! Я ${selected.name}. Приятно познакомиться. Теперь мы можем общаться.`,
        selected.tts_voice,
        controller.signal,
        selected.tts_engine,
        selected.tts_device,
        undefined,
        undefined,
        cloudOptions(selected),
        {
          openvoice_enabled: selected.openvoice_enabled,
          openvoice_voice: selected.openvoice_voice,
        },
      );
      await playAudio(
        audio,
        selected.audio_output_device_id,
        controller.signal,
      );
    } catch (error) {
      if (!controller.signal.aborted && alive.current)
        setError(errorText(error));
    } finally {
      if (preview.current === controller) preview.current = null;
      if (alive.current) setPreviewing(false);
    }
  }
  const locked = Boolean(pending);
  const selectedVoice =
    progress.voice_mode === "keep" ? config.tts_engine : progress.voice_mode;
  const ready = Boolean(
    check?.brain.connected &&
    check.brain.model_available &&
    (!config.speak_answers || check.speech.synthesis) &&
    (!progress.microphone || check.speech.recognition),
  );
  const localModels = catalog.filter((item) => item.kind === "llm");
  const knownModels = Array.from(
    new Set([
      ...(check?.brain.models ?? []).map((item) => item.id),
      ...(progress.mode === "local" ? localModels.map((item) => item.id) : []),
    ]),
  );

  return (
    <main className="setup-page">
      <div className="setup-shell">
        <header className="setup-header">
          <div className="logo-mark">W</div>
          <div>
            <span className="eyebrow">WILEYAI · ПЕРВЫЙ ЗАПУСК</span>
            <h1 ref={heading} tabIndex={-1}>
              {progress.step === 0
                ? "Давайте познакомимся"
                : steps[progress.step]}
            </h1>
          </div>
          <button
            className="subtle"
            disabled={locked}
            onClick={() =>
              void action("Сохраняю шаг…", async () => {
                await persist({ active: false });
                onClose();
              })
            }
          >
            Настроить позже
          </button>
        </header>
        <ol className="setup-steps" aria-label="Этапы первоначальной настройки">
          {steps.map((step, index) => (
            <li
              key={step}
              aria-current={index === progress.step ? "step" : undefined}
            >
              <span>{index + 1}</span>
              {step}
            </li>
          ))}
        </ol>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="notice" role="status">
            {notice}
          </p>
        )}
        {pending && (
          <div className="setup-progress" role="status">
            <span>{pending}</span>
            <progress aria-label="Выполнение настройки" />
          </div>
        )}
        <section className="setup-content" aria-label={steps[progress.step]}>
          {progress.step === 0 && (
            <>
              <h2>Как будет работать ваш ассистент?</h2>
              <p className="help">
                Начнём с мозга, затем настроим голос. Все параметры можно
                изменить позже. Веса моделей скачиваются отдельно по вашей
                команде.
              </p>
              <div className="setup-choices">
                {[
                  {
                    id: "local",
                    title: "На этом компьютере",
                    text: "Ollama и локальная модель. После скачивания можно общаться без интернета.",
                  },
                  {
                    id: "cloud",
                    title: "Через облачный API",
                    text: "OpenRouter, RouterAI или другой совместимый сервис. Нужны интернет и свой ключ.",
                  },
                ].map((item) => (
                  <label
                    key={item.id}
                    className={progress.mode === item.id ? "selected" : ""}
                  >
                    <input
                      type="radio"
                      name="setup-mode"
                      checked={progress.mode === item.id}
                      disabled={locked}
                      onChange={() =>
                        void action("Сохраняю выбор…", async () => {
                          await persist({
                            mode: item.id as SetupProgress["mode"],
                          });
                          setModel(
                            item.id === "local"
                              ? initialSettings.provider === "ollama"
                                ? initialSettings.model
                                : "qwen3.5:4b"
                              : initialSettings.provider === "compatible"
                                ? initialSettings.model
                                : "",
                          );
                          setAddress(
                            item.id === "local"
                              ? initialSettings.provider === "ollama"
                                ? initialSettings.base_url
                                : "http://127.0.0.1:11434"
                              : services[service].url,
                          );
                        })
                      }
                    />
                    <strong>{item.title}</strong>
                    <span>{item.text}</span>
                  </label>
                ))}
              </div>
              <p className="help">
                Можно начать с текста. Микрофон, голоса и аватар подключаются по
                желанию.
              </p>
            </>
          )}
          {progress.step === 1 && (
            <>
              <h2>
                {progress.mode === "local"
                  ? "Подключите локальную модель"
                  : "Подключите облачный мозг"}
              </h2>
              {progress.mode === "local" ? (
                <ComponentPanel
                  ids={["ollama"]}
                  expanded
                  onReady={() =>
                    void action("Проверяю подключение…", async () => {
                      await saveBrain();
                      await verify();
                    })
                  }
                />
              ) : (
                <label>
                  Сервис модели
                  <select
                    aria-label="Сервис модели"
                    value={service}
                    disabled={locked}
                    onChange={(event) => {
                      const selected = event.target
                        .value as keyof typeof services;
                      setService(selected);
                      setAddress(services[selected].url);
                      setKey("");
                      setCheck(null);
                      setModel("");
                    }}
                  >
                    {Object.entries(services).map(([id, item]) => (
                      <option key={id} value={id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {(progress.mode === "local" || service === "compatible") && (
                <label>
                  Адрес сервера модели
                  <input
                    aria-label="Адрес сервера модели"
                    value={address}
                    disabled={locked}
                    onChange={(event) => {
                      setAddress(event.target.value);
                      setCheck(null);
                    }}
                    placeholder="https://example.com/v1"
                  />
                </label>
              )}
              {progress.mode === "cloud" && (
                <label>
                  Ключ API для мозга
                  <input
                    aria-label="Ключ API для мозга"
                    type="password"
                    autoComplete="off"
                    value={key}
                    disabled={locked}
                    onChange={(event) => setKey(event.target.value)}
                    placeholder={
                      config.has_api_key &&
                      config.base_url ===
                        (service === "compatible"
                          ? address
                          : services[service].url)
                        ? "Ключ уже сохранён в Windows"
                        : "Введите ключ сервиса"
                    }
                  />
                </label>
              )}
              <label>
                Модель для общения
                <input
                  aria-label="Модель для общения"
                  value={model}
                  list="setup-model-list"
                  disabled={locked || downloading}
                  onChange={(event) => {
                    setModel(event.target.value);
                    setCheck(null);
                  }}
                  placeholder={
                    progress.mode === "local"
                      ? "qwen3.5:4b"
                      : "Идентификатор модели у сервиса"
                  }
                />
                <datalist id="setup-model-list">
                  {knownModels.map((id) => (
                    <option key={id} value={id}>
                      {localModels.find((item) => item.id === id)?.name ?? id}
                    </option>
                  ))}
                </datalist>
              </label>
              <div className="button-row">
                <button
                  className="outline"
                  disabled={locked}
                  onClick={() =>
                    void action(
                      "Сохраняю и проверяю подключение…",
                      async () => {
                        await saveBrain();
                        await verify();
                      },
                    )
                  }
                >
                  Сохранить и проверить подключение
                </button>
                {progress.mode === "local" && (
                  <button
                    className="outline"
                    disabled={locked || downloading || !model.trim()}
                    onClick={() =>
                      void action("Начинаю загрузку модели…", async () => {
                        await saveBrain();
                        const item = await request<Job>(
                          "/models/pull",
                          "POST",
                          { model: model.trim() },
                        );
                        setJobs((current) => [
                          ...current.filter((old) => old.id !== item.id),
                          item,
                        ]);
                      })
                    }
                  >
                    {downloading
                      ? "Модель скачивается…"
                      : "Скачать выбранную модель"}
                  </button>
                )}
              </div>
              {check && (
                <p
                  className={check.brain.connected ? "help" : "device-error"}
                  role="status"
                >
                  {check.brain.connected
                    ? check.brain.model_available
                      ? "Подключение доступно, выбранная модель найдена."
                      : "Подключение доступно. Выберите модель из списка или скачайте её."
                    : check.brain.error}
                </p>
              )}
              {job && (
                <div className="setup-model-job" role="status">
                  <span>{job.detail}</span>
                  {downloading && (
                    <>
                      <progress
                        aria-label="Загрузка модели мозга"
                        max={100}
                        value={
                          job.total
                            ? Math.min(100, (job.completed / job.total) * 100)
                            : undefined
                        }
                      />
                      <button
                        className="outline"
                        disabled={locked}
                        onClick={() =>
                          void action("Останавливаю загрузку…", async () => {
                            await request(`/jobs/${job.id}`, "DELETE");
                            setJobs(await request<Job[]>("/jobs"));
                          })
                        }
                      >
                        Отменить загрузку модели
                      </button>
                    </>
                  )}
                </div>
              )}
              <p className="help">
                {progress.mode === "local"
                  ? "При выборе ориентируйтесь на объём памяти компьютера. Каталог предлагает Qwen 3.5 4B и вариант Huihui; можно указать другое имя модели Ollama."
                  : "После проверки доступны имена моделей сервиса. Проверка получает список моделей и не генерирует ответ. Ключ хранится отдельно в Windows."}
              </p>
            </>
          )}
          {progress.step === 2 && (
            <>
              <h2>Как будем общаться?</h2>
              <label>
                Озвучка ответов
                <select
                  aria-label="Озвучка ответов"
                  value={progress.voice_mode}
                  disabled={locked || previewing}
                  onChange={(event) =>
                    void action("Сохраняю выбор голоса…", () =>
                      persist({
                        voice_mode: event.target
                          .value as SetupProgress["voice_mode"],
                      }),
                    )
                  }
                >
                  <option value="text">Пока только текст</option>
                  <option value="piper">
                    Piper · Ирина · локальная озвучка
                  </option>
                  <option value="sapi">
                    Голоса Windows · без скачивания модели
                  </option>
                  <option value="keep">Оставить текущий движок и голос</option>
                </select>
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={progress.microphone}
                  disabled={locked}
                  onChange={(event) =>
                    void action("Сохраняю выбор…", () =>
                      persist({ microphone: event.target.checked }),
                    )
                  }
                />
                Использовать голосовой ввод и режим разговора
              </label>
              {(progress.voice_mode === "piper" || progress.microphone) && (
                <ComponentPanel
                  key={[
                    progress.voice_mode,
                    progress.microphone,
                    config.stt_model === "gigaam-v3",
                  ].join()}
                  ids={[
                    ...(progress.voice_mode === "piper" ? ["piper"] : []),
                    ...(progress.microphone
                      ? [
                          config.stt_model === "gigaam-v3"
                            ? "gigaam"
                            : "whisper",
                        ]
                      : []),
                  ]}
                  expanded
                  onReady={() => {}}
                />
              )}
              {progress.voice_mode === "piper" && (
                <div className="setup-download">
                  <span>Голос Ирина · около 63 МБ</span>
                  <button
                    className="outline"
                    disabled={
                      locked ||
                      !voice?.piper_available ||
                      Boolean(
                        voice.piper_voices.find((item) => item.name === "irina")
                          ?.installed,
                      )
                    }
                    onClick={() =>
                      void action(
                        "Скачиваю голос Ирина. Это может занять несколько минут…",
                        () => downloadVoice("piper-irina"),
                      )
                    }
                  >
                    {voice?.piper_voices.find((item) => item.name === "irina")
                      ?.installed
                      ? "Голос установлен"
                      : "Скачать голос Ирина"}
                  </button>
                  {!voice?.piper_available && (
                    <small>
                      Сначала установите Piper и перезапустите программу.
                    </small>
                  )}
                </div>
              )}
              {progress.microphone && (
                <>
                  <label>
                    Модель распознавания
                    <select
                      aria-label="Модель распознавания"
                      value={config.stt_model}
                      disabled={locked}
                      onChange={(event) =>
                        setConfig({
                          ...config,
                          stt_model: event.target
                            .value as Settings["stt_model"],
                        })
                      }
                    >
                      <option value="tiny">Whisper tiny · около 75 МБ</option>
                      <option value="base">Whisper base · около 145 МБ</option>
                      <option value="small">
                        Whisper small · около 485 МБ
                      </option>
                      <option value="gigaam-v3">
                        GigaAM v3 · E2E RNN-T · около 854 МиБ
                      </option>
                    </select>
                  </label>
                  <div className="setup-download">
                    <button
                      className="outline"
                      disabled={
                        locked ||
                        !voice ||
                        !(config.stt_model === "gigaam-v3"
                          ? voice?.gigaam_available
                          : voice?.available) ||
                        voice.installed_stt.includes(config.stt_model)
                      }
                      onClick={() =>
                        void action(
                          "Скачиваю модель распознавания. Это может занять несколько минут…",
                          () => downloadVoice(config.stt_model),
                        )
                      }
                    >
                      {voice?.installed_stt.includes(config.stt_model)
                        ? "Распознавание установлено"
                        : "Скачать модель распознавания"}
                    </button>
                    {!(config.stt_model === "gigaam-v3"
                      ? voice?.gigaam_available
                      : voice?.available) && (
                      <small>
                        Сначала установите{" "}
                        {config.stt_model === "gigaam-v3"
                          ? "GigaAM ONNX"
                          : "Whisper"}{" "}
                        и перезапустите программу.
                      </small>
                    )}
                  </div>
                </>
              )}
              {progress.voice_mode === "sapi" && (
                <label>
                  Системный голос
                  <select
                    aria-label="Системный голос"
                    disabled={locked || !voice?.voices.length}
                    value={systemVoice}
                    onChange={(event) => setSystemVoice(event.target.value)}
                  >
                    <option value="">По умолчанию Windows</option>
                    {voice?.voices.map((item) => (
                      <option key={item.name} value={item.name}>
                        {item.name} · {item.language}
                      </option>
                    ))}
                  </select>
                  {voice && !voice.voices.length && (
                    <small>
                      Голоса Windows не найдены. Выберите Piper или текст.
                    </small>
                  )}
                </label>
              )}
              {(progress.microphone || progress.voice_mode !== "text") && (
                <AudioDevices
                  settings={config}
                  onChange={setConfig}
                  disabled={locked || previewing}
                />
              )}
              {progress.voice_mode !== "text" && (
                <>
                  <button
                    className="outline"
                    disabled={locked}
                    onClick={() => void sample()}
                  >
                    {previewing
                      ? "Остановить пробу голоса"
                      : "Прослушать выбранный голос"}
                  </button>
                  <p className="help">
                    Escape останавливает озвучку.
                    {selectedVoice === "cloud"
                      ? " Проба облачного голоса расходует квоту сервиса."
                      : ""}
                  </p>
                </>
              )}
              <p className="help">
                Другие локальные голоса, Qwen3-TTS, облачная озвучка и
                VRM-аватар доступны в обычных настройках. Выбор устройств
                сохранится кнопкой ниже.
              </p>
            </>
          )}
          {progress.step === 3 && (
            <>
              <h2>
                {ready ? "Можно начинать общение" : "Проверим, что уже готово"}
              </h2>
              <dl className="setup-checklist">
                <div>
                  <dt>Мозг · {config.model}</dt>
                  <dd>
                    {!check
                      ? "Нажмите «Проверить готовность»"
                      : check.brain.connected && check.brain.model_available
                        ? "Подключение и наличие модели проверены"
                        : check.brain.error ||
                          "Выбранная модель ещё не установлена или недоступна"}
                  </dd>
                </div>
                <div>
                  <dt>Озвучка</dt>
                  <dd>
                    {!config.speak_answers
                      ? "Отключена · текстовый режим"
                      : !check
                        ? "Пока не проверена"
                        : check.speech.synthesis
                          ? "Движок и голос настроены"
                          : check.speech.error ||
                            "Установите движок и голос на предыдущем шаге"}
                  </dd>
                </div>
                <div>
                  <dt>Распознавание голоса</dt>
                  <dd>
                    {!progress.microphone
                      ? "Можно подключить позже"
                      : check?.speech.recognition
                        ? "Движок и выбранная модель установлены"
                        : "Установите движок и веса выбранной модели"}
                  </dd>
                </div>
              </dl>
              <button
                className="outline"
                disabled={locked}
                onClick={() =>
                  void action(
                    "Проверяю подключение и установленные модели…",
                    async () => {
                      await verify();
                    },
                  )
                }
              >
                Проверить готовность
              </button>
              <p className="help">
                Проверка не запрашивает ответ у мозга и не записывает речь.
                Первый настоящий ответ дополнительно загрузит модель в память.
              </p>
            </>
          )}
        </section>
        <footer className="setup-footer">
          <button
            className="outline"
            disabled={locked || progress.step === 0}
            onClick={() =>
              void action("Возвращаюсь…", () =>
                persist({ step: progress.step - 1 }),
              )
            }
          >
            Назад
          </button>
          <span>
            Шаг {progress.step + 1} из {steps.length}
          </span>
          {progress.step < 3 ? (
            <button
              className="primary"
              disabled={locked || downloading}
              onClick={() => void action("Сохраняю настройку…", next)}
            >
              {progress.step === 0
                ? "Начать настройку"
                : "Сохранить и продолжить"}
            </button>
          ) : (
            <button
              className="primary"
              disabled={locked || !ready}
              onClick={() =>
                void action("Завершаю настройку…", async () => {
                  await persist({ active: false, completed: true });
                  onClose();
                })
              }
            >
              Начать общение
            </button>
          )}
        </footer>
      </div>
    </main>
  );
}
