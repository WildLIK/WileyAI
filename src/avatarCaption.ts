import type {
  AvatarEmotion,
  AvatarGesture,
  AvatarPhase,
} from "./avatarBehavior";

const captions: Partial<Record<AvatarGesture, [string, string]>> = {
  wave: ["Приветствие", "Привет! Рада тебя видеть"],
  nod: ["Кивок", "Хорошо, я поняла"],
  comfort: ["Сочувствие", "Я рядом, давай разберёмся"],
  joy: ["Радость", "Ура, получилось!"],
  surprise: ["Удивление", "Вот это неожиданно!"],
  cute: ["Удивление", "Вот это неожиданно!"],
  explain: ["Объяснение", "Сейчас объясню"],
  think: ["Размышление", "Дай подумать…"],
  praise: ["Радость от похвалы", "Спасибо, мне очень приятно!"],
  point: ["Указание", "Вот что нужно сделать"],
  listen: ["Слушаю тебя", "Я внимательно слушаю"],
  thumbsup: ["Палец вверх", "Всё верно, так и сделаем"],
  shy: ["Смущение", "Немного смущаюсь…"],
  tired: ["Усталость", "Пора немного отдохнуть"],
  dance: ["Танец", "Парю в ритме музыки"],
  dance2: ["Танец 2", "Кружусь под музыку"],
  dance3: ["Танец 3", "Шаг, поворот — и полетели!"],
};
export function avatarCaption(
  pose: AvatarGesture,
  emotion: AvatarEmotion,
  phase: AvatarPhase,
) {
  const fallback: [string, string] =
    phase === "thinking"
      ? captions.think!
      : phase === "listening"
        ? captions.listen!
        : phase === "speaking"
          ? captions.explain!
          : emotion === "happy"
            ? ["Радость", "Рада помочь"]
            : emotion === "surprised"
              ? captions.surprise!
              : emotion === "sad"
                ? captions.comfort!
                : emotion === "angry"
                  ? ["Злость", "Это возмущает"]
                  : emotion === "relaxed"
                    ? ["Спокойствие", "Немного отдыхаю"]
                    : ["В покое", "Готова помочь"];
  const [name, text] = captions[pose] || fallback;
  return { name, text };
}
