// Cópia em JavaScript de pipeline/metrics.py, para o MODO ESTÁTICO (site sem
// servidor: as contas rodam no navegador com os arquivos de data/).
//
// Deve dar EXATAMENTE os mesmos números do Python. Isso é conferido por
// web/tests/calculo.test.mjs contra web/tests/fixtures/metricas_ref.json,
// gerado pelo próprio pipeline (python pipeline/tools/gerar_referencia_js.py).
// Se mudar uma regra aqui, mude lá também (e vice-versa).

export const OK_PADRAO = 0.5;
export const CRIT_PADRAO = 0.2;
export const JANELA_H_PADRAO = 720;
export const INCERTEZA_PADRAO_GRAUS = 1.0;

/** Regra de visibilidade: alguma parte do disco acima do relevo + margem. */
export function regraVisivel(el, rad, hz, margem = 0) {
    return el + rad > hz + margem;
}

/** Horizonte interpolado linearmente no azimute (com wrap em 360°). */
export function horizonteEm(h, az) {
    const v = h.horizon_deg, passo = h.az_step_deg, n = v.length;
    if (!n || passo <= 0 || Math.abs(n * passo - 360) > 1e-9) {
        throw new Error(`invalid horizon: ${n} values with a ${passo}° step do not cover 360°`);
    }
    // Igual a np.mod(az, 360) / passo (resultado sempre em [0, 360)).
    const x = (((az % 360) + 360) % 360) / passo;
    const base = Math.floor(x);
    const f = x - base;
    const i0 = ((base % n) + n) % n;
    const i1 = (i0 + 1) % n;
    return v[i0] * (1 - f) + v[i1] * f;
}

function iso(ms) {
    return new Date(ms).toISOString().replace(".000Z", "Z");
}

function instante(texto) {
    return Date.parse(texto);
}

function maiorSequencia(b, ini, fim) {
    let melhor = 0, atual = 0;
    for (let i = ini; i < fim; i++) {
        atual = b[i] ? atual + 1 : 0;
        if (atual > melhor) melhor = atual;
    }
    return melhor;
}

function conferirLimiares(ok, crit) {
    for (const [nome, v] of [["ok", ok], ["crit", crit]]) {
        if (typeof v !== "number" || !Number.isFinite(v)) throw new Error(`threshold ${nome} must be a number (got: ${v})`);
        if (v < 0 || v > 1) throw new Error(`threshold ${nome} must be a fraction between 0 and 1 (got: ${v})`);
    }
    if (!(crit < ok)) throw new Error(`the critical threshold (${crit}) must be lower than the ok threshold (${ok})`);
}

export function classificar(score, ok, crit) {
    conferirLimiares(ok, crit);
    if (score >= ok) return "ideal";
    if (score < crit) return "critico";
    return "moderado";
}

function passos(ceu, horas, nome) {
    const n = (horas * 60) / ceu.step_min;
    if (Math.abs(n - Math.round(n)) > 1e-9) {
        throw new Error(`${nome} = ${horas} h is not a multiple of the sky time step (${ceu.step_min} min)`);
    }
    return Math.round(n);
}

function janela(ceu, inicioIdx, janelaH) {
    const n = passos(ceu, janelaH, "janela_h");
    if (n <= 0) throw new Error(`janela_h must be > 0 (got: ${janelaH})`);
    const total = ceu.sun.el.length;
    if (inicioIdx < 0 || inicioIdx + n > total) {
        const ini = instante(ceu.start), passoMs = ceu.step_min * 60000;
        throw new Error(
            `window out of the sky range: requested ${iso(ini + passoMs * inicioIdx)} + ${janelaH} h, ` +
            `but the sky for ${ceu.site} covers ${iso(ini)} to ${iso(ini + passoMs * total)} ` +
            `(${total} samples of ${ceu.step_min} min)`);
    }
    return n;
}

/** Índice do instante (ms ou ISO) na grade do céu. */
export function indiceDe(ceu, quando) {
    const ms = typeof quando === "number" ? quando : instante(quando);
    const p = (ms - instante(ceu.start)) / (ceu.step_min * 60000);
    if (Math.abs(p - Math.round(p)) > 1e-9) throw new Error(`${iso(ms)} is not on the ${ceu.step_min}-min grid of the sky`);
    const i = Math.round(p);
    if (i < 0 || i >= ceu.sun.el.length) throw new Error(`${iso(ms)} is out of the sky range for ${ceu.site}`);
    return i;
}

/** Elevação, raio e horizonte por instante, para Sol e Terra (interpolação feita uma vez). */
export function geometria(ceu, hz) {
    if (ceu.site !== hz.site) throw new Error(`sky and horizon are from different sites: '${ceu.site}' and '${hz.site}'`);
    const g = {};
    for (const corpo of ["sun", "earth"]) {
        const c = ceu[corpo];
        g[corpo] = { el: c.el, rad: c.rad_deg, hz: c.az.map((az) => horizonteEm(hz, az)) };
    }
    return g;
}

export function visivel(g, margem = 0) {
    const f = (c) => c.el.map((el, i) => regraVisivel(el, c.rad[i], c.hz[i], margem));
    return { sol: f(g.sun), terra: f(g.earth) };
}

function contar(b, ini, fim) {
    let n = 0;
    for (let i = ini; i < fim; i++) if (b[i]) n++;
    return n;
}

function resumo(b, ini, fim, passoH) {
    const n = fim - ini;
    const sem = b.map((x) => !x);
    return {
        pct: contar(b, ini, fim) / n,
        longest_with_h: maiorSequencia(b, ini, fim) * passoH,
        longest_without_h: maiorSequencia(sem, ini, fim) * passoH,
    };
}

function diario(b, ini, fim, inicioMs, stepMin) {
    const vistos = [], totais = [];
    for (let i = ini; i < fim; i++) {
        const dia = Math.floor(((i - ini) * stepMin) / 1440);
        vistos[dia] = (vistos[dia] || 0) + (b[i] ? 1 : 0);
        totais[dia] = (totais[dia] || 0) + 1;
    }
    return totais.map((t, k) => ({ date: iso(inicioMs + k * 86400000), pct: vistos[k] / t }));
}

/** Mesma saída de pipeline.metrics.calcular_metricas. */
export function calcularMetricas(ceu, hz, inicioIdx, janelaH, ok = OK_PADRAO, crit = CRIT_PADRAO,
                                 margem = 0, incerteza = INCERTEZA_PADRAO_GRAUS) {
    conferirLimiares(ok, crit);
    const n = janela(ceu, inicioIdx, janelaH);
    if (incerteza < 0) throw new Error(`incerteza_graus must be >= 0 (got: ${incerteza})`);
    const ini = inicioIdx, fim = inicioIdx + n;
    const passoH = ceu.step_min / 60;
    const inicioMs = instante(ceu.start) + ceu.step_min * 60000 * ini;
    const g = geometria(ceu, hz);

    const scoreCom = (m) => {
        const v = visivel(g, m);
        return Math.min(contar(v.sol, ini, fim), contar(v.terra, ini, fim)) / n;
    };
    const v = visivel(g, margem);
    const ambos = v.sol.map((s, i) => s && v.terra[i]);
    const energy = { ...resumo(v.sol, ini, fim, passoH), daily: diario(v.sol, ini, fim, inicioMs, ceu.step_min) };
    const comms = { ...resumo(v.terra, ini, fim, passoH), daily: diario(v.terra, ini, fim, inicioMs, ceu.step_min) };
    const score = Math.min(energy.pct, comms.pct);
    return {
        site: ceu.site,
        window: { start: iso(inicioMs), hours: n * passoH },
        mock: Boolean(ceu.mock) || Boolean(hz.mock),
        energy, comms,
        both: { pct: contar(ambos, ini, fim) / n, longest_h: maiorSequencia(ambos, ini, fim) * passoH },
        score,
        class: classificar(score, ok, crit),
        thresholds: { ok, crit },
        incerteza: { margem_graus: incerteza, score_min: scoreCom(margem + incerteza), score_max: scoreCom(margem - incerteza) },
    };
}

/** Mesma saída de pipeline.metrics.serie_por_atraso. */
export function seriePorAtraso(ceu, hz, inicioIdx, janelaH, atrasos, ok = OK_PADRAO, crit = CRIT_PADRAO, margem = 0) {
    conferirLimiares(ok, crit);
    const n = janela(ceu, inicioIdx, janelaH);
    const total = ceu.sun.el.length;
    const desloc = atrasos.map((a) => {
        const d = passos(ceu, a * 24, `delay of ${a} days`);
        if (inicioIdx + d < 0 || inicioIdx + d + n > total) janela(ceu, inicioIdx + d, janelaH);
        return d;
    });
    const v = visivel(geometria(ceu, hz), margem);
    const acum = (b) => { const a = [0]; b.forEach((x, i) => a.push(a[i] + (x ? 1 : 0))); return a; };
    const as = acum(v.sol), at = acum(v.terra);
    return atrasos.map((a, k) => {
        const i = inicioIdx + desloc[k];
        const sc = Math.min(as[i + n] - as[i], at[i + n] - at[i]) / n;
        return { atraso_dias: a, score: sc, class: classificar(sc, ok, crit) };
    });
}
