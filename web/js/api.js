// Cliente da API (api/main.py). O front só LÊ: nada aqui escreve dados.
//
// Onde está a API:
//   1. <meta name="api-base" content="..."> no index.html, se preenchido;
//   2. a mesma origem da página (quando o front é servido pela própria API,
//      em http://localhost:8001/web/);
//   3. http://localhost:8001 (front servido à parte, ex.: http.server na 8000).

const CANDIDATOS_PADRAO = ["", "http://localhost:8001"];
let base = null;

async function json(url) {
    const r = await fetch(url);
    if (!r.ok) {
        let detalhe = `HTTP ${r.status}`;
        try { detalhe = (await r.json()).detail || detalhe; } catch { /* sem corpo JSON */ }
        throw new Error(detalhe);
    }
    return r.json();
}

/** Descobre a base da API; devolve {base, saude} ou lança erro. */
export async function conectar() {
    const meta = document.querySelector('meta[name="api-base"]')?.content?.trim();
    const candidatos = meta ? [meta] : CANDIDATOS_PADRAO;
    for (const c of candidatos) {
        try {
            const saude = await json(`${c}/api/saude`);
            base = c;
            return { base: c || location.origin, saude };
        } catch { /* tenta a próxima */ }
    }
    throw new Error(`API indisponível (tentado: ${candidatos.map((c) => c || location.origin).join(", ")})`);
}

function q(params) {
    return new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null));
}

function exigirBase() {
    if (base === null) throw new Error("API não conectada");
    return base;
}

export const api = {
    sites: () => json(`${exigirBase()}/api/sites`),
    horizonte: (id) => json(`${exigirBase()}/api/sites/${encodeURIComponent(id)}/horizonte`),
    metricas: (id, params) => json(`${exigirBase()}/api/sites/${encodeURIComponent(id)}/metricas?${q(params)}`),
    atrasos: (id, params) => json(`${exigirBase()}/api/sites/${encodeURIComponent(id)}/atrasos?${q(params)}`),
    visibilidade: (id, params) =>
        json(`${exigirBase()}/api/sites/${encodeURIComponent(id)}/visibilidade?${q(params)}`),
};

/** Plano B do front: sem API, ao menos a lista de locais (data/sites.json). */
export async function sitesSemApi() {
    for (const url of ["/data/sites.json", new URL("../data/sites.json", document.baseURI).href]) {
        try { return await json(url); } catch { /* tenta a próxima */ }
    }
    return [];
}
