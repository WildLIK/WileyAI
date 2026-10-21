import { useState } from "react";
import {
  avatarPresets,
  idleAvatar,
  type AvatarDemo,
  type AvatarEmotion,
  type AvatarGesture,
  type AvatarPhase,
} from "./avatarBehavior";

const faces: { emotion: AvatarEmotion; label: string }[] = [
  { emotion: "neutral", label: "Нейтрально" },
  { emotion: "happy", label: "Радость" },
  { emotion: "sad", label: "Грусть" },
  { emotion: "angry", label: "Злость" },
  { emotion: "surprised", label: "Удивление" },
  { emotion: "relaxed", label: "Спокойствие" },
];
export const neutralDemo = (): AvatarDemo => ({
  signal: { ...idleAvatar, cue: crypto.randomUUID() },
  strength: 0.8,
  still: true,
  label: "Нейтрально",
});

export function AvatarTests({
  value,
  expressions,
  wings,
  gestures,
  onChange,
  onClose,
}: {
  value: AvatarDemo;
  expressions: string[];
  wings: number;
  gestures: boolean;
  onChange(value: AvatarDemo): void;
  onClose(): void;
}) {
  const [tab, setTab] = useState("faces");
  function show(
    label: string,
    emotion: AvatarEmotion,
    gesture: AvatarGesture = "none",
    phase: AvatarPhase = "idle",
    still = true,
  ) {
    onChange({
      ...value,
      label,
      still,
      signal: {
        ...idleAvatar,
        emotion,
        gesture,
        phase,
        cue: crypto.randomUUID(),
      },
    });
  }
  return (
    <section className="avatar-tests" aria-label="Проверка эмоций и жестов">
      <div className="avatar-tests-title">
        <strong>Проверка персонажа</strong>
        <button aria-label="Завершить проверку персонажа" onClick={onClose}>
          ×
        </button>
      </div>
      <div
        className="avatar-test-tabs"
        role="tablist"
        aria-label="Вид проверки персонажа"
      >
        <button
          role="tab"
          aria-selected={tab === "faces"}
          onClick={() => setTab("faces")}
        >
          Эмоции
        </button>
        <button
          role="tab"
          aria-selected={tab === "poses"}
          onClick={() => setTab("poses")}
        >
          Позы феи
        </button>
      </div>
      {tab === "faces" ? (
        <div className="avatar-test-buttons">
          {faces.map(({ emotion, label }) => (
            <button
              key={emotion}
              aria-pressed={value.label === label}
              disabled={emotion !== "neutral" && !expressions.includes(emotion)}
              title={
                emotion === "neutral" || expressions.includes(emotion)
                  ? label
                  : "У этой VRM нет привязки выражения"
              }
              onClick={() => show(label, emotion)}
            >
              {label}
            </button>
          ))}
        </div>
      ) : (
        <div className="avatar-test-buttons">
          {avatarPresets.map((preset) => (
            <button
              key={preset.gesture}
              disabled={!gestures}
              aria-pressed={value.label === preset.label}
              title={preset.example}
              onClick={() =>
                show(
                  preset.label,
                  preset.emotion,
                  preset.gesture,
                  "idle",
                  false,
                )
              }
            >
              {preset.label}
            </button>
          ))}
        </div>
      )}
      <div className="avatar-test-buttons gestures">
        <button
          disabled={!gestures}
          aria-pressed={value.label === "Помахать"}
          onClick={() => show("Помахать", "happy", "wave", "idle", false)}
        >
          Помахать
        </button>
        <button
          disabled={!gestures}
          aria-pressed={value.label === "Кивнуть"}
          onClick={() => show("Кивнуть", "neutral", "nod", "idle", false)}
        >
          Кивнуть
        </button>
        <button
          disabled={!expressions.includes("aa") && !expressions.includes("ou")}
          aria-pressed={value.label === "Губы"}
          onClick={() => show("Губы", "neutral", "none", "speaking")}
        >
          Губы
        </button>
        <button
          aria-pressed={value.label === "Думает"}
          onClick={() => show("Думает", "neutral", "none", "thinking", false)}
        >
          Думает
        </button>
        <button
          aria-pressed={value.label === "Движения"}
          onClick={() => show("Движения", "neutral", "none", "idle", false)}
        >
          Движения
        </button>
        <button onClick={onClose}>Авто</button>
      </div>
      <label className="avatar-test-strength">
        Сила проверки: {Math.round(value.strength * 100)}%
        <input
          aria-label="Сила проверки выражения"
          type="range"
          min="0"
          max="100"
          step="5"
          value={Math.round(value.strength * 100)}
          onChange={(event) =>
            onChange({ ...value, strength: Number(event.target.value) / 100 })
          }
        />
      </label>
      <small>
        Без озвучки. В тесте поза держится до следующего выбора. Костей крыльев:{" "}
        {wings}.
      </small>
      <small>
        {
          avatarPresets.find((item) => item.gesture === value.signal.gesture)
            ?.example
        }
      </small>
    </section>
  );
}
