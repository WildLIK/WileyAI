import { useEffect, useRef, useState } from "react";
import { request, type Settings, type SpeechSettings } from "../api";
import { fishVoiceId } from "./fish";
import { CloudVoices } from "./CloudVoices";

const endpoints = {
  openrouter: "https://openrouter.ai/api/v1",
  routerai: "https://routerai.ru/api/v1",
};
const presets = [
  {
    service: "openrouter",
    model: "fish-audio/s2.1-pro-free:free",
    name: "Fish Audio Free · бесплатно с лимитами",
    voice: "",
  },
  {
    service: "routerai",
    model: "google/gemini-3.8-flash-tts",
    name: "Gemini Flash TTS · выразительность",
    voice: "Sulafat",
  },
  {
    service: "routerai",
    model: "google/gemini-3.8-flash-lite-tts",
    name: "Gemini Flash Lite TTS · дешевле и быстрее",
    voice: "Sulafat",
  },
  {
    service: "routerai",
    model: "x-ai/grok-voice-tts-1.0",
    name: "Grok Voice TTS",
    voice: "ara",
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
  flush,
  onError,
  onNotice,
  disabled,
}: {
  settings: Settings;
  onChange: (patch: Partial<SpeechSettings>) => Promise<void>;
  flush: () => Promise<void>;
  onError: (reason: unknown) => void;
  onNotice: (text: string) => void;
  disabled: boolean;
}) {
  const [info, setInfo] = useState<Connections>();
  const [secret, setSecret] = useState("");
  const [models, setModels] = useState<Model[]>([]);
  const [busy, setBusy] = useState(false);
  const [customModel, setCustomModel] = useState(false);
  const upload = useRef<HTMLInputElement>(null);
  const reload = async () =>
    setInfo(await request<Connections>("/voice/cloud/connections"));
  useEffect(() => {
    let current = true;
    setSecret("");
    setModels([]);
    setCustomModel(false);
    void request<Connections>("/voice/cloud/connections")
      .then((value) => {
        if (current) setInfo(value);
      })
      .catch(onError);
    return () => {
      current = false;
    };
  }, [settings.tts_service, settings.tts_base_url]);
  const run = (operation: () => Promise<unknown>) => {
    setBusy(true);
    void operation()
      .catch(onError)
      .finally(() => setBusy(false));
  };
  const change = (patch: Partial<SpeechSettings>) => {
    void onChange(patch).catch(() => {});
  };
  const serviceName =
    settings.tts_service === "openrouter"
      ? "OpenRouter"
      : settings.tts_service === "routerai"
        ? "RouterAI"
        : "Совместимый API";
  const hasKey = info?.connections.some(
    (row) => row.base_url === settings.tts_base_url && row.has_key,
  );
  const fish = settings.tts_model.startsWith("fish-audio/");
  const fishReference = fish && settings.tts_service === "openrouter";
  const options = new Map([
    ...presets
      .filter((item) => item.service === settings.tts_service)
      .map((item) => [item.model, item.name] as const),
    ...models.map((item) => [item.id, item.name] as const),
  ]);
  if (settings.tts_model && !options.has(settings.tts_model))
    options.set(settings.tts_model, settings.tts_model);
  const voices = [
    ...new Set([
      ...(settings.tts_model.startsWith("google/")
        ? ["Sulafat", "Achernar", "Vindemiatrix", "Aoede", "Despina", "Kore"]
        : settings.tts_model.startsWith("x-ai/")
          ? ["ara", "eve", "rex", "sal", "leo"]
          : []),
      ...(models.find((item) => item.id === settings.tts_model)?.voices || []),
    ]),
  ];
  const saveUrl = (value: string) =>
    change({
      tts_base_url: value,
      tts_service:
        value.replace(/\/+$/, "") === endpoints.openrouter
          ? "openrouter"
          : value.replace(/\/+$/, "") === endpoints.routerai
            ? "routerai"
            : "compatible",
    });
  const address = (
    <Field
      label="Адрес API озвучки"
      value={settings.tts_base_url}
      onSave={saveUrl}
    />
  );
  const modelId = (
    <Field
      label="ID облачной модели озвучки"
      value={settings.tts_model}
      onSave={(value) =>
        change({ tts_model: value, tts_cloud_voice: "", tts_format: "auto" })
      }
    />
  );
  const voiceId = (
    <Field
      label={
        fish
          ? "Ссылка или ID голоса Fish Audio"
          : "Облачный голос или ID голоса"
      }
      value={settings.tts_cloud_voice}
      list="cloud-voices"
      onSave={(value) => {
        try {
          const voice = fish ? fishVoiceId(value) : value;
          change({
            tts_cloud_voice: voice,
            ...(fish && voice ? { tts_use_reference: false } : {}),
          });
        } catch (error) {
          onError(error);
        }
      }}
    />
  );

  return (
    <fieldset className="cloud-speech-settings" disabled={busy || disabled}>
      <legend>Облачная озвучка</legend>
      <label>
        Сервис озвучки
        <select
          aria-label="Сервис озвучки"
          value={settings.tts_service}
          onChange={(event) =>
            change({
              tts_service: event.target.value as Settings["tts_service"],
            })
          }
        >
          <option value="openrouter">OpenRouter</option>
          <option value="routerai">RouterAI</option>
          <option value="compatible">Другой совместимый API</option>
        </select>
      </label>
      {settings.tts_service === "compatible" && address}
      <details className="cloud-key" key={settings.tts_base_url} open={!hasKey}>
        <summary>
          Ключ {serviceName} · {hasKey ? "сохранён" : "не указан"}
        </summary>
        <label>
          Ключ озвучки {serviceName}
          <input
            aria-label={"Ключ озвучки " + serviceName}
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={secret}
            placeholder={
              hasKey ? "Введите новый ключ для замены" : "Вставьте API-ключ"
            }
            onChange={(event) => setSecret(event.target.value)}
          />
        </label>
        <div className="button-row">
          <button
            className="outline"
            disabled={!secret}
            onClick={() =>
              run(async () => {
                await request("/voice/cloud/key", "PUT", {
                  base_url: settings.tts_base_url,
                  api_key: secret,
                });
                setSecret("");
                await reload();
                onNotice("Ключ озвучки " + serviceName + " сохранён");
              })
            }
          >
            Сохранить ключ {serviceName}
          </button>
          {hasKey && (
            <button
              className="subtle"
              onClick={() =>
                run(async () => {
                  await request("/voice/cloud/key", "PUT", {
                    base_url: settings.tts_base_url,
                    api_key: "",
                  });
                  setSecret("");
                  await reload();
                  onNotice("Ключ озвучки удалён");
                })
              }
            >
              Удалить ключ {serviceName}
            </button>
          )}
        </div>
      </details>
      <label>
        Облачная модель озвучки
        <select
          aria-label="Облачная модель озвучки"
          value={
            customModel || !settings.tts_model ? "custom" : settings.tts_model
          }
          onChange={(event) => {
            const id = event.target.value;
            setCustomModel(id === "custom");
            if (id !== "custom")
              change({
                tts_model: id,
                tts_format: "auto",
                tts_cloud_voice:
                  presets.find((item) => item.model === id)?.voice || "",
              });
          }}
        >
          {[...options].map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
          <option value="custom">Указать ID другой модели…</option>
        </select>
      </label>
      {(customModel || !settings.tts_model) && modelId}
      <CloudVoices
        settings={settings}
        voices={voices}
        reference={fishReference ? info?.reference?.name : undefined}
        onChange={onChange}
        flush={flush}
        onError={onError}
      />
      {fishReference && (
        <details className="cloud-advanced">
          <summary>WAV-образец голоса</summary>
          {settings.tts_use_reference && info?.reference && (
            <p className="help">{`Голос из образца: ${info.reference.name} · ${info.reference.seconds} с`}</p>
          )}
          <div className="button-row">
            {info?.serena_available && (
              <button
                className="outline"
                onClick={() =>
                  run(async () => {
                    await request("/voice/cloud/reference/serena", "POST");
                    await reload();
                    await onChange({
                      tts_use_reference: true,
                      tts_cloud_voice: "",
                    });
                    onNotice("Выбран женский образец Serena для Fish Audio");
                  })
                }
              >
                Женский голос · образец Serena
              </button>
            )}
            <button className="outline" onClick={() => upload.current?.click()}>
              Загрузить свой WAV
            </button>
          </div>
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
                await onChange({
                  tts_use_reference: true,
                  tts_cloud_voice: "",
                });
              });
            }}
          />
          {info?.reference && (
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
          )}
        </details>
      )}
      <datalist id="cloud-voices">
        {voices.map((voice) => (
          <option key={voice} value={voice} />
        ))}
      </datalist>
      <details className="cloud-advanced" key={settings.tts_service}>
        <summary>Дополнительно: API, голос и формат</summary>
        {settings.tts_service !== "compatible" && address}
        {!customModel && settings.tts_model && modelId}
        {voiceId}
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
              change({
                tts_format: event.target.value as Settings["tts_format"],
              })
            }
          >
            <option value="auto">Автоматически</option>
            <option value="mp3">MP3</option>
            <option value="pcm">PCM16 · 24 кГц · моно</option>
            <option value="wav">WAV · если сервис поддерживает</option>
          </select>
        </label>
        <button
          className="outline"
          onClick={() =>
            run(async () => {
              await flush();
              setModels(await request<Model[]>("/voice/cloud/catalog"));
              onNotice("Каталог озвучки " + serviceName + " обновлён");
            })
          }
        >
          Обновить каталог озвучки
        </button>
        {fishReference && (
          <>
            <p className="help">
              Для сохранения голоса по ссылке выберите «Добавить…» в списке
              голосов. Женский образец задаёт тембр, сходство зависит от записи
              и модели. WAV: PCM16, 1–30 секунд, до 5 МБ. Образец хранится на
              этом ПК и не включается в резервную копию.
            </p>
            {info?.reference && (
              <button
                className="subtle"
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
          </>
        )}
      </details>
      <p className="help">
        Фразы и включённый образец отправляются выбранному сервису. Ключ
        хранится отдельно в Windows. Прослушивание расходует квоту или баланс
        сервиса.
      </p>
    </fieldset>
  );
}
