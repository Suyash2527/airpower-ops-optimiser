# DECISIONS

Log of defaults chosen where the specs were ambiguous, and of any deviation from the fixed stack.
Format: `D-nn · date · decision — rationale`.

## Session 1 (Phases 0–1)

- **D-01 · 2026-10-02 · Nested git repo.** `git init -b main` inside `D:\AirPower`. The enclosing `D:\` repo is a drive-wide untracked tree; commits there would be unsafe. The README also says to `git init` in the project folder.
- **D-02 · Repo root.** `CLAUDE.md` shows `airpower/` as the root; the repo root is `D:\AirPower` itself.
- **D-03 · Python environment.** Python 3.13 is installed (spec: 3.11+). Dependencies go in `backend/.venv`. `requires-python = ">=3.11"`.
- **D-04 · Storage in Phase 1.** SQLModel tables exist for every entity. Scenarios are persisted as canonical JSON files in `scenarios/` plus a lightweight registry row in SQLite, and the snapshot endpoint is served by rebuilding from the stored scenario. Full per-entity table writes and `state_version` come with the fusion layer (Phase 2).
- **D-05 · Weather in the generator.** The generator emits a synthetic hourly forecast per base (`source="SYNTHETIC"`). The real Open-Meteo adapter is Phase 7.
- **D-06 · Placeholder numbers.** All aircraft-type, loadout, crew-duty and weight numbers are illustrative placeholders. Each scenario file carries a `notes` field saying so.
- **D-07 · Compose database.** `db` is PostgreSQL; the password in `.env.example` is a placeholder. Dev uses SQLite, no Docker.
- **D-08 · Map tiles.** MapLibre with a free raster OpenStreetMap style, attribution visible. Terms check for the demo: to be re-verified before any public demo (OSM tile usage policy discourages heavy use of the public tile server); not a blocker for a local prototype.
- **D-09 · Scripts instead of Makefile.** Windows host, so `scripts/*.ps1` / plain commands in the README rather than a Makefile.
- **D-10 · Scenario JSON determinism.** Canonical form: `sort_keys=True`, 2-space indent, `ensure_ascii`, floats rounded to fixed decimals at generation time, trailing newline, LF line endings.
- **D-11 · 2026-10-02 · Windows Application Control blocks some compiled packages.** On this machine, `import sklearn` and `import pyproj` fail with "An Application Control policy has blocked this file" (unsigned `.pyd` files), and `python -m ruff` is blocked, while `.venv/Scripts/ruff.exe` run directly works. We did not attempt to bypass the policy. Phases 0–1 import neither library. Consequence for later phases: `pyproj` (Phase 3) and `scikit-learn` (Phase 7) need the user to allow these files or run in Docker/WSL. Linting here is run as `backend/.venv/Scripts/ruff.exe check .`.
- **D-12 · 2026-10-02 · Neutral map region.** Fictional bases are placed in a bounding box of lat −28…−22, lon 130…138 (sparsely populated interior), shown on open OSM tiles. This follows HONESTY.md ("fictional base names on a neutral map region") and avoids implying real military sites. The region is a presentation choice, not a claim about any real location.
- **D-13 · 2026-10-02 · MapLibre v6 worker.** `maplibre-gl` v6 has no default export and its web worker fails under Turbopack. The worker and shared chunk are copied to `frontend/public/maplibre/` by `scripts/copy-maplibre-worker.mjs` (run by `predev`/`prebuild`; the folder is git-ignored) and wired with `setWorkerUrl`. No new dependency.
- **D-14 · 2026-10-02 · Frontend scaffold choices.** Next.js 16 (App Router, Turbopack), Tailwind 4. System fonts instead of `next/font/google` to avoid a build-time network fetch. The scaffold's dark-mode CSS was removed (out of scope). Scaffold-generated `frontend/AGENTS.md` and `frontend/CLAUDE.md` are kept as generated.
- **D-15 · 2026-10-02 · Compose `db` service vs. database driver.** Compose defines a PostgreSQL `db` service as the spec requires, but the stack list contains no PostgreSQL driver (e.g. `psycopg`), and adding one needs approval. Until then the `api` service uses SQLite on a volume. Validated with `docker compose --env-file .env.example config` only; images were not built in Phases 0–1 (end-to-end compose check is Task 8.5).
