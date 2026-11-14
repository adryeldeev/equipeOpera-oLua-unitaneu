# Pouso no Polo Sul Lunar

Ferramenta web que, para um local e uma data/hora na Lua, mostra onde estão o Sol e a Terra
em relação ao horizonte do terreno e avalia energia (Sol visível) e comunicação direta (Terra visível).
Feita para planejadores de missão, educadores e público geral.

> **Estado atual:** esqueleto. Os dados em `data/` são **falsos** (`"mock": true`) e servem só para desenvolver o frontend.

## Estrutura

```
.
├── pipeline/               # Python: calcula e exporta (não conhece o frontend)
│   ├── config/sites.yaml   # locais analisados (coordenadas aproximadas)
│   ├── tools/gerar_mock.py # gera dados falsos em data/
│   ├── ephemeris.py        # Sol/Terra vistos do local (Skyfield/SPICE, DE440)
│   ├── horizon.py          # horizonte do terreno (DEM do LOLA, rasterio)
│   ├── metrics.py          # visibilidade, métricas e veredito
│   ├── export.py           # escreve os JSONs de data/
│   ├── requirements.txt
│   └── Dockerfile
├── web/                    # HTML/CSS/JS puro, estático (não conhece o pipeline)
│   ├── index.html
│   └── js/data.js          # loadSites, loadHorizon, loadSky (com cache)
├── data/                   # contrato entre pipeline e web (versionado no git)
│   ├── sites.json
│   ├── horizon/<id>.json
│   └── sky/<id>.json
├── cache/                  # kernels JPL, DEM etc. (ignorado pelo git)
└── docker-compose.yml
```

**Regra:** o pipeline escreve em `data/`; o frontend só lê.
O Horizons API (JPL) é usado apenas para validar resultados, nunca em tempo real.

## Requisitos

- Python 3.11 ou 3.12
- Um navegador moderno
- Docker Desktop (opcional)

O `rasterio` depende da biblioteca nativa **GDAL**. Em geral o `pip` instala uma wheel que já inclui o GDAL,
mas se `pip install` falhar no Windows (erro compilando rasterio/GDAL), use o caminho com **Docker** abaixo.
Para gerar o mock basta `pyyaml` (`pip install pyyaml`).

## Como rodar sem Docker (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r pipeline/requirements.txt
python pipeline/tools/gerar_mock.py
python -m http.server 8000
```

Rode o `http.server` **na raiz do repositório** e abra http://localhost:8000/web/

Se o `Activate.ps1` for bloqueado, libere scripts só para a sessão atual:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

> **Atenção:** abrir o `web/index.html` com duplo clique **não funciona**: o navegador bloqueia a
> leitura dos JSONs em `file://`. É preciso um servidor local (`http.server` ou Docker).

## Como rodar com Docker

```powershell
docker compose up web
```

Abra http://localhost:8080/web/ (nginx servindo `web/` e `data/` somente leitura).

Para rodar o pipeline (hoje: gerar o mock) dentro do container:

```powershell
docker compose run --rm pipeline
```

O serviço `pipeline` tem o profile `tools`, então não sobe com `docker compose up`, só sob demanda.

## Contrato de dados

| Arquivo | Conteúdo |
|---|---|
| `data/sites.json` | lista de `{id, name, lat, lon, category, mission}` |
| `data/horizon/<id>.json` | `{site, az_step_deg, horizon_deg[360]}` |
| `data/sky/<id>.json` | `{site, start, step_min, sun:{az[],el[]}, earth:{az[],el[]}}` |

- `lat`: graus, negativa no sul. `lon`: graus, **leste positiva**.
- Azimute em graus a partir do Norte, sentido horário (Leste = 90°). Elevação em graus acima do plano tangente.
- `start`: ISO 8601 em UTC (ex.: `2027-01-01T00:00:00Z`); a amostra `i` é `start + i * step_min`.
- **Visível** = elevação do corpo > `horizon_deg[round(az) % 360]`.
- Dados falsos levam `"mock": true` (em `sites.json`, em cada item).

## Escopo do MVP

3 a 5 locais, 1 ano de dados, passo de 1 hora.
Fora do escopo: trajetória Terra-Lua, simulação térmica, 3D realista.
