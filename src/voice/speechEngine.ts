import type { Settings, SpeechSettings } from "../api";

export const usesOpenVoice = (
  config: Pick<Settings, "tts_engine" | "openvoice_enabled">,
) =>
  config.openvoice_enabled &&
  ["piper", "silero", "silero_v5_6"].includes(config.tts_engine);

export function selectSpeechEngine(
  value: string,
  config: Settings,
): Partial<SpeechSettings> {
  if (value === "openvoice")
    return {
      tts_engine: ["piper", "silero", "silero_v5_6"].includes(config.tts_engine)
        ? config.tts_engine
        : "piper",
      openvoice_enabled: true,
      tts_voice: "",
    };
  return {
    tts_engine: value as Settings["tts_engine"],
    openvoice_enabled: false,
    tts_voice: "",
  };
}
