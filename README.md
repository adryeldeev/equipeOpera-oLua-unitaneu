---
title: LanderBnB
emoji: 🌙
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8001
pinned: false
short_description: Sun & Earth visibility at lunar south pole landing sites
---

# LanderBnB: Lunar South Pole Landing Planner

A web planning tool. For a landing site near the lunar south pole and a landing date, it shows whether the
**Sun** (power) and the **Earth** (direct-to-Earth communication) will be above the real terrain, and how the
outcome changes if the landing slips. Built for mission planners, educators and the general public
(NASA Space Apps Challenge 2026).

> **Status:** **real** ephemerides (Sun and Earth, JPL DE440) in `data/sky/` and a **real** terrain horizon
> (LRO LOLA) in `data/horizon/` for the 5 polar sites. Only Apollo 11, outside the polar maps, keeps a mock
> horizon (`"mock": true`). Fully synthetic data lives in `data_mock/`.

## Architecture

```
  NAIF (DE440 kernels, download)          LOLA/PDS (polar DEMs, download)
            │ Skyfield                              │ numpy (reads the .img directly)
            ▼                                       ▼
  pipeline/ephemeris.py                    pipeline/horizon.py
  sky: Sun and Earth (az, el, rad_deg)     horizon: horizon_deg[360]
            └─────────────────┬─────────────────────┘
                              ▼
                     pipeline/metrics.py
          visibility, % of time, longest periods,
          score, class, uncertainty, delay series
                              │
            ┌─────────────────┴──────────────────┐
            ▼                                    ▼
   api/ (FastAPI, port 8001)            pipeline/export.py
   ephemeris + metrics on demand        data/*.json (fallback) and --check
            │                                    │
            └────────────►  front  ◄─────────────┘
                 web/ (LanderBnB: HTML/CSS/JS + Three.js)
```

- **pipeline/**: Python computation. Knows nothing about the front end.
- **data/**: pipeline → front-end contract (versioned). Also the fallback if the ephemeris cannot load.
- **web/**: read-only. Never writes.
- The JPL Horizons API is used **for validation only**, never at run time.

```
.
├── Dockerfile                  # API + site in one container (hosting)
├── pipeline/
│   ├── config/sites.yaml       # landing sites (the origin of each point is documented)
│   ├── ephemeris.py            # Sun/Earth seen from a site: library + CLI (Skyfield, DE440)
│   ├── horizon.py              # terrain horizon (LOLA DEMs): library + CLI
│   ├── metrics.py              # visibility, metrics, score, uncertainty, delay
│   ├── export.py               # data/sites.json, _meta.json and the contract --check
│   ├── tests/                  # pytest (no network)
│   ├── tools/gerar_mock.py     # synthetic data in data_mock/
│   ├── tools/escolher_pontos.py   # derives landing points from the DEM (summit, best-lit rim)
│   ├── tools/gerar_texturas_lua.py # 3D Moon textures (south polar cap from LOLA)
│   └── tools/validar_horizons.py  # checks ephemeris against the Horizons API
├── api/                        # FastAPI: main.py, tests/, requirements*.txt
├── web/                        # LanderBnB front end: index.html, style.css, js/, assets/, tests/
├── data/                       # sites.json, _meta.json, horizon/<id>.json, sky/<id>.json, sky/_meta.json
├── data_mock/                  # same contract, synthetic data
├── cache/                      # kernels, DEMs, Horizons responses (not in git)
└── docker-compose.yml
```

## Running it

### Locally

Requirements: Python 3.11+ and a modern browser.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1              # Linux/macOS: source .venv/bin/activate
pip install -r api/requirements-dev.txt  # includes the pipeline and pytest

uvicorn api.main:app --port 8001         # from the REPOSITORY ROOT: starts the API and serves the site
```

Open **http://localhost:8001/**. The interactive API docs are at http://localhost:8001/docs.

You can also serve the front end separately (`python -m http.server 8000` at the root, then open
http://localhost:8000/web/); it finds the API at `localhost:8001` on its own. Opening `web/index.html` by
double-clicking **does not work**, because browsers block `fetch` on `file://`.

If `Activate.ps1` is blocked: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.

### Docker

```powershell
docker build -t landerbnb .
docker run -p 8001:8001 landerbnb        # http://localhost:8001/

docker compose up web api                # front end :8080/web/ and API :8001/docs
docker compose run --rm pipeline python -m pipeline.export --check
```

The `pipeline` compose service uses the `tools` profile: it only runs on demand.

### Pipeline commands

```powershell
# Sky (ephemerides) for 2027, 1 h step. Downloads ~45 MB of kernels into cache/ the first time.
python -m pipeline.ephemeris --start 2027-01-01 --days 365 --step-min 60 --out data/sky

# Real horizon of the polar sites. Downloads ~145 MB of DEMs into cache/lola/ the first time.
python -m pipeline.horizon --out data/horizon
python -m pipeline.horizon --out data/horizon --site malapert --altura-observador 2

# sites.json from the YAML + check of data/sky and data/horizon
python -m pipeline.export --sites pipeline/config/sites.yaml --out data
python -m pipeline.export --out data --site malapert --start 2027-03-01 --days 44

# Validate EVERY JSON in data/ and data_mock/ (non-zero exit code on errors)
python -m pipeline.export --check

# Tests (no network) and validation against Horizons (network)
python -m pytest pipeline/tests api/tests -v
node --test web/tests/geo.test.mjs
python pipeline/tools/validar_horizons.py

# Synthetic data
python pipeline/tools/gerar_mock.py
```

`export` **does not recompute** the sky or the horizon: it writes `data/sites.json` and `data/_meta.json`
(generation date and which files are mock) and reports anything missing or not covering the requested
period. Every write is atomic (temporary file + rename).

## Hosting

The site needs the API running (it is a Python server, not only static files). The root `Dockerfile`
builds one container with the API and the site. It listens on `$PORT` (default 8001) and downloads the
kernels (~45 MB) on first start; without network it keeps working in fallback mode (2027 only).

- **Hugging Face Spaces (Docker)**: the YAML header at the top of this README is the Space configuration
  (`sdk: docker`, `app_port: 8001`).
- Any Docker host works the same way (Railway, Fly.io, Koyeb, Cloud Run).
- Static-only hosts (GitHub Pages, Netlify, Vercel static) can serve `web/`, but then the API must run
  somewhere else (set `<meta name="api-base">` in `web/index.html` and `CORS_ORIGENS` in the API).

## Front end (web/): LanderBnB

The LanderBnB design (branch `feature/landerbnb`, by Lucksman1001) wired to the API, in plain
HTML/CSS/JS (no build step). Three.js comes from the jsdelivr CDN.

| Part | Data source |
|---|---|
| Site cards (class, % Sun and % Earth, score and uncertainty range) | `/api/sites` + `/api/sites/{id}/metricas` |
| 1. Location | `/api/sites` |
| 2. Date/Time | becomes the `inicio` (UTC) of every call; 720 h window |
| 3. Sun/Earth | terrain panorama (`/horizonte`) with the Sun and Earth at that instant (`/visibilidade`) |
| 4. Power | `/metricas` + hour-by-hour battery simulation using `/visibilidade` |
| 5. Communication | `/metricas` (% Earth visible, longest blackout, Sun and Earth together) |
| Delay simulator | `/atrasos` (0 to 14 days) with a bar chart and thresholds |
| 3D Moon | light from the real Sun direction; markers at the real coordinates |

- **3D Moon**: the sphere uses the NASA SVS CGI Moon Kit textures (`lroc_color_2k.jpg`, `ldem_3_8bit.jpg`).
  On top sits a **south polar cap** (−80° to −90°) generated from the same LOLA DEM as the horizon
  (`python pipeline/tools/gerar_texturas_lua.py`, needs `pillow`). The orientation was checked on the
  texture (Tycho, Copernicus, Mare Crisium) and by tests. The camera "up" vector is longitude 0°, so it can
  look straight down at the pole.
- **Battery simulation**: with the Sun visible, output = power × efficiency; without the Sun, 0. Constant
  load; charge clamped between 0 and capacity. A simple model, stated on screen.
- **Shareable link**: the URL keeps the scenario, e.g.
  `/web/?local=malapert&data=2027-03-01&hora=12:00&etapa=energia&atraso=5`.
- **Without the API**: the page shows a notice with the command to start the API and lists the sites
  from `data/sites.json`.
- **Tests** of the pure functions (geometry, UTC, battery): `node --test web/tests/geo.test.mjs`.

## API (api/main.py)

FastAPI on top of the pipeline. Interactive docs at http://localhost:8001/docs. Every route is GET and
returns JSON. (Route and field names are in Portuguese; they are the contract with the front end.)

| Route | Returns |
|---|---|
| `/api/saude` | health: whether the ephemeris loaded, supported range and defaults |
| `/api/sites`, `/api/sites/{id}` | sites (`data/sites.json`) |
| `/api/sites/{id}/horizonte` | terrain horizon (`data/horizon/<id>.json`) |
| `/api/sites/{id}/ceu?inicio=&dias=30&passo_min=60` | Sun and Earth over the period (sky contract) |
| `/api/sites/{id}/metricas?inicio=&janela_h=720&ok=0.5&crit=0.2` | output of `calcular_metricas` + `fonte` |
| `/api/sites/{id}/atrasos?inicio=&janela_h=720&atraso_max_dias=14` | `{..., serie:[{atraso_dias, score, class}]}` |
| `/api/sites/{id}/visibilidade?inicio=&dias=30` | per sample: `az`, `el`, `rad_deg`, `horizonte` at that azimuth and `visivel` (Sun and Earth) |

Example: `GET /api/sites/malapert/metricas?inicio=2027-03-01T00:00:00Z`

- `inicio` is the landing time in ISO 8601; without a time zone, UTC is assumed.
- **Thresholds**: fractions from 0 to 1. If either is greater than 1, both are treated as percentages
  (`ok=50&crit=20` → 0.5 and 0.2).
- **Errors** in English: 404 for an unknown site; 422 for an invalid parameter, a period out of range or
  `crit ≥ ok`.
- **Fallback**: if the kernels cannot load at startup (no network, for example), the API uses
  `data/sky/<id>.json` (2027, 60 min step) and says so in `fonte.ceu`. Results are identical to the live
  computation (there is a test for it).
- `fonte.horizonte` tells whether the horizon is real (LOLA) or mock.
- **Environment variables**: `PORT` (Docker, default 8001), `DADOS_DIR` (default `data/`), `CORS_ORIGENS`
  (default: `localhost:8000` and `localhost:8080`) and `BAIXAR_KERNELS=0` to skip downloads at startup.
- **Performance**: ~20 ms per metrics or delay call (30-day window computed live).

## Data sources

| Source | What | How we get it |
|---|---|---|
| **NAIF** (JPL) | kernels `de440s.bsp`, `moon_pa_de440_200625.bpc`, `moon_de440_250416.tf` | file **download** (HTTP), once, into `cache/` |
| **LOLA** (NASA GSFC), archived at the **PDS Geosciences Node** | south polar DEMs `LDEM_80S_80M` (80 m/pixel) and `LDEM_75S_240M` (240 m/pixel), ~145 MB | file **download** (HTTP), once, into `cache/lola/` |
| **NASA SVS** CGI Moon Kit | color and relief textures for the 3D Moon | file download, stored in `web/assets/` |
| **Horizons** (JPL) | Sun and Earth positions seen from a point on the Moon | **REST API**, used **only to validate** `ephemeris.py`, cached in `cache/horizons/` |

No `pipeline/` module uses the network at run time, except the initial download of kernels and DEMs and
the validation script.

## Horizon (pipeline/horizon.py)

- For each site, 360 rays (one per degree of azimuth, 0 = North, clockwise) along great circles on the
  sphere, from 40 m to 300 km. Step: 40 m up to 20 km, 80 m up to 100 km, 240 m up to 300 km.
- Height of each point from the finest DEM covering it (80 m inside −80°, 240 m down to −75°), bilinear
  interpolation.
- **Exact** elevation on the sphere, curvature included: `atan2(r2·cos θ − r1, r2·sin θ)`, with
  `θ = d/R`, `r1 = R + h_site + observer height` and `r2 = R + h_point`.
- `horizon_deg[i]` is the maximum elevation along ray `i`. `meta` records the DEMs, the site height, the
  observer height (default **2 m**, *TODO: confirm*) and how far the rays had data.
- The polar stereographic projection is read from the `.lbl` label. The axis signs were **checked against
  the terrain**: only the orientation used puts the centers of Shackleton, Haworth, Nobile, Cabeus,
  de Gerlache and Faustini inside depressions. No GDAL/rasterio needed.
- Apollo 11 (equator) is outside the polar maps: the CLI skips it and keeps the mock horizon.

## Conventions

- **Azimuth**: degrees from **North**, **clockwise** (East = 90°), in [0, 360).
- **Elevation**: degrees above the local plane (perpendicular to the radial vertical). No refraction.
- **East-positive longitude** (−180 to 180); negative latitude in the south.
- **Spherical Moon**, R = **1,737,400 m**.
- **MOON_ME** frame (`MOON_ME_DE440_ME421`, the frame of the LOLA DEMs, aligned with the DE421 ME frame to
  ~1 m).
- Dates in ISO 8601 **UTC** (`2027-01-01T00:00:00Z`); sky sample `i` is `start + i × step_min`.
- **Fractions are always between 0 and 1** (`pct`, `score`, thresholds). The front end formats them as %.

## Data contract

| File | Content |
|---|---|
| `data/sites.json` | list of `{id, name, lat, lon, category, mission, mock}` |
| `data/horizon/<id>.json` | `{site, az_step_deg, horizon_deg[360], meta?, mock}` |
| `data/sky/<id>.json` | `{site, frame, start, step_min, sun:{az[],el[],rad_deg[]}, earth:{az[],el[],rad_deg[]}, mock}` |
| `data/_meta.json`, `data/sky/_meta.json` | `{gerado_em, ...}` |

`horizon_deg[i]` is the maximum terrain elevation at azimuth `i × az_step_deg`. `rad_deg` is the apparent
angular radius of the body. `--check` requires `mock` in every file, 360 horizon values, sky arrays of equal
length, `az` in [0, 360) and no NaN.

## Metrics (pipeline/metrics.py)

```python
from pipeline.metrics import calcular_metricas, serie_por_atraso, indice_de, visibilidade

i0 = indice_de(ceu, datetime(2027, 3, 1, tzinfo=timezone.utc))
m = calcular_metricas(ceu, horizonte, i0, janela_h=720, ok=0.5, crit=0.2)
s = serie_por_atraso(ceu, horizonte, i0, 720, range(15), ok=0.5, crit=0.2)
```

Output of `calcular_metricas`:

```
{ site, window:{start, hours}, mock,
  energy:{ pct, longest_with_h, longest_without_h, daily:[{date, pct}] },
  comms: { pct, longest_with_h, longest_without_h, daily:[{date, pct}] },
  both:{ pct, longest_h },
  score, class:"ideal"|"moderado"|"critico", thresholds:{ok, crit},
  incerteza:{ margem_graus, score_min, score_max } }
```

`serie_por_atraso` returns `[{atraso_dias, score, class}]`. It computes visibility once and only shifts the
window. `export.validar_metricas(m)` validates this output (empty list = ok).

### Visibility rule

A body is visible at sample *i* if **any part of its disk** is above the terrain:

```
el[i] + rad_deg[i] > horizon(az[i]) + margem_graus
```

The horizon is linearly interpolated between neighboring azimuths, wrapping at 360°. The rule lives in a
single function (`regra_visivel`), so the team can switch to a "fraction of the disk" rule.

### Score, classes and defaults

- `score = min(energy.pct, comms.pct)`: a site is only as good as the weaker of the two resources.
- **ideal** if `score ≥ ok`; **critical** if `score < crit`; otherwise **moderate**. `crit < ok` is required.
- Defaults: `ok = 0.5`, `crit = 0.2`, `margem_graus = 0`, uncertainty **±1.0°**, window **720 h** (30 days,
  a bit more than one lunar solar day; *TODO: confirm with the team*). Delay simulator: 0 to 14 days.
- **Uncertainty**: the score is recomputed with the horizon at −1° and +1°; `score_min`/`score_max` give
  the range shown by the front end.
- `daily`: one block per 24 h from the window start; the last one may be partial.
- `mock` = `true` if the sky or the horizon is mock.

### Performance (1-year sky, 1 h step, 8,760 samples)

| Operation | Time |
|---|---|
| `visibilidade` | ~7 ms |
| `calcular_metricas` (720 h, with uncertainty) | ~9 ms |
| `serie_por_atraso` (15 delays) | ~9 ms |
| `horizon.calcular_horizonte` (360 rays × ~2,300 points) | ~0.3 s per site |
| `export --check` (28 files) | ~0.8 s |
| `pytest pipeline/tests api/tests` (150 tests) | ~7 s |

## Validation

- **Ephemerides vs. the Horizons API** (Shackleton, Malapert and Apollo 11; 6 instants each): worst
  difference **0.00005°** in Sun and Earth azimuth and elevation (tolerance 0.05°).
- **Horizon**:
  - The two DEMs agree (median difference 1.6 m over 2,000 points).
  - Synthetic tests: flat terrain gives the theoretical horizon dip (−√(2h/R)); a mountain placed to the
    east shows up at 90°, to the north at 0°.
  - The floor of Haworth (−87.45°, −4.14°) has a horizon ≥ 2.9° in every direction. Since the Sun never
    rises above ~1.6°, it gets 0% sunlight, consistent with the known permanent shadow of the crater floor.
  - The summit of the Malapert Massif has a horizon below 0° in every direction.
  - The best point on the Shackleton rim gets sunlight 80% of the year, within the 80–90% range reported
    for the rim peaks.
- **Tests**: 150 in Python (36 ephemeris, 23 horizon, 55 metrics, 8 export/contract, 28 API) and 9 in the
  front end (Node). They include synthetic cases with known results (12 h of Sun per day → 0.5), the disk
  boundary, classes, uncertainty, delay series, the API fallback and integration with the real `data/sky`.
- `export --check` reports no errors in `data/` and `data_mock/`.

## Limitations

- **DEM uncertainty**: the horizon error can reach **1.5–2.5°**, while the Sun at the pole never rises above
  **~1.5°**. Results are therefore sensitive to the terrain, and the front end shows the
  `score_min`–`score_max` range, not only the score.
- Spherical Moon, no refraction; the disk radius uses the instantaneous distance.
- Communication = **direct line of sight** only. **Out of scope:** Earth–Moon trajectory, ground-station
  availability (DSN, etc.) and **relay** satellites. Thermal simulation and realistic 3D are also out.
- **Results depend strongly on the exact coordinate.** On the narrow Malapert summit, moving the point by
  ~170 m changes sunlight from 66% to 77%. On the massif slope, 370 m below the summit, it is only 43%.
  The numbers hold for the exact point, not for the whole region.
- **There are no public official coordinates** for the Artemis III landing points. The sites in
  `sites.yaml` are published points (Nobile Rim 2, the IM-2 landing site) or derived from the DEM with a
  stated criterion (Malapert summit and best-lit point on the Shackleton and Haworth rims); each one has its
  origin noted in the YAML.
- 80–240 m resolution: features smaller than that (boulders, small craters) are not in the horizon.
- The 3D Moon shades the polar terrain by slope but does not cast shadows; the real shadowing is in the
  numbers and in the step 3 panorama.
- Apollo 11 still has a mock horizon.

## Open items

- **Coordinates**: replace the derived points with official ones when NASA publishes them; check the
  Nobile Rim 2 point against the full text of the paper. After changing a point, rerun
  `python -m pipeline.ephemeris ... --site <id>`, `python -m pipeline.horizon --site <id>` and
  `python -m pipeline.export --out data`. To redo the derived points: `python pipeline/tools/escolher_pontos.py`
  (~4 min).
- **Observer height** of 2 m to be confirmed (antenna, panel).
- Cross-check the horizon with a published reference (LOLA/PGDA illumination maps).
- **Default window** of 720 h to be confirmed.
- Disk rule ("any part") vs. "fraction of the disk": team decision.
- API fallback only covers 2027 with a 60 min step. Other years require regenerating `data/sky`.

## Credits

Sky: Skyfield + JPL DE440 (NAIF). Terrain: LRO LOLA (NASA GSFC, PDS Geosciences Node). Moon texture:
NASA's Scientific Visualization Studio (CGI Moon Kit). Front-end design: LanderBnB.
