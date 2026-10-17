import { useEffect, useRef, useState } from "react";
import { request, type Settings, type SpeechSettings } from "../api";

const endpoints = {
  openrouter: "https://openrouter.ai/api/v1",
  routerai: "https://routerai.ru/api/v1",
};
const presets: {
  id: string;
  name: string;
  description: string;
  config: Partial<SpeechSettings>;
}[] = [
  {
    id: "fish",
    name: "Fish Audio Free",
    description:
      "OpenRouter · бесплатно с лимитами. Для постоянного тембра можно добавить WAV-образец.",
    config: {
      tts_service: "openrouter",
      tts_base_url: endpoints.openrouter,
      tts_model: "fish-audio/s2.1-pro-free:free",
      tts_cloud_voice: "",
    },
  },
  {
    id: "gemini",
    name: "Gemini TTS",
    description:
      "RouterAI · платно по токенам. Sulafat — тёплый голос; Achernar — мягкий.",
    config: {
      tts_service: "routerai",
      tts_base_url: endpoints.routerai,
      tts_model: "google/gemini-3.8-flash-tts",
      tts_cloud_voice: "Sulafat",
    },
  },
  {
    id: "grok",
    name: "Grok Voice",
    description:
      "RouterAI · платно по символам. Ara — тёплый и дружелюбный голос.",
    config: {
      tts_service: "routerai",
      tts_base_url: endpoints.routerai,
      tts_model: "x-ai/grok-voice-tts-1.0",
      tts_cloud_voice: "ara",
    },
  },
];
type Connections = {
  connections: { service: string; base_url: string; has_key: boolean }[];
  reference: { name: string; seconds: number } | null;
  serena_available: boolean;
};
type Model = {
  id: string;
  name: string;
  voices: string[];
  pricing: Record<string, string | number>;
};

function Field({
  label,
  value,
  onSave,
  list,
}: {
  label: string;
  value: string;
  onSave: (value: string) => void;
  list?: string;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <label>
      {label}
      <input
        aria-label={label}
        value={draft}
        list={list}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => {
          if (draft !== value) onSave(draft.trim());
        }}
      />
    </label>
  );
}

export function CloudSpeechSettings({
  settings,
  onChange,
  onPreview,
  flush,
  onError,
  onNotice,
  disabled,
}: {
  settings: Settings;
  onChange: (patch: Partial<SpeechSettings>) => Promise<void>;
  onPreview: (patch: Partial<SpeechSettings>) => Promise<void>;
  flush: () => Promise<void>;
  onError: (reason: unknown) => void;
  onNotice: (text: string) => void;
  disabled: boolean;
}) {
  const [info, setInfo] = useState<Connections>();
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [models, setModels] = useState<Model[]>([]);
  const [busy, setBusy] = useState(false);
  const [geminiModel, setGeminiModel] = useState(
    settings.tts_model.startsWith("google/")
      ? settings.tts_model
      : "google/gemini-3.8-flash-tts",
  );
  const upload = useRef<HTMLInputElement>(null);
  const reload = async () =>
    setInfo(await request<Connections>("/voice/cloud/connections"));
  useEffect(() => {
    let current = true;
    void request<Connections>("/voice/cloud/connections")
      .then((value) => {
        if (current) setInfo(value);
      })
      .catch(onError);
    return () => {
      current = false;
    };
  }, [settings.tts_base_url]);
  const run = (operation: () => Promise<unknown>) => {
    setBusy(true);
    void operation()
      .catch(onError)
      .finally(() => setBusy(false));
  };
  const change = (patch: Partial<SpeechSettings>) => {
    void onChange(patch).catch(() => {});
  };
  const keyRows = [
    { name: "OpenRouter", url: endpoints.openrouter },
    { name: "RouterAI", url: endpoints.routerai },
    ...(settings.tts_service === "compatible"
      ? [{ name: "Совместимый API", url: settings.tts_base_url }]
      : []),
  ].filter(
    (row, index, rows) =>
      rows.findIndex((other) => other.url === row.url) === index,
  );
  const preset = (item: (typeof presets)[number]) => ({
    ...item.config,
    tts_engine: "cloud" as const,
    tts_format: "auto" as const,
    tts_use_reference: settings.tts_use_reference,
    ...(item.id === "gemini" ? { tts_model: geminiModel } : {}),
    tts_style: settings.tts_style,
  });
  const stockVoices = settings.tts_model.startsWith("google/")
    ? ["Sulafat", "Achernar", "Vindemiatrix", "Aoede", "Despina", "Kore"]
    : settings.tts_model.startsWith("x-ai/")
      ? ["ara", "eve", "rex", "sal", "leo"]
      : [];
  return (
    <div className="cloud-speech-settings">
      <h3>Облачная озвучка</h3>
      <p className="help">
        В облако отправляются озвучиваемые фразы. Ключи хранятся в Windows
        отдельно от ключа модели для чата. Нажатие «Прослушать» расходует квоту
        или баланс выбранного сервиса.
      </p>
      {keyRows.map((row) => (
        <div className="cloud-key" key={row.url}>
          <label>
            Ключ озвучки {row.name}
            <input
              aria-label={"Ключ озвучки " + row.name}
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={secrets[row.url] || ""}
              placeholder={
                info?.connections.some(
                  (connection) =>
                    connection.base_url === row.url && connection.has_key,
                )
                  ? "Ключ уже сохранён"
                  : "Вставьте API-ключ"
              }
              onChange={(event) =>
                setSecrets({ ...secrets, [row.url]: event.target.value })
              }
            />
          </label>
          <div className="button-row">
            <button
              className="outline"
              disabled={busy || !secrets[row.url]}
              onClick={() =>
                run(async () => {
                  await request("/voice/cloud/key", "PUT", {
                    base_url: row.url,
                    api_key: secrets[row.url],
                  });
                  setSecrets((current) => ({ ...current, [row.url]: "" }));
                  await reload();
                  onNotice("Ключ озвучки " + row.name + " сохранён");
                })
              }
            >
              Сохранить ключ {row.name}
            </button>
            <button
              className="subtle"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await request("/voice/cloud/key", "PUT", {
                    base_url: row.url,
                    api_key: "",
                  });
                  await reload();
                  onNotice("Ключ озвучки удалён");
                })
              }
            >
              Удалить ключ {row.name}
            </button>
          </div>
        </div>
      ))}
      <div className="cloud-presets">
        {presets.map((item) => (
          <article key={item.id}>
            <h4>{item.name}</h4>
            {item.id === "gemini" && (
              <label>
                Вариант Gemini
                <select
                  aria-label="Вариант Gemini"
                  value={geminiModel}
                  onChange={(event) => setGeminiModel(event.target.value)}
                >
                  <option value="google/gemini-3.8-flash-tts">
                    Flash TTS · выразительность
                  </option>
                  <option value="google/gemini-3.8-flash-lite-tts">
                    Flash Lite TTS · дешевле и быстрее
                  </option>
                </select>
              </label>
            )}
            <p className="help">{item.description}</p>
            <div className="button-row">
              <button
                className="outline"
                disabled={busy}
                onClick={() => run(() => onChange(preset(item)))}
              >
                Выбрать {item.name}
              </button>
              <button
                className="outline"
                disabled={busy || disabled}
                onClick={() =>
                  run(async () => {
                    await flush();
                    await onPreview(preset(item));
                  })
                }
              >
                Прослушать {item.name}
              </button>
            </div>
          </article>
        ))}
      </div>
      <label>
        Сервис озвучки
        <select
          aria-label="Сервис озвучки"
          value={settings.tts_service}
          onChange={(event) => {
            const service = event.target.value as Settings["tts_service"];
            if (service === "compatible") change({ tts_service: service });
            else change(preset(presets[service === "openrouter" ? 0 : 1]));
            setModels([]);
          }}
        >
          <option value="openrouter">OpenRouter</option>
          <option value="routerai">RouterAI</option>
          <option value="compatible">Другой совместимый API</option>
        </select>
      </label>
      <Field
        label="Адрес API озвучки"
        value={settings.tts_base_url}
        onSave={(value) =>
          change({
            tts_base_url: value,
            tts_service:
              value.replace(/\/+$/, "") === endpoints.routerai
                ? "routerai"
                : value.replace(/\/+$/, "") === endpoints.openrouter
                  ? "openrouter"
                  : "compatible",
          })
        }
      />
      <Field
        label="Облачная модель озвучки"
        value={settings.tts_model}
        list="cloud-models"
        onSave={(value) => change({ tts_model: value })}
      />
      <datalist id="cloud-models">
        {[
          ...new Set([
            ...models.map((model) => model.id),
            ...presets.map((item) => item.config.tts_model!),
            "google/gemini-3.8-flash-lite-tts",
          ]),
        ].map((id) => (
          <option key={id} value={id} />
        ))}
      </datalist>
      <button
        className="outline"
        disabled={busy}
        onClick={() =>
          run(async () => {
            await flush();
            setModels(await request<Model[]>("/voice/cloud/catalog"));
            onNotice("Каталог облачной озвучки обновлён");
          })
        }
      >
        Обновить каталог озвучки
      </button>
      <Field
        label="Облачный голос или ID голоса"
        value={settings.tts_cloud_voice}
        list="cloud-voices"
        onSave={(value) => change({ tts_cloud_voice: value })}
      />
      <datalist id="cloud-voices">
        {[
          ...new Set([
            ...stockVoices,
            ...(models.find((model) => model.id === settings.tts_model)
              ?.voices || []),
          ]),
        ].map((voice) => (
          <option key={voice} value={voice} />
        ))}
      </datalist>
      <Field
        label="Манера облачной речи"
        value={settings.tts_style}
        onSave={(value) => change({ tts_style: value })}
      />
      <label>
        Формат облачного аудио
        <select
          aria-label="Формат облачного аудио"
          value={settings.tts_format}
          onChange={(event) =>
            change({ tts_format: event.target.value as Settings["tts_format"] })
          }
        >
          <option value="auto">Автоматически</option>
          <option value="mp3">MP3</option>
          <option value="pcm">PCM16 · 24 кГц · моно</option>
          <option value="wav">WAV · если сервис поддерживает</option>
        </select>
      </label>
      <details>
        <summary>WAV-образец для Fish Audio</summary>
        <p className="help">
          Для постоянного тембра: WAV PCM16, 1–30 секунд, до 5 МБ. При включении
          образец отправляется OpenRouter вместе с каждой фразой Fish. Он
          хранится только на этом ПК и не включается в резервную копию.
        </p>
        <p>
          {info?.reference
            ? `${info.reference.name} · ${info.reference.seconds} с`
            : "Образец не загружен"}
        </p>
        <input
          type="file"
          accept=".wav,audio/wav"
          aria-label="Загрузить WAV-образец"
          ref={upload}
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (!file) return;
            run(async () => {
              const form = new FormData();
              form.append("file", file);
              await request("/voice/cloud/reference", "POST", form);
              await reload();
              change({ tts_use_reference: true });
            });
          }}
        />
        <div className="button-row">
          <button
            className="outline"
            disabled={busy}
            onClick={() => upload.current?.click()}
          >
            Загрузить WAV
          </button>
          {info?.serena_available && (
            <button
              className="outline"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await request("/voice/cloud/reference/serena", "POST");
                  await reload();
                  await onChange({ tts_use_reference: true });
                })
              }
            >
              Взять локальный пример Serena
            </button>
          )}
          {info?.reference && (
            <button
              className="subtle"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await onChange({ tts_use_reference: false });
                  await request("/voice/cloud/reference", "DELETE");
                  await reload();
                })
              }
            >
              Удалить образец
            </button>
          )}
        </div>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={settings.tts_use_reference}
            onChange={(event) =>
              change({ tts_use_reference: event.target.checked })
            }
          />
          Использовать WAV-образец для Fish
        </label>
      </details>
      <p className="help">
        Пробы не меняют выбранную модель. «Выбрать» сохраняет вариант для
        ответов в чате. Для проверки другого тембра измените поле голоса и
        нажмите общую кнопку «Прослушать голос».
      </p>
    </div>
  );
}
