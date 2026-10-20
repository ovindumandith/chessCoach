// Live in-browser Stockfish (WASM in a Web Worker) for exploring positions.
// Exploration only: nothing computed here is stored or feeds profiles, which use the
// fixed-depth server analysis so results stay reproducible.

const ENGINE_URL = "/engine/stockfish-19-lite-single.js";

export interface EngineLine {
  multipv: number;
  depth: number;
  /** White's point of view. Exactly one of cp / mate is set. */
  cp: number | null;
  mate: number | null;
  pv: string[]; // UCI moves
}

export interface EngineUpdate {
  depth: number;
  lines: EngineLine[];
  done: boolean;
}

type Listener = (u: EngineUpdate) => void;

export class LiveEngine {
  private worker: Worker;
  private ready: Promise<void>;
  private searching = false;
  private pending: { fen: string; depth: number } | null = null;
  private fen = "";
  private lines = new Map<number, EngineLine>();
  private listener: Listener = () => {};
  private multipv: number;

  constructor(multipv = 3) {
    this.multipv = multipv;
    this.worker = new Worker(ENGINE_URL);
    this.ready = new Promise((resolve) => {
      const onReady = (e: MessageEvent) => {
        if (String(e.data) === "readyok") {
          this.worker.removeEventListener("message", onReady);
          resolve();
        }
      };
      this.worker.addEventListener("message", onReady);
    });
    this.worker.addEventListener("message", (e) => this.onLine(String(e.data)));
    this.send("uci");
    this.send(`setoption name MultiPV value ${multipv}`);
    this.send("isready");
  }

  onUpdate(fn: Listener) {
    this.listener = fn;
  }

  /** Analyse a position; any running search is stopped first. */
  async analyse(fen: string, depth = 22) {
    await this.ready;
    this.pending = { fen, depth };
    if (this.searching) this.send("stop"); // its bestmove will start the pending search
    else this.startPending();
  }

  stop() {
    this.pending = null;
    if (this.searching) this.send("stop");
  }

  terminate() {
    this.worker.terminate();
  }

  private send(cmd: string) {
    this.worker.postMessage(cmd);
  }

  private startPending() {
    if (!this.pending) return;
    const { fen, depth } = this.pending;
    this.pending = null;
    this.fen = fen;
    this.lines.clear();
    this.searching = true;
    this.send(`position fen ${fen}`);
    this.send(`go depth ${depth}`);
  }

  private onLine(line: string) {
    if (line.startsWith("bestmove")) {
      this.searching = false;
      if (this.pending) this.startPending();
      else this.emit(true);
      return;
    }
    // Ignore output from a search that is being replaced.
    if (!this.searching || this.pending || !line.startsWith("info ") || !line.includes(" pv ")) return;
    if (line.includes(" lowerbound") || line.includes(" upperbound")) return;
    const t = line.split(" ");
    const num = (key: string) => {
      const i = t.indexOf(key);
      return i >= 0 ? Number(t[i + 1]) : null;
    };
    const depth = num("depth") ?? 0;
    const multipv = num("multipv") ?? 1;
    const scoreAt = t.indexOf("score");
    if (scoreAt < 0) return;
    const kind = t[scoreAt + 1];
    const value = Number(t[scoreAt + 2]);
    // UCI scores are from the side to move; convert to White's point of view.
    const sign = this.fen.split(" ")[1] === "b" ? -1 : 1;
    const pv = t.slice(t.indexOf("pv") + 1);
    this.lines.set(multipv, {
      multipv,
      depth,
      cp: kind === "cp" ? sign * value : null,
      mate: kind === "mate" ? sign * value : null,
      pv,
    });
    if (multipv === this.multipv || this.lines.size === 1) this.emit(false);
  }

  private emit(done: boolean) {
    const lines = [...this.lines.values()].sort((a, b) => a.multipv - b.multipv);
    this.listener({ depth: Math.max(0, ...lines.map((l) => l.depth)), lines, done });
  }
}
