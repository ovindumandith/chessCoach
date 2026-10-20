import { useState, type ReactNode } from "react";

import { errorText } from "../api";

export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="muted">{what}…</p>;
}

export function ErrorBox({ error }: { error: string | null }) {
  return error ? (
    <p className="error" role="alert">
      {error}
    </p>
  ) : null;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function Badge({ kind, children }: { kind?: string; children: ReactNode }) {
  return <span className={`badge ${kind ?? ""}`}>{children}</span>;
}

/** Button that shows progress and surfaces errors from its async action. */
export function ActionButton({
  onClick,
  children,
  className,
  disabled,
}: {
  onClick: () => Promise<unknown>;
  children: ReactNode;
  className?: string;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="action">
      <button
        className={className}
        disabled={busy || disabled}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await onClick();
          } catch (e) {
            setError(errorText(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Working…" : children}
      </button>
      {error && <span className="error inline">{error}</span>}
    </span>
  );
}

export function pct(x: number | null | undefined, digits = 0): string {
  return x === null || x === undefined ? "–" : `${(x * 100).toFixed(digits)}%`;
}

export const STATE_LABEL: Record<string, string> = {
  recurring_weakness: "Recurring weakness",
  emerging_pattern: "Emerging pattern",
  insufficient_evidence: "Insufficient evidence",
  no_issue_detected: "No issue detected",
};
