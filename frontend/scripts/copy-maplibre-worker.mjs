// MapLibre v6 loads its web worker from a URL. Bundlers (Turbopack) can't resolve it,
// so we serve the worker and its shared chunk as static files from /public/maplibre.
import { copyFileSync, mkdirSync } from "node:fs";

const src = "node_modules/maplibre-gl/dist";
const dest = "public/maplibre";
mkdirSync(dest, { recursive: true });
for (const f of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
  copyFileSync(`${src}/${f}`, `${dest}/${f}`);
}
