// Camada de dados do frontend: só LÊ os JSONs de data/ (nunca escreve).
// Cada recurso é buscado uma única vez; chamadas repetidas reutilizam
// a mesma Promise (cache em memória por sessão da página).

// web/ e data/ ficam lado a lado na raiz servida (http.server ou nginx).
const DATA_BASE = new URL("../data/", document.baseURI);

const cache = new Map();

function fetchJson(relPath) {
  if (!cache.has(relPath)) {
    const p = fetch(new URL(relPath, DATA_BASE)).then((res) => {
      if (!res.ok) throw new Error(`Falha ao ler ${relPath}: HTTP ${res.status}`);
      return res.json();
    });
    // Se falhar, remove do cache para permitir nova tentativa.
    p.catch(() => cache.delete(relPath));
    cache.set(relPath, p);
  }
  return cache.get(relPath);
}

/** Lista de locais: [{id, name, lat, lon, category, mission}] */
export function loadSites() {
  return fetchJson("sites.json");
}

/** Horizonte: {site, az_step_deg, horizon_deg[360]} */
export function loadHorizon(id) {
  return fetchJson(`horizon/${encodeURIComponent(id)}.json`);
}

/** Céu: {site, start, step_min, sun:{az[],el[]}, earth:{az[],el[]}} */
export function loadSky(id) {
  return fetchJson(`sky/${encodeURIComponent(id)}.json`);
}
