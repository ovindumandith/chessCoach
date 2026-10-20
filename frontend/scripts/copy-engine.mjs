// Copies the in-browser Stockfish build (lite, single-threaded WASM) into public/engine/,
// together with its GPLv3 licence, which must ship with the engine.
import { copyFileSync, mkdirSync } from "node:fs";

const src = "node_modules/stockfish";
const dest = "public/engine";
mkdirSync(dest, { recursive: true });
for (const file of ["bin/stockfish-19-lite-single.js", "bin/stockfish-19-lite-single.wasm", "Copying.txt"]) {
  copyFileSync(`${src}/${file}`, `${dest}/${file.split("/").pop()}`);
}
console.log("Stockfish (GPLv3) copied to public/engine/");
