import { Chess, type Square } from "chess.js";
import { Chessboard, type Arrow } from "react-chessboard";

interface BoardProps {
  fen: string;
  orientation?: "white" | "black";
  /** Called with a legal UCI move. Omit for a read-only board. */
  onMove?: (uci: string) => void;
  /** Engine best move (green) and the move actually played (red), as UCI. */
  bestMove?: string | null;
  playedMove?: string | null;
  size?: number;
  id?: string;
}

function toArrow(uci: string | null | undefined, color: string): Arrow[] {
  return uci ? [{ startSquare: uci.slice(0, 2), endSquare: uci.slice(2, 4), color }] : [];
}

/** Board that validates moves with chess.js before reporting them (server re-validates). */
export function Board({ fen, orientation = "white", onMove, bestMove, playedMove, size = 360, id }: BoardProps) {
  const arrows = [...toArrow(playedMove, "rgba(200, 40, 40, 0.75)"), ...toArrow(bestMove, "rgba(20, 140, 60, 0.8)")];

  function onPieceDrop({ sourceSquare, targetSquare }: { sourceSquare: string; targetSquare: string | null }) {
    if (!onMove || !targetSquare) return false;
    const chess = new Chess(fen);
    try {
      // Auto-promote to a queen; under-promotion can be typed in SAN instead.
      const move = chess.move({ from: sourceSquare as Square, to: targetSquare as Square, promotion: "q" });
      onMove(move.from + move.to + (move.promotion ?? ""));
      return true;
    } catch {
      return false; // illegal: the piece snaps back
    }
  }

  return (
    <div className="board" style={{ width: size, maxWidth: "100%" }}>
      <Chessboard
        options={{
          id,
          position: fen,
          boardOrientation: orientation,
          allowDragging: Boolean(onMove),
          onPieceDrop,
          arrows,
        }}
      />
    </div>
  );
}
