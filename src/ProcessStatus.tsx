export type ProcessKind =
  "brain" | "search" | "document" | "voice" | "listen" | "download" | "upload";
export function ProcessStatus({
  kind,
  label,
  detail,
  compact = false,
}: {
  kind: ProcessKind;
  label: string;
  detail?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={"process-status process-" + kind + (compact ? " compact" : "")}
      role="status"
      aria-label={label}
      aria-live="polite"
      data-process={kind}
    >
      <span className="process-glyph" aria-hidden="true">
        {kind === "voice" || kind === "listen" ? (
          <span className="process-wave">
            {[0, 1, 2, 3, 4].map((index) => (
              <i key={index} />
            ))}
          </span>
        ) : (
          <svg viewBox="0 0 40 40" fill="none">
            <circle className="process-orbit" cx="20" cy="20" r="17" />
            {kind === "brain" ? (
              <>
                <path d="M12 12 28 14 20 29 12 12 11 26 28 14" />
                <circle cx="12" cy="12" r="2.3" />
                <circle cx="28" cy="14" r="2.3" />
                <circle cx="20" cy="29" r="2.3" />
              </>
            ) : kind === "search" ? (
              <>
                <circle cx="18" cy="18" r="7" />
                <path d="m23 23 6 6" />
              </>
            ) : kind === "document" ? (
              <>
                <path d="M13 10h10l5 5v15H13z M23 10v6h5 M17 21h7 M17 25h6" />
              </>
            ) : (
              <>
                <path
                  d={
                    kind === "download"
                      ? "M20 10v17m-6-6 6 6 6-6"
                      : "M20 28V11m-6 6 6-6 6 6"
                  }
                />
                <path d="M12 29v3h16v-3" />
              </>
            )}
          </svg>
        )}
      </span>
      <span className="process-copy">
        <strong>{label}</strong>
        {detail && <small>{detail}</small>}
      </span>
      <span className="process-track" aria-hidden="true">
        <i />
      </span>
    </div>
  );
}
