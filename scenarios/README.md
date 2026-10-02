# scenarios/

Seeded, reproducible SYNTHETIC scenarios. Every file is canonical JSON (sorted keys, LF) and is
fully determined by the `scenario.params` block stored inside it; `backend/tests/test_saved_scenarios.py`
regenerates each file and compares bytes.

| File | Season preset | Seed | Regions (bases) | How generated |
|---|---|---|---|---|
| `demo.json` | `monsoon` (default) | 42 | central, east_ne, south | `cd backend && python -m app.sim.generate --seed 42 --out ../scenarios/demo.json` |
| `monsoon_flood_hadr.json` | `monsoon` | 101 | central, east_ne, south | `scripts/generate_presets.py` |
| `winter_fog_north.json` | `winter_fog_north` | 202 | north, west, central | `scripts/generate_presets.py` |
| `cyclone_east_coast.json` | `post_monsoon_cyclone` | 303 | south, east_ne, central | `scripts/generate_presets.py` |
| `pre_monsoon_heat_dust.json` | `pre_monsoon_heat_dust` | 404 | west, central, north | `scripts/generate_presets.py` |

## What is real and what is not

- **Synthetic:** bases (codenames such as `BASE-C1`), aircraft (generic types FTR-A … TKR-E), crews,
  missions, threat zones, maintenance history, weather, scheduled events. All numeric performance
  values are illustrative placeholders. Not validated on real operations.
- **Real open data:** terrain elevation of the base sites (Open-Meteo elevation API, CC BY 4.0) and the
  `alternate_airfields` list (OurAirports, public domain, public civil airports). Each file lists these
  in `scenario.open_data_sources`; per-record `provenance.data_label` is `"open"` for the airports.
- Scenario dates are notional.

## Known limitation

`cyclone_east_coast` is named for its theme. The five INDIA_CONTEXT region boxes do not cover the
Bay of Bengal east coast (about 82–87 E), so its bases lie in the south, east/NE and central boxes
(see `docs/DECISIONS.md` D-17).
