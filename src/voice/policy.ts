/** An active session keeps the saved snapshot taken at its explicit start. */
export type VoicePolicyConfig = {
  stt_environment: "normal" | "music";
  conversation_wake_required: boolean;
  conversation_barge_in: boolean;
  conversation_listen_while_thinking: boolean;
  conversation_wake_word: string;
  stt_model: string;
  conversation_queue_mode?: "sequential" | "latest" | "queue";
};
export type VoiceSessionPolicy = VoicePolicyConfig & { startedManually: true; backgroundWake: false };
export function activationPolicy(config: VoicePolicyConfig, role: "main" | "barge" = "main") {
  if (role === "barge") return { required: true, reason: "barge_in" } as const;
  if (config.stt_environment === "music") return { required: true, reason: "music_profile" } as const;
  if (config.conversation_wake_required) return { required: true, reason: "user_setting" } as const;
  return { required: false, reason: "not_required" } as const;
}
export function sessionPolicy(config: VoicePolicyConfig): VoiceSessionPolicy {
  return { stt_environment: config.stt_environment, conversation_wake_required: config.conversation_wake_required,
    conversation_barge_in: config.conversation_barge_in, conversation_listen_while_thinking: config.conversation_listen_while_thinking,
    conversation_wake_word: config.conversation_wake_word, stt_model: config.stt_model, conversation_queue_mode: config.conversation_queue_mode ?? "sequential", startedManually: true, backgroundWake: false };
}
export const policyReasons = { barge_in: "перебивание озвучки", music_profile: "защита от музыкального фона", user_setting: "ваша настройка", not_required: "свободный разговор без имени" };
