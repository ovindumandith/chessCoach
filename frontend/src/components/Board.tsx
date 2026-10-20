import { Chess, type Square } from "chess.js";
import { useCallback, useMemo, useRef } from "react";
import { Chessboard, type Arrow } from "react-chessboard";

interface BoardProps {
  fen: string;
  orientation?: "white" | "black";
  /** Called with a legal UCI move. Omit for a read-only board. */
  onMove?: (uci: string) => void;
  /** Engine best move (green) and the move actually played (red), as UCI. */
  bestMove?: string | null;
  playedMove?: string | null;
  /** The opponent's best reply / threat (orange), as UCI. */
  threat?: string | null;
  /** Highlight the from/to squares of the move just played, as UCI. */
  lastMove?: string | null;
  size?: number;
  id?: string;
}

function toArrow(uci: string | null | undefined, color: string): Arrow[] {
  return uci ? [{ startSquare: uci.slice(0, 2), endSquare: uci.slice(2, 4), color }] : [];
}

const LAST_MOVE_STYLE = { background: "rgba(255, 214, 64, 0.45)" };

/** Board that validates moves with chess.js before reporting them (server re-validates). */
export function Board({
  fen,
  orientation = "white",
  onMove,
  bestMove,
  playedMove,
  threat,
  lastMove,
  size = 360,
  id,
}: BoardProps) {
  // Stable inputs: background data refreshes must not re-create the board's options and
  // disturb a drag in progress.
  const arrows = useMemo(
    () => [
      ...toArrow(playedMove, "rgba(200, 40, 40, 0.75)"),
      ...toArrow(threat, "rgba(230, 120, 20, 0.8)"),
      ...toArrow(bestMove, "rgba(20, 140, 60, 0.8)"),
    ],
    [playedMove, threat, bestMove],
  );
  const squareStyles = useMemo(
    () =>
      lastMove ? { [lastMove.slice(0, 2)]: LAST_MOVE_STYLE, [lastMove.slice(2, 4)]: LAST_MOVE_STYLE } : {},
    [lastMove],
  );
  const moveHandler = useRef(onMove);
  moveHandler.current = onMove;
  const canMove = Boolean(onMove);

  const onPieceDrop = useCallback(
    ({ sourceSquare, targetSquare }: { sourceSquare: string; targetSquare: string | null }) => {
      if (!moveHandler.current || !targetSquare) return false;
      const chess = new Chess(fen);
      try {
        // Auto-promote to a queen; under-promotion can be typed in SAN instead.
        const move = chess.move({ from: sourceSquare as Square, to: targetSquare as Square, promotion: "q" });
        moveHandler.current(move.from + move.to + (move.promotion ?? ""));
        return true;
      } catch {
        return false; // illegal: the piece snaps back
      }
    },
    [fen],
  );
  const options = useMemo(
    () => ({
      id,
      position: fen,
      boardOrientation: orientation,
      allowDragging: canMove,
      onPieceDrop,
      arrows,
      squareStyles,
      animationDurationInMs: 120, // snappy when stepping through a game with the keyboard
    }),
    [id, fen, orientation, canMove, onPieceDrop, arrows, squareStyles],
  );

  return (
    <div className="board" style={{ width: size, maxWidth: "100%" }}>
      <Chessboard options={options} />
    </div>
  );
}
