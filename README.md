# Pouso no Polo Sul Lunar

Ferramenta web que, para um local e uma data/hora na Lua, mostra onde estão o Sol e a Terra
em relação ao horizonte do terreno e avalia energia (Sol visível) e comunicação direta (Terra visível).
Feita para planejadores de missão, educadores e público geral.

> **Estado atual:** efemérides **reais** (Sol e Terra) em `data/sky/`. Horizonte e lista de locais
> em `data/` ainda são mock (`"mock": true`) até a Tarefa 3. Dados 100% falsos ficam em `data_mock/`.

## Estrutura

```
.
├── pipeline/                   # Python: calcula e exporta (não conhece o frontend)
│   ├── config/sites.yaml       # locais analisados (coordenadas aproximadas)
│   ├── ephemeris.py            # Sol/Terra vistos do local: biblioteca + CLI (Skyfield, DE440)
│   ├── horizon.py              # horizonte do terreno (DEM do LOLA), Tarefa 3
│   ├── metrics.py              # visibilidade, métricas e veredito
│   ├── export.py               # escrita dos JSONs de data/
│   ├── tests/                  # pytest (sem rede)
│   ├── tools/gerar_mock.py     # gera dados falsos em data_mock/
│   ├── tools/validar_horizons.py  # confere ephemeris contra a API Horizons (JPL)
│   ├── requirements.txt / requirements-dev.txt
│   └── Dockerfile
├── web/                        # HTML/CSS/JS puro, estático (não conhece o pipeline)
├── data/                       # contrato pipeline → front (versionado no git)
│   ├── sites.json
│   ├── horizon/<id>.json
│   └── sky/<id>.json, sky/_meta.json
├── data_mock/                  # mesmo contrato, dados falsos, para testes do front
├── cache/                      # kernels JPL, respostas do Horizons (ignorado pelo git)
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

## Como rodar sem Docker (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r pipeline/requirements-dev.txt
python -m http.server 8000
```

Rode o `http.server` **na raiz do repositório** e abra http://localhost:8000/web/

Se o `Activate.ps1` for bloqueado, libere scripts só para a sessão atual:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

> **Atenção:** abrir o `web/index.html` com duplo clique **não funciona**: o navegador bloqueia a
> leitura dos JSONs em `file://`. É preciso um servidor local (`http.server` ou Docker).

## Efemérides (pipeline/ephemeris.py)

Calcula azimute, elevação e raio angular aparente do Sol e da Terra vistos de um local lunar.

- Skyfield + **DE440** (`de440s.bsp`) + orientação lunar `moon_pa_de440_200625.bpc` e
  `moon_de440_250416.tf`. Na primeira execução são baixados para `cache/` (~45 MB, nunca vão para o git).
- Referencial **MOON_ME** (`MOON_ME_DE440_ME421`, alinhado ao ME do DE421 a ~1 m, o mesmo dos DEMs do LOLA).
- Lua esférica (R = 1737,4 km), sem refração, com tempo de luz e aberração.
- **Intervalo suportado: 1849-12-27 a 2150-01-20 (UTC).**

### Como biblioteca (uso da API)

```python
from datetime import datetime, timezone
from pipeline.ephemeris import carregar_recursos, gerar_ceu, intervalo_suportado

carregar_recursos()   # no startup: carrega kernels uma vez (thread-safe)
ceu = gerar_ceu(site, datetime(2027, 1, 1, tzinfo=timezone.utc), dias=30, passo_min=60)
```

Erros: `ParametroInvalido` (dias ≤ 0, passo fora de 1–1440, mais de 100.000 instantes, data sem fuso)
e `ForaDoIntervalo` (traz `inicio_suportado` e `fim_suportado`). 30 dias em passo de 60 min levam ~15 ms.

### Como CLI (cache e plano B)

```powershell
python -m pipeline.ephemeris --start 2027-01-01 --days 365 --step-min 60 --out data/sky
python -m pipeline.ephemeris --start 2027-01-01 --days 365 --step-min 60 --out data/sky --site malapert
docker compose run --rm pipeline python -m pipeline.ephemeris --start 2027-01-01 --days 365 --step-min 60 --out data/sky
```

`--sites` tem como padrão `pipeline/config/sites.yaml`. Grava cada arquivo de forma atômica e
também `data/sky/_meta.json` (versão do Skyfield, kernels, início, fim, passo, nº de instantes, data de geração).

### Testes e validação

```powershell
python -m pytest pipeline/tests -v          # sem rede; pulados se faltarem os kernels
python pipeline/tools/validar_horizons.py   # consulta a API Horizons (sequencial, com cache)
```

Última validação (Shackleton, Malapert e Apollo 11; 6 instantes cada): pior diferença de
**0,00005°** em azimute e elevação do Sol e da Terra (tolerância inicial 0,05°).

## Dados mock

```powershell
python pipeline/tools/gerar_mock.py          # grava em data_mock/
docker compose run --rm pipeline             # o mesmo, dentro do Docker
```

## Como rodar com Docker

```powershell
docker compose up web
```

Abra http://localhost:8080/web/ (nginx servindo `web/` e `data/` somente leitura).
O serviço `pipeline` tem o profile `tools`: só roda sob demanda (`docker compose run --rm pipeline ...`).

## Contrato de dados

| Arquivo | Conteúdo |
|---|---|
| `data/sites.json` | lista de `{id, name, lat, lon, category, mission}` |
| `data/horizon/<id>.json` | `{site, az_step_deg, horizon_deg[360]}` |
| `data/sky/<id>.json` | `{site, frame, start, step_min, sun:{az[],el[],rad_deg[]}, earth:{az[],el[],rad_deg[]}, mock}` |

- `lat`: graus, negativa no sul. `lon`: graus, **leste positiva**.
- Azimute em graus a partir do Norte, sentido horário (Leste = 90°), em [0, 360). Elevação em graus acima do plano local.
- `rad_deg`: raio angular aparente do corpo (graus), um por instante.
- `start`: ISO 8601 em UTC (ex.: `2027-01-01T00:00:00Z`); a amostra `i` é `start + i * step_min`.
- **Visível** = elevação do corpo > `horizon_deg[round(az) % 360]`.
- Dados falsos levam `"mock": true` (em `sites.json`, em cada item).

## Escopo do MVP

3 a 5 locais, 1 ano de dados, passo de 1 hora.
Fora do escopo: trajetória Terra-Lua, simulação térmica, 3D realista.
