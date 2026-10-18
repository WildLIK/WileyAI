import { useEffect, useRef } from "react";
import { themes, type Appearance } from "./appearance";

export function ThemeSwitch({
  value,
  onChange,
  disabled = false,
}: {
  value: Appearance;
  onChange: (patch: Partial<Appearance>) => void;
  disabled?: boolean;
}) {
  const root = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node))
        root.current?.removeAttribute("open");
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, []);
  return (
    <details
      className="theme-switch"
      ref={root}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          root.current?.removeAttribute("open");
          root.current?.querySelector("summary")?.focus();
        }
      }}
    >
      <summary aria-label="Выбрать тему оформления" title="Тема оформления">
        <span aria-hidden="true">◐</span>
        <span className="theme-switch-name">
          {themes.find((theme) => theme.id === value.ui_theme)?.name}
        </span>
      </summary>
      <div className="theme-menu" role="group" aria-label="Быстрый выбор темы">
        {themes.map((theme) => (
          <button
            type="button"
            key={theme.id}
            aria-pressed={value.ui_theme === theme.id}
            disabled={disabled}
            onClick={() => {
              onChange({ ui_theme: theme.id });
              root.current?.removeAttribute("open");
              root.current?.querySelector("summary")?.focus();
            }}
          >
            <i className={"theme-dot theme-" + theme.id} aria-hidden="true" />
            {theme.name}
            <span>{value.ui_theme === theme.id ? "✓" : theme.tag}</span>
          </button>
        ))}
      </div>
    </details>
  );
}

export function AppearancePanel({
  value,
  onChange,
  saving,
}: {
  value: Appearance;
  onChange: (patch: Partial<Appearance>) => void;
  saving: boolean;
}) {
  return (
    <div className="card appearance-panel">
      <div className="appearance-heading">
        <div>
          <span className="eyebrow">ВАШ ИНТЕРФЕЙС</span>
          <h2>Свет, цвет и движение</h2>
        </div>
        <span className="appearance-save" aria-live="polite">
          {saving ? "Сохраняю…" : "Сохраняется автоматически"}
        </span>
      </div>
      <p>
        Выберите настроение. Оформление применяется сразу в чате, настройках и
        окне аватара.
      </p>
      <div className="theme-gallery" role="group" aria-label="Темы оформления">
        {themes.map((theme) => (
          <button
            type="button"
            className={"theme-card theme-" + theme.id}
            key={theme.id}
            aria-pressed={value.ui_theme === theme.id}
            onClick={() => onChange({ ui_theme: theme.id })}
          >
            <span className="theme-preview" aria-hidden="true">
              <span className="preview-sidebar">
                <i />
                <i />
                <i />
              </span>
              <span className="preview-main">
                <i />
                <i />
                <i />
              </span>
              <span className="preview-orbit" />
            </span>
            <span className="theme-card-title">
              {theme.name}
              <span>
                {value.ui_theme === theme.id ? "Выбрана ✓" : theme.tag}
              </span>
            </span>
            <span className="theme-description">{theme.description}</span>
          </button>
        ))}
      </div>
      <div className="appearance-options">
        <label className="appearance-option">
          <span>
            <strong>Полупрозрачные панели</strong>
            <small>Стекло, мягкий свет и размытие внутри интерфейса</small>
          </span>
          <input
            type="checkbox"
            checked={value.ui_glass}
            onChange={(event) => onChange({ ui_glass: event.target.checked })}
          />
        </label>
        <label className="appearance-option">
          <span>
            <strong>Уменьшить движение</strong>
            <small>Неподвижный фон и статичные индикаторы процессов</small>
          </span>
          <input
            type="checkbox"
            checked={value.ui_motion === "reduced"}
            onChange={(event) =>
              onChange({ ui_motion: event.target.checked ? "reduced" : "full" })
            }
          />
        </label>
      </div>
      <p className="help">
        Анимации показывают реальные процессы. В простое активных индикаторов
        нет. Системная настройка уменьшения движения также учитывается. У
        «Туманности» декоративный фон плавно движется; в неактивном окне он
        замирает.
      </p>
    </div>
  );
}
