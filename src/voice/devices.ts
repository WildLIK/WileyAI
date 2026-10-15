export function microphoneConstraints(deviceId = ""): MediaStreamConstraints {
  return {
    audio: {
      ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
      channelCount: 1,
      sampleRate: 16000,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  };
}

export function microphoneError(error: unknown): Error {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError")
      return new Error(
        "Нет доступа к микрофону. Разрешите его в настройках Windows.",
      );
    if (["NotFoundError", "OverconstrainedError"].includes(error.name))
      return new Error(
        "Выбранный микрофон недоступен. Подключите его или выберите другой в настройках звука.",
      );
    if (error.name === "NotReadableError")
      return new Error(
        "Не удалось открыть микрофон. Проверьте, не занят ли он другим приложением.",
      );
  }
  return error instanceof Error
    ? error
    : new Error("Не удалось подключить микрофон");
}

export async function selectOutput(audio: HTMLMediaElement, deviceId = "") {
  if (!audio.setSinkId) {
    if (deviceId)
      throw new Error("Эта версия приложения не поддерживает выбор динамика.");
    return;
  }
  try {
    await audio.setSinkId(deviceId);
  } catch {
    throw new Error(
      "Выбранный динамик недоступен. Подключите его или выберите другое устройство воспроизведения.",
    );
  }
}

/** All TTS engines and speaker checks share this output and cancellation path. */
export async function playAudio(
  blob: Blob,
  deviceId: string,
  signal: AbortSignal,
) {
  signal.throwIfAborted();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  const stop = () => audio.pause();
  signal.addEventListener("abort", stop, { once: true });
  try {
    await selectOutput(audio, deviceId);
    signal.throwIfAborted();
    await new Promise<void>((resolve, reject) => {
      const cancel = () => {
        cleanup();
        reject(new DOMException("Воспроизведение остановлено", "AbortError"));
      };
      const cleanup = () => {
        audio.onended = null;
        audio.onerror = null;
        signal.removeEventListener("abort", cancel);
      };
      audio.onended = () => {
        cleanup();
        resolve();
      };
      audio.onerror = () => {
        cleanup();
        reject(new Error("Не удалось воспроизвести озвучку"));
      };
      signal.addEventListener("abort", cancel, { once: true });
      void audio.play().catch((error) => {
        cleanup();
        reject(error);
      });
    });
  } finally {
    signal.removeEventListener("abort", stop);
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    URL.revokeObjectURL(url);
  }
}
