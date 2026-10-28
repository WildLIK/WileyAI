export const SETTINGS_SECTIONS = [
  { id: "personality", label: "Личность", icon: "◉" },
  { id: "appearance", label: "Оформление", icon: "◐" },
  { id: "brain", label: "Мозг", icon: "⬡" },
  { id: "speech", label: "Озвучка", icon: "♪" },
  { id: "microphone", label: "Микрофон и разговор", icon: "◌" },
  { id: "mobile", label: "Телефон", icon: "▯" },
  { id: "search", label: "Поиск", icon: "⌕" },
  { id: "avatar", label: "Аватар", icon: "◇" },
  { id: "data", label: "Данные и копии", icon: "▤" },
] as const;
export type SettingsSection = (typeof SETTINGS_SECTIONS)[number]["id"];

export function SettingsNavigation({
  active,
  onChange,
}: {
  active: SettingsSection;
  onChange: (section: SettingsSection) => void;
}) {
  return (
    <nav
      className="settings-navigation"
      role="tablist"
      aria-label="Разделы настроек"
      aria-orientation="vertical"
    >
      {SETTINGS_SECTIONS.map((item, index) => (
        <button
          key={item.id}
          id={"settings-tab-" + item.id}
          role="tab"
          type="button"
          aria-selected={active === item.id}
          aria-controls={"settings-panel-" + item.id}
          tabIndex={active === item.id ? 0 : -1}
          onClick={(event) => {
            onChange(item.id);
            event.currentTarget.closest(".settings-page")?.scrollTo({ top: 0 });
          }}
          onKeyDown={(event) => {
            let next = index;
            if (["ArrowRight", "ArrowDown"].includes(event.key))
              next = (index + 1) % SETTINGS_SECTIONS.length;
            else if (["ArrowLeft", "ArrowUp"].includes(event.key))
              next =
                (index + SETTINGS_SECTIONS.length - 1) %
                SETTINGS_SECTIONS.length;
            else if (event.key === "Home") next = 0;
            else if (event.key === "End") next = SETTINGS_SECTIONS.length - 1;
            else return;
            event.preventDefault();
            onChange(SETTINGS_SECTIONS[next].id);
            document
              .getElementById("settings-tab-" + SETTINGS_SECTIONS[next].id)
              ?.focus();
          }}
        >
          <span aria-hidden="true">{item.icon}</span>
          {item.label}
        </button>
      ))}
    </nav>
  );
}
