import { useState } from "react";

import { patch, skillLabel, type Page, type Weakness } from "../../api";
import { sideToMove, studentEvalText } from "../../verdict";
import { Board } from "../../components/Board";
import { ActionButton, Badge, Empty, ErrorBox, Loading, pct } from "../../components/ui";
import { useLoad, useTaxonomy } from "../../hooks";

const EVIDENCE_LABEL = { motif: "Verified motif", skill_inference: "Context rule", move_quality: "Unexplained error" };

export function ReviewTab({ studentId, canReview }: { studentId: string; canReview: boolean }) {
  const [status, setStatus] = useState("candidate");
  const query = status ? `&review_status=${status}` : "";
  const { data, error, loading, reload } = useLoad<Page<Weakness>>(
    `/students/${studentId}/weaknesses?limit=100${query}`,
  );
  const tax = useTaxonomy();

  return (
    <section>
      <div className="row">
        <label>
          Show{" "}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="candidate">Needs review</option>
            <option value="confirmed">Confirmed</option>
            <option value="corrected">Corrected</option>
            <option value="rejected">Rejected</option>
            <option value="">All</option>
          </select>
        </label>
        <span className="muted small">
          Confidence values are ordinal heuristics, not calibrated probabilities.
        </span>
      </div>
      {loading && <Loading />}
      <ErrorBox error={error} />
      {data && data.items.length === 0 && <Empty>Nothing here. Analyze games to create findings.</Empty>}
      <div className="grid">
        {data?.items.map((w) => (
          <WeaknessCard key={w.id} w={w} tax={tax} canReview={canReview} onDone={reload} />
        ))}
      </div>
    </section>
  );
}

function WeaknessCard({
  w,
  tax,
  canReview,
  onDone,
}: {
  w: Weakness;
  tax: ReturnType<typeof useTaxonomy>;
  canReview: boolean;
  onDone: () => Promise<void>;
}) {
  const [correcting, setCorrecting] = useState(false);
  const [code, setCode] = useState("");
  const e = w.evidence;
  const moveNo = Math.ceil(e.ply / 2);
  const review = (body: object) => patch(`/observations/${w.id}/review`, body).then(onDone);

  return (
    <article className="card weakness">
      <header>
        <strong>{skillLabel(tax, w.skill_code, w.subskill_code)}</strong>
        <Badge kind={w.evidence_type}>{EVIDENCE_LABEL[w.evidence_type]}</Badge>
        <Badge>{w.review_status}</Badge>
      </header>
      <Board fen={e.fen_before} size={240} bestMove={e.best_move_uci} playedMove={e.uci_move} />
      <p className="small">
        {w.game_white} – {w.game_black} {w.game_played_at ?? ""}, move {moveNo}: played <b>{e.san_move}</b> (
        {studentEvalText(e.eval_before_cp, e.eval_before_mate, sideToMove(e.fen_before))} →{" "}
        {studentEvalText(e.eval_after_cp, e.eval_after_mate, sideToMove(e.fen_before), true)})
        {e.best_line_san[0] && e.best_line_san[0] !== e.san_move && (
          <>
            , engine: <b>{e.best_line_san.slice(0, 4).join(" ")}</b>
          </>
        )}
        {e.refutation_san[0] && <>, opponent's best reply: {e.refutation_san[0]}</>}
      </p>
      <p className="small muted">
        Severity {pct(w.severity)} win-probability loss
        {typeof w.details.motif_kind === "string" && ` · ${w.details.motif_kind}`}
        {typeof w.details.rule === "string" && ` · rule: ${w.details.rule}`}
      </p>
      {canReview && w.review_status === "candidate" && (
        <div className="row">
          <ActionButton onClick={() => review({ action: "confirm" })}>Confirm</ActionButton>
          <ActionButton onClick={() => review({ action: "reject" })}>Reject</ActionButton>
          <button onClick={() => setCorrecting(!correcting)}>Correct…</button>
        </div>
      )}
      {correcting && tax && (
        <div className="row">
          <select value={code} onChange={(ev) => setCode(ev.target.value)}>
            <option value="">Choose the right skill</option>
            {Object.entries(tax.categories).flatMap(([cat, c]) =>
              Object.entries(c.subskills).map(([sub, s]) => (
                <option key={`${cat}.${sub}`} value={`${cat}.${sub}`}>
                  {c.name}: {s.name}
                </option>
              )),
            )}
          </select>
          <ActionButton
            disabled={!code}
            onClick={() => {
              const [skill_code, subskill_code] = code.split(".");
              return review({ action: "correct", skill_code, subskill_code });
            }}
          >
            Save
          </ActionButton>
        </div>
      )}
    </article>
  );
}
