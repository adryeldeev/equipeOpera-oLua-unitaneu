# Pouso no Polo Sul Lunar

Ferramenta web de planejamento: para um local do polo sul lunar e uma data de pouso, mostra se haverá
**Sol** (energia) e **Terra** (comunicação direta) acima do relevo, e como o resultado muda se o pouso atrasar.
Feita para planejadores de missão, educadores e público geral.

> **Estado atual:** efemérides **reais** (Sol e Terra) em `data/sky/`. O horizonte em `data/horizon/` ainda é
> **mock** (`"mock": true`) até o `horizon.py` ficar pronto, então toda métrica sai com `"mock": true`.
> Dados 100% falsos ficam em `data_mock/`.

## Arquitetura

```
  NAIF (kernels DE440, download)          PGDA (DEM polar do LOLA, download)
            │ Skyfield                              │ rasterio
            ▼                                       ▼
  pipeline/ephemeris.py                    pipeline/horizon.py
  céu: Sol e Terra (az, el, rad_deg)       horizonte: horizon_deg[360]
            └─────────────────┬─────────────────────┘
                              ▼
                     pipeline/metrics.py
          visibilidade, % do tempo, maiores períodos,
          score, classe, incerteza, série por atraso
                              │
            ┌─────────────────┴──────────────────┐
            ▼                                    ▼
   api/ (FastAPI, outra tarefa)         pipeline/export.py
   chama ephemeris + metrics            data/*.json (plano B) e --check
            │                                    │
            └────────────►  front  ◄─────────────┘
                 hoje: web/ (HTML/JS puro); depois: React
```

- **pipeline/**: cálculo em Python. Não conhece o front.
- **data/**: contrato pipeline → front (versionado). Também serve de plano B se a API cair.
- **web/**: só lê. Nunca escreve.
- A API Horizons (JPL) serve **só para validar**, nunca em tempo real.

```
.
├── pipeline/
│   ├── config/sites.yaml       # locais analisados (coordenadas aproximadas)
│   ├── ephemeris.py            # Sol/Terra vistos do local: biblioteca + CLI (Skyfield, DE440)
│   ├── horizon.py              # horizonte do terreno (DEM do LOLA), em andamento
│   ├── metrics.py              # visibilidade, métricas, score, incerteza, atraso
│   ├── export.py               # data/sites.json, _meta.json e --check do contrato
│   ├── tests/                  # pytest (sem rede)
│   ├── tools/gerar_mock.py     # dados falsos em data_mock/
│   └── tools/validar_horizons.py  # confere ephemeris contra a API Horizons
├── web/                        # front estático
├── data/                       # sites.json, _meta.json, horizon/<id>.json, sky/<id>.json, sky/_meta.json
├── data_mock/                  # mesmo contrato, dados falsos
├── cache/                      # kernels, DEMs, respostas do Horizons (fora do git)
└── docker-compose.yml
```

## Como rodar

### Local (PowerShell)

Requisitos: Python 3.11+ e um navegador moderno.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r pipeline/requirements-dev.txt

python -m http.server 8000      # na RAIZ do repositório
```

Abra http://localhost:8000/web/. Abrir o `web/index.html` com duplo clique **não funciona**, porque o
navegador bloqueia a leitura dos JSONs em `file://`.

Se o `Activate.ps1` for bloqueado: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.
O `rasterio` depende do GDAL; se o `pip install` falhar no Windows, use o Docker.

### Docker

```powershell
docker compose up web                                              # http://localhost:8080/web/
docker compose run --rm pipeline python -m pipeline.export --check
docker compose run --rm pipeline python -m pipeline.ephemeris --start 2027-01-01 --days 365 --step-min 60 --out data/sky
```

O serviço `pipeline` tem o profile `tools`: só roda sob demanda.

### Comandos do pipeline

```powershell
# Céu (efemérides) para 2027, passo de 1 h. Baixa ~45 MB de kernels para cache/ na 1ª vez.
python -m pipeline.ephemeris --start 2027-01-01 --days 365 --step-min 60 --out data/sky

# sites.json a partir do YAML + conferência de data/sky e data/horizon
python -m pipeline.export --sites pipeline/config/sites.yaml --out data
python -m pipeline.export --out data --site malapert --start 2027-03-01 --days 44

# Valida TODOS os JSON de data/ e data_mock/ (código de saída ≠ 0 se houver erro)
python -m pipeline.export --check

# Testes (sem rede) e validação contra o Horizons (com rede)
python -m pytest pipeline/tests -v
python pipeline/tools/validar_horizons.py

# Dados falsos
python pipeline/tools/gerar_mock.py
```

O `export` **não recalcula** céu nem horizonte: gera `data/sites.json` e `data/_meta.json` (data de geração e
quais arquivos são mock) e aponta o que falta ou não cobre o período pedido. Toda escrita é atômica
(arquivo temporário + rename).

## Origem dos dados

| Fonte | O quê | Como obtemos |
|---|---|---|
| **NAIF** (JPL) | kernels `de440s.bsp`, `moon_pa_de440_200625.bpc`, `moon_de440_250416.tf` | **download** de arquivos (HTTP), uma vez, para `cache/` |
| **PGDA** (NASA GSFC) | DEM polar sul do LOLA (relevo) | **download** de arquivos para `cache/`; o produto exato fica a cargo do `horizon.py` |
| **Horizons** (JPL) | posições de Sol e Terra vistas de um ponto da Lua | **API** (REST), usada **só para validar** o `ephemeris.py`, com cache em `cache/horizons/` |

Nenhum módulo de `pipeline/` chama rede em tempo de execução, exceto o download inicial dos kernels e o
script de validação.

## Convenções

- **Azimute**: graus a partir do **Norte**, sentido **horário** (Leste = 90°), em [0, 360).
- **Elevação**: graus acima do plano local (perpendicular à vertical radial). Sem refração.
- **Longitude leste positiva** (−180 a 180); latitude negativa no sul.
- **Lua esférica**, R = **1.737.400 m**.
- Referencial **MOON_ME** (`MOON_ME_DE440_ME421`, o mesmo dos DEMs do LOLA, alinhado ao ME do DE421 a ~1 m).
- Datas em ISO 8601 **UTC** (`2027-01-01T00:00:00Z`); a amostra `i` do céu é `start + i × step_min`.
- **Frações sempre entre 0 e 1** (`pct`, `score`, limiares). O front formata como %.

## Contrato de dados

| Arquivo | Conteúdo |
|---|---|
| `data/sites.json` | lista de `{id, name, lat, lon, category, mission, mock}` |
| `data/horizon/<id>.json` | `{site, az_step_deg, horizon_deg[360], meta?, mock}` |
| `data/sky/<id>.json` | `{site, frame, start, step_min, sun:{az[],el[],rad_deg[]}, earth:{az[],el[],rad_deg[]}, mock}` |
| `data/_meta.json`, `data/sky/_meta.json` | `{gerado_em, ...}` |

`horizon_deg[i]` é a elevação máxima do relevo no azimute `i × az_step_deg`. `rad_deg` é o raio angular
aparente do corpo. O `--check` exige `mock` em todos os arquivos, 360 valores no horizonte, arrays do
mesmo tamanho no céu, `az` em [0, 360) e nenhum NaN.

## Métricas (pipeline/metrics.py)

```python
from pipeline.metrics import calcular_metricas, serie_por_atraso, indice_de, visibilidade

i0 = indice_de(ceu, datetime(2027, 3, 1, tzinfo=timezone.utc))
m = calcular_metricas(ceu, horizonte, i0, janela_h=720, ok=0.5, crit=0.2)
s = serie_por_atraso(ceu, horizonte, i0, 720, range(15), ok=0.5, crit=0.2)
```

Saída de `calcular_metricas`:

```
{ site, window:{start, hours}, mock,
  energy:{ pct, longest_with_h, longest_without_h, daily:[{date, pct}] },
  comms: { pct, longest_with_h, longest_without_h, daily:[{date, pct}] },
  both:{ pct, longest_h },
  score, class:"ideal"|"moderado"|"critico", thresholds:{ok, crit},
  incerteza:{ margem_graus, score_min, score_max } }
```

`serie_por_atraso` devolve `[{atraso_dias, score, class}]`. Ela calcula a visibilidade uma vez e só desloca
a janela. `export.validar_metricas(m)` confere essa saída (lista vazia = ok).

### Regra de visibilidade

Um astro é visível no instante *i* se **qualquer parte do disco** estiver acima do relevo:

```
el[i] + rad_deg[i] > horizonte(az[i]) + margem_graus
```

O horizonte é interpolado linearmente entre os azimutes vizinhos, com wrap em 360°. A regra está numa só
função (`regra_visivel`), para a equipe poder trocar por "fração do disco".

### Score, classes e padrões

- `score = min(energy.pct, comms.pct)`: o local é tão bom quanto o pior dos dois recursos.
- **ideal** se `score ≥ ok`; **crítico** se `score < crit`; senão **moderado**. É obrigatório `crit < ok`.
- Padrões: `ok = 0,5`, `crit = 0,2`, `margem_graus = 0`, incerteza **±1,0°**, janela **720 h** (30 dias, pouco
  mais de um dia solar lunar; *TODO: confirmar com a equipe*). Simulador de atraso: 0 a 14 dias.
- **Incerteza**: o score é recalculado com o horizonte −1° e +1°, e `score_min`/`score_max` dão a faixa que
  o front mostra.
- `daily`: um bloco por 24 h a partir do início da janela; o último pode ser parcial.
- `mock` = `true` se o céu ou o horizonte forem mock.

### Desempenho (céu de 1 ano, passo de 1 h, 8.760 instantes)

| Operação | Tempo |
|---|---|
| `visibilidade` | ~7 ms |
| `calcular_metricas` (720 h, com incerteza) | ~9 ms |
| `serie_por_atraso` (15 atrasos) | ~9 ms |
| `export --check` (23 arquivos) | ~0,8 s |
| `pytest pipeline/tests` (94 testes) | ~4 s |

## Validação feita

- **Efemérides vs. API Horizons** (Shackleton, Malapert e Apollo 11; 6 instantes cada): pior diferença de
  **0,00005°** em azimute e elevação do Sol e da Terra (tolerância 0,05°).
- **pytest**: 35 testes de efemérides, 51 de métricas e 8 de export/contrato. Incluem casos sintéticos com
  resultado conhecido (12 h de Sol por dia → 0,5), fronteira do disco, classes, incerteza, série por atraso
  e integração com `data/sky` real + `data_mock/horizon`.
- `export --check` sem erros em `data/` e `data_mock/`.

## Limitações

- **Incerteza do DEM**: o erro do horizonte pode chegar a **1,5–2,5°**, e o Sol no polo nunca passa de
  **~1,5°** de elevação. Por isso o resultado é sensível ao relevo e o front deve mostrar a faixa
  `score_min`–`score_max`, não só o score.
- Lua esférica, sem refração; o raio do disco usa a distância instantânea.
- Comunicação = só **visada direta** Terra–local. **Fora do escopo:** trajetória Terra–Lua, disponibilidade
  de antenas na Terra (DSN etc.) e satélites de **relé**. Também ficam de fora simulação térmica e 3D realista.
- As coordenadas de `sites.yaml` são aproximadas.

## Pendências

- **Horizonte real** (`horizon.py`): `data/horizon/` ainda é mock. O arquivo real deve trazer `"mock": false`
  (o `--check` exige a chave).
- **API** (`api/`, outra tarefa): importar `calcular_metricas`, `serie_por_atraso`, `indice_de` e
  `validar_metricas`, e converter limiares de 0–100 para fração.
- **Janela padrão** de 720 h a confirmar.
- Regra do disco ("qualquer parte") vs. "fração do disco": decisão da equipe.
- Conferir as coordenadas dos locais em fontes oficiais.
- Front em React e uso das métricas no front: ainda não existem.
