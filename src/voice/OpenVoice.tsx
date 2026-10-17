import { useEffect, useRef, useState } from "react";
import { request, type Settings, type SpeechSettings } from "../api";

type Info = {
  installed: boolean;
  references: {
    id: Settings["openvoice_voice"];
    name: string;
    available: boolean;
  }[];
};
export function OpenVoiceSettings({
  settings,
  onChange,
  disabled,
  onError,
  onNotice,
}: {
  settings: Settings;
  onChange: (patch: Partial<SpeechSettings>) => Promise<void>;
  disabled: boolean;
  onError: (reason: unknown) => void;
  onNotice: (message: string) => void;
}) {
  const [info, setInfo] = useState<Info>();
  const [busy, setBusy] = useState(false);
  const upload = useRef<HTMLInputElement>(null);
  useEffect(() => {
    void request<Info>("/voice/openvoice").then(setInfo).catch(onError);
  }, []);
  const run = (operation: () => Promise<void>) => {
    setBusy(true);
    void operation()
      .catch(onError)
      .finally(() => setBusy(false));
  };
  return (
    <fieldset className="cloud-speech-settings" disabled={disabled || busy}>
      <legend>OpenVoice · локальное изменение тембра</legend>
      <label>
        Основа OpenVoice
        <select
          aria-label="Основа OpenVoice"
          value={settings.tts_engine}
          onChange={(event) => {
            void onChange({
              tts_engine: event.target.value as Settings["tts_engine"],
              tts_voice: "",
            }).catch(() => {});
          }}
        >
          <option value="piper">Piper · быстрее</option>
          <option value="silero_v5_6">Silero 5.6 · выразительность</option>
          <option value="silero">Silero 5</option>
        </select>
      </label>
      <label>
        Тембр OpenVoice
        <select
          aria-label="Тембр OpenVoice"
          value={settings.openvoice_voice}
          onChange={(event) => {
            void onChange({
              openvoice_voice: event.target
                .value as Settings["openvoice_voice"],
            }).catch(() => {});
          }}
        >
          {(info?.references || []).map((row) => (
            <option key={row.id} value={row.id}>
              {row.name}
              {row.available ? "" : " · нет образца"}
            </option>
          ))}
        </select>
      </label>
      <div className="button-row">
        <button className="outline" onClick={() => upload.current?.click()}>
          Загрузить WAV для OpenVoice
        </button>
        <button
          className="subtle"
          onClick={() =>
            run(async () => {
              setInfo(await request<Info>("/voice/openvoice/install", "POST"));
              onNotice("OpenVoice установлен. Можно прослушать голос");
            })
          }
        >
          {info?.installed
            ? "Переустановить OpenVoice"
            : "Установить OpenVoice"}
        </button>
      </div>
      <input
        ref={upload}
        aria-label="WAV-образец OpenVoice"
        hidden
        type="file"
        accept=".wav,audio/wav"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          run(async () => {
            const form = new FormData();
            form.append("file", file);
            setInfo(
              await request<Info>("/voice/openvoice/reference", "POST", form),
            );
            await onChange({ openvoice_voice: "custom" });
            onNotice("Выбран свой образец OpenVoice: " + file.name);
          });
        }}
      />
      <p className="help" role="status">
        {busy
          ? "Подготовка OpenVoice…"
          : info
            ? info.installed
              ? "OpenVoice установлен · CPU"
              : "OpenVoice ещё не установлен"
            : "Проверяю OpenVoice…"}
      </p>
      <p className="help">
        Piper или Silero произносит текст, OpenVoice меняет тембр по образцу.
        Всё работает на ПК. Первый запуск дольше; интонация и сходство зависят
        от исходного голоса. WAV: PCM16, 1–30 секунд, до 5 МБ.
      </p>
    </fieldset>
  );
}
