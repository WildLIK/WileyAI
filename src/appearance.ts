export type Appearance = {
  ui_theme: "aurora" | "ice" | "ember";
  ui_motion: "full" | "reduced";
  ui_glass: boolean;
};
export const themes = [
  {
    id: "aurora",
    name: "Аврора",
    description: "Кристаллические связи, бирюза и синий градиент",
    tag: "Тёмная",
  },
  {
    id: "ice",
    name: "Ледяной свет",
    description: "Светло-голубые панели и чистые синие акценты",
    tag: "Светлая",
  },
  {
    id: "ember",
    name: "Красный контур",
    description: "Графит, чёрное стекло и красная подсветка",
    tag: "Тёмная",
  },
] as const;
const defaults: Appearance = {
  ui_theme: "aurora",
  ui_motion: "full",
  ui_glass: true,
};
const cacheKey = "wiley-appearance";
export function validAppearance(value: unknown): Appearance {
  const saved = (
    value && typeof value === "object" ? value : {}
  ) as Partial<Appearance>;
  return {
    ui_theme: themes.some((theme) => theme.id === saved.ui_theme)
      ? saved.ui_theme!
      : defaults.ui_theme,
    ui_motion: saved.ui_motion === "reduced" ? "reduced" : "full",
    ui_glass: typeof saved.ui_glass === "boolean" ? saved.ui_glass : true,
  };
}
export function applyAppearance(value: Appearance) {
  const appearance = validAppearance(value);
  document.documentElement.dataset.theme = appearance.ui_theme;
  document.documentElement.dataset.motion = appearance.ui_motion;
  document.documentElement.dataset.glass = appearance.ui_glass ? "on" : "off";
  try {
    localStorage.setItem(cacheKey, JSON.stringify(appearance));
  } catch {
    /* Backend remains authoritative. */
  }
}
export function restoreAppearance() {
  try {
    applyAppearance(
      validAppearance(JSON.parse(localStorage.getItem(cacheKey) || "null")),
    );
  } catch {
    applyAppearance(defaults);
  }
  const visibility = () => {
    document.documentElement.dataset.windowHidden = String(document.hidden);
  };
  visibility();
  document.addEventListener("visibilitychange", visibility);
}
