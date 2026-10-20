import type { VerdictKind } from "../verdict";

export interface GraphPoint {
  ply: number;
  /** Winning chances 0..1 from the student's side, or null if unknown. */
  value: number | null;
  mark?: VerdictKind;
  /** The opponent's move (drawn as a hollow marker). */
  opponent?: boolean;
}

const W = 600;
const H = 90;

/** Winning chances over the game. Click anywhere to jump to that move. */
export function EvalGraph({
  points,
  totalPlies,
  currentPly,
  onSelect,
  you,
}: {
  points: GraphPoint[];
  totalPlies: number;
  currentPly: number;
  onSelect: (ply: number) => void;
  you: "white" | "black";
}) {
  if (totalPlies === 0) return null;
  const x = (ply: number) => (ply / totalPlies) * W;
  const y = (v: number) => H - v * H;
  const known = points.filter((p) => p.value !== null) as (GraphPoint & { value: number })[];
  const line = known.map((p, i) => `${i ? "L" : "M"}${x(p.ply).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const area = known.length ? `${line} L${x(known[known.length - 1].ply)},${H} L${x(known[0].ply)},${H} Z` : "";

  return (
    <figure className="evalgraph">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="Your winning chances over the game; click to jump to a move"
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          onSelect(Math.max(0, Math.min(totalPlies, Math.round(((e.clientX - r.left) / r.width) * totalPlies))));
        }}
      >
        <rect x="0" y="0" width={W} height={H} className="eg-bg" />
        <line x1="0" x2={W} y1={H / 2} y2={H / 2} className="eg-mid" />
        {area && <path d={area} className="eg-area" />}
        {line && <path d={line} className="eg-line" />}
        {known
          .filter((p) => p.mark && p.mark !== "best" && p.mark !== "good")
          .map((p) => (
            <circle
              key={p.ply}
              cx={x(p.ply)}
              cy={y(p.value)}
              r="4"
              className={`eg-dot ${p.mark} ${p.opponent ? "opp" : ""}`}
            />
          ))}
        <line x1={x(currentPly)} x2={x(currentPly)} y1="0" y2={H} className="eg-cursor" />
      </svg>
      <figcaption className="muted small">
        Your winning chances as {you === "white" ? "White" : "Black"}: top = you are winning, bottom = your opponent is.
        Filled dots: your mistakes; hollow dots: your opponent's
      </figcaption>
    </figure>
  );
}
