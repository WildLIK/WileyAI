import { useId } from "react";

/** Native checkbox behavior, switch semantics, and a clickable full row. */
export function SettingsSwitch({ label, description, checked, disabled = false, onChange }: {
  label: string; description: string; checked: boolean; disabled?: boolean; onChange(value: boolean): void;
}) {
  const id = useId();
  return <label className={"settings-switch" + (disabled ? " is-disabled" : "")}>
    <span className="settings-switch-copy"><span id={id + "-label"}>{label}</span><small id={id + "-description"}>{description}</small></span>
    <input type="checkbox" role="switch" aria-labelledby={id + "-label"} aria-describedby={id + "-description"} checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
    <span className="settings-switch-track" aria-hidden="true"><span /></span>
  </label>;
}
