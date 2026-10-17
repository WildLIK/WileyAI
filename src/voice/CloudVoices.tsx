import { useEffect, useState } from "react";
import {
  request,
  type Settings,
  type SpeechSettings,
  type SavedSpeechVoice,
} from "../api";
import { FISH_VOICES } from "./fish";

export function CloudVoices({
  settings,
  voices,
  reference,
  onChange,
  flush,
  onError,
}: {
  settings: Settings;
  voices: string[];
  reference?: string;
  onChange: (patch: Partial<SpeechSettings>) => Promise<void>;
  flush: () => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setAdding(false);
    setName("");
    setValue("");
  }, [settings.tts_base_url, settings.tts_model]);
  const saved = (settings.tts_saved_voices || []).filter(
    (row) =>
      row.base_url === settings.tts_base_url &&
      row.model === settings.tts_model,
  );
  const options = new Map<string, string>(
    voices.map((voice) => [voice, voice]),
  );
  if (settings.tts_model.startsWith("fish-audio/"))
    FISH_VOICES.forEach((voice) => options.set(voice.id, voice.name));
  saved.forEach((row) => options.set(row.voice, row.name));
  if (settings.tts_cloud_voice && !options.has(settings.tts_cloud_voice))
    options.set(settings.tts_cloud_voice, settings.tts_cloud_voice);
  const selected = saved.find((row) => row.voice === settings.tts_cloud_voice);
  const run = (operation: () => Promise<void>) => {
    setBusy(true);
    void operation()
      .catch(onError)
      .finally(() => setBusy(false));
  };
  return (
    <fieldset className="cloud-voice-picker" disabled={busy}>
      <label>
        Облачный голос
        <select
          aria-label="Облачный голос"
          value={
            reference && settings.tts_use_reference
              ? "$reference"
              : settings.tts_cloud_voice
          }
          onChange={(event) => {
            if (event.target.value === "$add") {
              setAdding(true);
              return;
            }
            setAdding(false);
            void onChange({
              tts_cloud_voice:
                event.target.value === "$reference" ? "" : event.target.value,
              tts_use_reference: event.target.value === "$reference",
            }).catch(() => {});
          }}
        >
          <option value="">По умолчанию</option>
          {[...options].map(([id, label]) => (
            <option value={id} key={id}>
              {label}
            </option>
          ))}
          {reference && <option value="$reference">WAV · {reference}</option>}
          <option value="$add">Добавить…</option>
        </select>
      </label>
      {adding && (
        <div className="cloud-key">
          <label>
            Название голоса
            <input
              aria-label="Название голоса"
              maxLength={80}
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoFocus
            />
          </label>
          <label>
            Ссылка или ID голоса
            <input
              aria-label="Ссылка или ID голоса"
              maxLength={300}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder="https://fish.audio/ru/m/… или ID"
            />
          </label>
          <div className="button-row">
            <button
              className="outline"
              disabled={!name.trim() || !value.trim()}
              onClick={() =>
                run(async () => {
                  await flush();
                  const row = await request<SavedSpeechVoice>(
                    "/voice/cloud/voices",
                    "POST",
                    { name: name.trim(), voice: value.trim() },
                  );
                  await onChange({
                    tts_cloud_voice: row.voice,
                    tts_use_reference: false,
                  });
                  setAdding(false);
                  setName("");
                  setValue("");
                })
              }
            >
              Добавить голос
            </button>
            <button className="subtle" onClick={() => setAdding(false)}>
              Отмена
            </button>
          </div>
          <p className="help">
            Голос сохранится для этого сервиса и модели. Для Fish Audio можно
            вставить адрес страницы голоса.
          </p>
        </div>
      )}
      {selected && !settings.tts_use_reference && (
        <button
          className="subtle"
          onClick={() =>
            run(async () => {
              await request("/voice/cloud/voices/" + selected.id, "DELETE");
              await onChange({ tts_cloud_voice: "" });
            })
          }
        >
          Удалить голос «{selected.name}» из списка
        </button>
      )}
    </fieldset>
  );
}
