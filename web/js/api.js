// Cliente de dados do front. O front só LÊ: nada aqui escreve dados.
//
// Dois modos, com as MESMAS respostas (as telas não sabem qual está em uso):
//   API       chama api/main.py (céu calculado na hora, qualquer data 1849–2150);
//   ESTÁTICO  sem servidor: lê data/ (céu pré-calculado) e faz as contas no
//             navegador com calculo.js, cópia fiel do pipeline/metrics.py.
//
// Escolha do modo (<meta name="api-base"> no index.html):
//   "static"  -> sempre estático (usado na hospedagem gratuita);
//   "<url>"   -> só essa API;
//   vazio     -> tenta a mesma origem e http://localhost:8001; se nenhuma
//                responder, cai no modo estático.

import * as calc from "./calculo.js";

const CANDIDATOS_PADRAO = ["", "http://localhost:8001"];
const ATRASO_MAX_DIAS = 14;
let base = null;          // URL da API, ou null no modo estático
let dados = null;         // URL da pasta data/ (modo estático)

async function json(url) {
    const r = await fetch(url);
    if (!r.ok) {
        let detalhe = `HTTP ${r.status}`;
        try { detalhe = (await r.json()).detail || detalhe; } catch { /* sem corpo JSON */ }
        throw new Error(detalhe);
    }
    return r.json();
}

// ---------------------------------------------------------------- modo estático

const cache = new Map();
function lerDados(rel) {
    if (!cache.has(rel)) {
        const p = json(new URL(rel, dados).href);
        p.catch(() => cache.delete(rel));
        cache.set(rel, p);
    }
    return cache.get(rel);
}

async function acharDados() {
    for (const rel of ["data/", "../data/", "/data/"]) {
        const url = new URL(rel, document.baseURI).href;
        try {
            await json(`${url}sites.json`);
            return url;
        } catch { /* tenta a próxima */ }
    }
    throw new Error("data/ not found (sites.json)");
}

async function saudeEstatica() {
    const meta = await lerDados("sky/_meta.json");
    // Última data de pouso útil: a janela padrão + o maior atraso cabem no céu gravado.
    const fimMs = Date.parse(meta.fim) - (calc.JANELA_H_PADRAO + ATRASO_MAX_DIAS * 24) * 3600e3;
    return {
        status: "ok", modo: "estatico", efemerides: false, erro_efemerides: null,
        intervalo_suportado: { inicio: meta.inicio, fim: new Date(fimMs).toISOString().replace(".000Z", "Z") },
        padroes: { janela_h: calc.JANELA_H_PADRAO, ok: calc.OK_PADRAO, crit: calc.CRIT_PADRAO,
                   incerteza_graus: calc.INCERTEZA_PADRAO_GRAUS },
    };
}

function fonte(hz) {
    return { ceu: "data/sky (static mode, computed in the browser)",
             horizonte: hz.mock ? "mock" : (hz.meta?.fonte || "real") };
}

async function par(id) {
    return Promise.all([lerDados(`sky/${encodeURIComponent(id)}.json`), lerDados(`horizon/${encodeURIComponent(id)}.json`)]);
}

function limiares(ok = calc.OK_PADRAO, crit = calc.CRIT_PADRAO) {
    ok = Number(ok); crit = Number(crit);
    return ok > 1 || crit > 1 ? [ok / 100, crit / 100] : [ok, crit];
}

const estatico = {
    sites: () => lerDados("sites.json"),
    horizonte: (id) => lerDados(`horizon/${encodeURIComponent(id)}.json`),
    async metricas(id, p) {
        const [ceu, hz] = await par(id);
        const [ok, crit] = limiares(p.ok, p.crit);
        const m = calc.calcularMetricas(ceu, hz, calc.indiceDe(ceu, p.inicio), Number(p.janela_h ?? calc.JANELA_H_PADRAO), ok, crit);
        return { ...m, fonte: fonte(hz) };
    },
    async atrasos(id, p) {
        const [ceu, hz] = await par(id);
        const [ok, crit] = limiares(p.ok, p.crit);
        const janela = Number(p.janela_h ?? calc.JANELA_H_PADRAO);
        const n = Number(p.atraso_max_dias ?? ATRASO_MAX_DIAS);
        const serie = calc.seriePorAtraso(ceu, hz, calc.indiceDe(ceu, p.inicio), janela, [...Array(n + 1).keys()], ok, crit);
        return { site: id, inicio: p.inicio, janela_h: janela, thresholds: { ok, crit },
                 mock: Boolean(ceu.mock) || Boolean(hz.mock), fonte: fonte(hz), serie };
    },
    async visibilidade(id, p) {
        const [ceu, hz] = await par(id);
        const i0 = calc.indiceDe(ceu, p.inicio);
        const n = Math.ceil((Number(p.dias ?? 30) * 1440) / ceu.step_min);
        if (i0 + n > ceu.sun.el.length) throw new Error("period out of the precomputed sky");
        const g = calc.geometria(ceu, hz);
        const v = calc.visivel(g);
        const corta = (a) => a.slice(i0, i0 + n);
        const corpo = (c, gc, vis) => ({ az: corta(c.az), el: corta(c.el), rad_deg: corta(c.rad_deg),
                                         horizonte: corta(gc.hz).map((x) => Math.round(x * 1000) / 1000), visivel: corta(vis) });
        return { site: id, start: p.inicio, step_min: ceu.step_min, mock: Boolean(ceu.mock) || Boolean(hz.mock),
                 fonte: fonte(hz), sol: corpo(ceu.sun, g.sun, v.sol), terra: corpo(ceu.earth, g.earth, v.terra) };
    },
};

// ---------------------------------------------------------------- modo API

function q(params) {
    return new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null));
}

const remoto = {
    sites: () => json(`${base}/api/sites`),
    horizonte: (id) => json(`${base}/api/sites/${encodeURIComponent(id)}/horizonte`),
    metricas: (id, p) => json(`${base}/api/sites/${encodeURIComponent(id)}/metricas?${q(p)}`),
    atrasos: (id, p) => json(`${base}/api/sites/${encodeURIComponent(id)}/atrasos?${q(p)}`),
    visibilidade: (id, p) => json(`${base}/api/sites/${encodeURIComponent(id)}/visibilidade?${q(p)}`),
};

let impl = null;
export const api = {
    sites: (...a) => impl.sites(...a),
    horizonte: (...a) => impl.horizonte(...a),
    metricas: (...a) => impl.metricas(...a),
    atrasos: (...a) => impl.atrasos(...a),
    visibilidade: (...a) => impl.visibilidade(...a),
};

/** Escolhe o modo; devolve {base, saude}. saude.modo === "estatico" no modo sem servidor. */
export async function conectar() {
    const meta = document.querySelector('meta[name="api-base"]')?.content?.trim();
    if (meta !== "static") {
        for (const c of meta ? [meta] : CANDIDATOS_PADRAO) {
            try {
                const saude = await json(`${c}/api/saude`);
                base = c;
                impl = remoto;
                return { base: c || location.origin, saude };
            } catch { /* tenta a próxima */ }
        }
    }
    dados = await acharDados();
    impl = estatico;
    return { base: dados, saude: await saudeEstatica() };
}

/** Sem API nem data/: ao menos tenta a lista de locais. */
export async function sitesSemApi() {
    for (const url of ["/data/sites.json", new URL("../data/sites.json", document.baseURI).href]) {
        try { return await json(url); } catch { /* tenta a próxima */ }
    }
    return [];
}
