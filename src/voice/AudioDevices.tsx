import { useEffect, useRef, useState } from "react";
import type { Settings } from "../api";
import { Microphone } from "./microphone";
import { playAudio } from "./devices";
import { rms, wav } from "./speech";

export function AudioDevices({
  settings,
  onChange,
  disabled,
}: {
  settings: Settings;
  onChange: (settings: Settings) => void;
  disabled: boolean;
}) {
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [level, setLevel] = useState(0);
  const microphone = useRef<Microphone | null>(null);
  const output = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);

  const fail = (error: unknown) => {
    if (
      !mounted.current ||
      (error instanceof DOMException && error.name === "AbortError")
    )
      return;
    setError(
      error instanceof Error ? error.message : "Не удалось проверить звук",
    );
  };
  async function refresh() {
    try {
      const items = await navigator.mediaDevices.enumerateDevices();
      if (mounted.current)
        setDevices(
          items.filter((item) =>
            ["audioinput", "audiooutput"].includes(item.kind),
          ),
        );
    } catch (error) {
      fail(error);
    }
  }
  function stopMicrophone() {
    const current = microphone.current;
    microphone.current = null;
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    void current?.stop().catch(fail);
    if (mounted.current) {
      setChecking(false);
      setLevel(0);
    }
  }
  useEffect(() => {
    mounted.current = true;
    void refresh();
    const changed = () => {
      void refresh();
    };
    navigator.mediaDevices.addEventListener("devicechange", changed);
    return () => {
      mounted.current = false;
      navigator.mediaDevices.removeEventListener("devicechange", changed);
      stopMicrophone();
      output.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (disabled) {
      stopMicrophone();
      output.current?.abort();
    }
  }, [disabled]);

  async function checkMicrophone() {
    if (microphone.current) {
      stopMicrophone();
      return;
    }
    setError("");
    output.current?.abort();
    const current = new Microphone(settings.audio_input_device_id);
    microphone.current = current;
    setChecking(true);
    let last = 0;
    try {
      await current.start(
        (frame) => {
          if (microphone.current !== current || performance.now() - last < 90)
            return;
          last = performance.now();
          setLevel(Math.min(1, rms(frame) * 5));
        },
        (error) => {
          if (microphone.current !== current) return;
          stopMicrophone();
          fail(error);
        },
      );
      if (microphone.current !== current) return;
      await refresh();
      if (microphone.current !== current) return;
      timer.current = setTimeout(stopMicrophone, 7000);
    } catch (error) {
      if (microphone.current !== current) return;
      stopMicrophone();
      fail(error);
    }
  }
  async function checkOutput() {
    if (output.current) {
      output.current.abort();
      return;
    }
    stopMicrophone();
    setError("");
    const controller = new AbortController();
    output.current = controller;
    setPlaying(true);
    const rate = 16000;
    const samples = new Float32Array(rate);
    for (let index = 0; index < samples.length; index++) {
      const time = index / rate;
      if (time < 0.4 || time > 0.6) {
        const position = time < 0.4 ? time : time - 0.6;
        const envelope = Math.min(1, position / 0.02, (0.4 - position) / 0.02);
        samples[index] =
          0.12 *
          envelope *
          Math.sin(2 * Math.PI * (time < 0.4 ? 440 : 660) * time);
      }
    }
    try {
      await playAudio(
        new Blob([wav(samples, rate)], { type: "audio/wav" }),
        settings.audio_output_device_id,
        controller.signal,
      );
    } catch (error) {
      fail(error);
    } finally {
      if (output.current === controller) output.current = null;
      if (mounted.current) setPlaying(false);
    }
  }

  function selector(
    kind: "audioinput" | "audiooutput",
    key: "audio_input_device_id" | "audio_output_device_id",
    label: string,
  ) {
    const items = devices.filter(
      (item) =>
        item.kind === kind && item.deviceId && item.deviceId !== "default",
    );
    const missing =
      settings[key] && !items.some((item) => item.deviceId === settings[key]);
    return (
      <label>
        {label}
        <select
          aria-label={label}
          value={settings[key]}
          disabled={disabled || checking || playing}
          onChange={(event) =>
            onChange({ ...settings, [key]: event.target.value })
          }
        >
          <option value="">По умолчанию Windows</option>
          {missing && (
            <option value={settings[key]}>
              Сохранённое устройство сейчас недоступно
            </option>
          )}
          {items.map((item, index) => (
            <option key={item.deviceId} value={item.deviceId}>
              {item.label ||
                `${kind === "audioinput" ? "Микрофон" : "Динамик"} ${index + 1}`}
            </option>
          ))}
        </select>
      </label>
    );
  }
  return (
    <div className="card audio-devices">
      <h2>Устройства звука</h2>
      {selector("audioinput", "audio_input_device_id", "Микрофон")}
      {selector("audiooutput", "audio_output_device_id", "Динамик / наушники")}
      <div className="button-row">
        <button
          className="outline"
          disabled={disabled || playing}
          onClick={() => void checkMicrophone()}
        >
          {checking ? "Остановить проверку" : "Проверить микрофон"}
        </button>
        <button
          className="outline"
          disabled={disabled || checking}
          onClick={() => void checkOutput()}
        >
          {playing ? "Остановить сигнал" : "Проверить динамик"}
        </button>
        <button className="subtle" onClick={() => void refresh()}>
          Обновить устройства
        </button>
      </div>
      {checking && (
        <div className="microphone-meter">
          <meter aria-label="Уровень микрофона" min={0} max={1} value={level} />
          <span>Скажите несколько слов · проверка до 7 секунд</span>
        </div>
      )}
      {error && (
        <p className="device-error" role="alert">
          {error}
        </p>
      )}
      <p className="help">
        Выбор действует для чата, аватара и обоих движков озвучки. Нажмите
        «Сохранить», чтобы применять его после перезапуска. Проверка микрофона
        показывает уровень без записи и отправки речи; названия устройств могут
        появиться после неё.
      </p>
      <p className="help">
        Если выбранное устройство отключено, выберите другое или «По умолчанию
        Windows».
      </p>
    </div>
  );
}
