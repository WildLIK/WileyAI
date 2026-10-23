export type AvatarPhase = "idle" | "listening" | "thinking" | "speaking";
export type AvatarEmotion =
  "neutral" | "happy" | "sad" | "angry" | "relaxed" | "surprised";
export type AvatarGesture =
  | "none"
  | "wave"
  | "nod"
  | "comfort"
  | "joy"
  | "cute"
  | "surprise"
  | "explain"
  | "think"
  | "praise"
  | "point"
  | "listen"
  | "thumbsup"
  | "shy"
  | "tired"
  | "dance"
  | "dance2"
  | "dance3";
export type AvatarSignal = {
  phase: AvatarPhase;
  emotion: AvatarEmotion;
  gesture: AvatarGesture;
  cue: string;
  voice?: boolean;
  energy?: number;
};
export type AvatarDemo = {
  signal: AvatarSignal;
  strength: number;
  still: boolean;
  label: string;
};
export type AvatarDemoState = {
  demo: AvatarDemo | null;
  owner: boolean;
  revision: number;
};
export type AvatarCapabilities = {
  expressions: string[];
  wings: number;
  gestures: boolean;
};
export type AvatarWindowState = {
  visible: boolean;
  clickThrough: boolean;
  minimal: boolean;
};
export const idleAvatar: AvatarSignal = {
  phase: "idle",
  emotion: "neutral",
  gesture: "none",
  cue: "",
  voice: false,
  energy: 0,
};

export const avatarPresets: {
  gesture: AvatarGesture;
  emotion: AvatarEmotion;
  label: string;
  example: string;
}[] = [
  {
    gesture: "joy",
    emotion: "happy",
    label: "Радостная поза",
    example: "Ура, у меня получилось!",
  },
  {
    gesture: "surprise",
    emotion: "surprised",
    label: "Удивление",
    example: "Вот это неожиданно!",
  },
  {
    gesture: "wave",
    emotion: "happy",
    label: "Приветствие",
    example: "Привет, Уайли!",
  },
  {
    gesture: "explain",
    emotion: "neutral",
    label: "Объяснение",
    example: "Объясни, как это работает",
  },
  {
    gesture: "think",
    emotion: "neutral",
    label: "Размышление",
    example: "Давай подумаем над этим",
  },
  {
    gesture: "praise",
    emotion: "happy",
    label: "Похвала",
    example: "Ты молодец, отлично помогла!",
  },
  {
    gesture: "point",
    emotion: "neutral",
    label: "Указание",
    example: "Что мне нужно сделать дальше?",
  },
  {
    gesture: "listen",
    emotion: "neutral",
    label: "Слушаю тебя",
    example: "Послушай меня внимательно",
  },
  {
    gesture: "thumbsup",
    emotion: "happy",
    label: "Палец вверх",
    example: "Всё верно, так и сделаем",
  },
  {
    gesture: "shy",
    emotion: "relaxed",
    label: "Смущение",
    example: "Ты смущаешься?",
  },
  {
    gesture: "tired",
    emotion: "relaxed",
    label: "Усталость",
    example: "Ты устала? Пора отдохнуть",
  },
  {
    gesture: "comfort",
    emotion: "sad",
    label: "Сочувствие",
    example: "Мне грустно, ничего не получается",
  },
];

/** Recent real turns, rather than the length of loaded/scrolling chat history. */
export class AvatarActivity {
  private turns: number[] = [];
  mark(now: number) {
    this.turns.push(now);
    if (this.turns.length > 32) this.turns.shift();
    return this.value(now);
  }
  value(now: number) {
    this.turns = this.turns.filter((at) => now - at < 60000 && now >= at);
    return (
      Math.round(
        Math.min(
          1,
          this.turns.reduce(
            (sum, at) => sum + Math.exp(-(now - at) / 18000),
            0,
          ) / 4,
        ) * 20,
      ) / 20
    );
  }
}

/** Conservative cues from this turn's text; no claim to detect a person's feelings. */
export function avatarReaction(
  text: string,
): Pick<AvatarSignal, "emotion" | "gesture"> {
  // Quoted examples/code are data, not the speaker's mood.
  const value = text
    .toLowerCase()
    .replace(/```[\s\S]*?(?:```|$)|«[^»]*»|"[^"\n]*"|“[^”]*”/gu, " ")
    .replace(
      /(^|[\s,.!?])не\s+(?:груст[а-я]*|расстро[а-я]*|злюсь|раздраж[а-я]*|устал[а-я]*|рад[аы]?|весел[а-я]*|весёл[а-я]*|счастлив[а-я]*)(?=$|[\s,.!?])/gu,
      " ",
    )
    .slice(-1600);
  if (
    /я (?:устал[аи]?|утомл[её]н[аы]?)|хочу спать|валюсь с ног|сил совсем нет/u.test(
      value,
    )
  )
    return { emotion: "relaxed", gesture: "tired" };
  if (
    /я (?:злюсь|в ярости)|меня (?:бесит|раздражает)|возмутительно|[😠😡]/u.test(
      value,
    )
  )
    return { emotion: "angry", gesture: "point" };
  if (
    /(?:ты|вы)[^.!?]{0,25}устал|пора отдохнуть|отдохни|пора спать/u.test(value)
  )
    return { emotion: "relaxed", gesture: "tired" };
  if (
    /\b(?:sad|sorry)\b|груст|печаль|расстро|сожале|сочувств|тревож|обидно|мне плохо|тяжело на душе|одинок|огорч|не получ|не работает|ошибк|извин|устал|злюсь|раздраж|боюсь|страшно|[😢😔😭😟💔]/u.test(
      value,
    )
  )
    return { emotion: "sad", gesture: "comfort" };
  if (
    /(?:ты|вы|уайли)[^.!?]{0,25}\sне\s+(?:милая|молодец|умница|лучшая)/u.test(
      value,
    )
  )
    return { emotion: "neutral", gesture: "none" };
  if (/смуща|застесня|стесняешь/u.test(value))
    return { emotion: "relaxed", gesture: "shy" };
  if (
    /(?:ты|вы|уайли)[^.!?]{0,35}(?:мил[а-я]*|красавиц|прелест|очарователь)|феечк|милая фея/u.test(
      value,
    )
  )
    return { emotion: "relaxed", gesture: "shy" };
  if (
    /(?:ты|вы|уайли)[^.!?]{0,35}(?:молодец|умниц|отлично помог|лучшая|лучш[еа-я]* помощ)|горжусь тобой/u.test(
      value,
    )
  )
    return { emotion: "happy", gesture: "praise" };
  if (/привет|здравств|доброе утро|добрый (?:день|вечер)/u.test(value))
    return { emotion: "happy", gesture: "wave" };
  if (/послушай|слушай меня|выслушай|расскажу тебе/u.test(value))
    return { emotion: "neutral", gesture: "listen" };
  if (
    /давай подумаем|подумай|поразмышля|дай подумать|надо подумать/u.test(value)
  )
    return { emotion: "neutral", gesture: "think" };
  if (
    /объясни|объясню|поясни|поясню|как это работает|например|дело в том/u.test(
      value,
    )
  )
    return { emotion: "neutral", gesture: "explain" };
  if (
    /что (?:мне )?(?:нужно|надо) сделать|следующий шаг|нужно сделать|надо сделать|сделай вот так/u.test(
      value,
    )
  )
    return { emotion: "neutral", gesture: "point" };
  if (
    /вс[её] верно|так и сделаем|соглас(?:ен|на)|одобряю|палец вверх|[👍]/u.test(
      value,
    )
  )
    return { emotion: "happy", gesture: "thumbsup" };
  if (
    /(?:^|[\s,.!?])ура(?=$|[\s,.!?])|получилось|счастлив|радост|радуюсь|весел[аоы]?|весёл|я рад[аы]?|я довольн|в восторге|прекрасное настроение|[😂😄🥳]/u.test(
      value,
    )
  )
    return { emotion: "happy", gesture: "joy" };
  if (
    /спасибо|благодар|отлично|здорово|(?:^|[\s,.!?])ура(?=$|[\s,.!?])|рад[аы]? помочь|получилось|счастлив|радост|радуюсь|[🙂😊😂😄👍]/u.test(
      value,
    )
  )
    return { emotion: "happy", gesture: "nod" };
  if (
    /удивитель|удивл[её]н|неожиданно|ничего себе|невероятно|потрясающе|\bwow\b|(?:^|\s)ого(?=$|[!\s.])|[😲😮🤯]/u.test(
      value,
    )
  )
    return { emotion: "surprised", gesture: "surprise" };
  if (
    /спокойной ночи|отдохни|всё хорошо|все хорошо|мне спокойно|умиротвор|на душе спокойно/u.test(
      value,
    )
  )
    return { emotion: "relaxed", gesture: "nod" };
  if (
    /\?\s*$|интересно|любопытно|сомнева|не уверена|попробуем разобраться/u.test(
      value,
    )
  )
    return { emotion: "neutral", gesture: "think" };
  return { emotion: "neutral", gesture: "none" };
}

export function avatarPhase(input: {
  playing: boolean;
  thinking: boolean;
  listening: boolean;
}): AvatarPhase {
  return input.playing
    ? "speaking"
    : input.thinking
      ? "thinking"
      : input.listening
        ? "listening"
        : "idle";
}

export function avatarZoom(value: number): number {
  return Number.isFinite(value) ? Math.min(6, Math.max(0.7, value)) : 1;
}
