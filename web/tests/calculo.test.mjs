// O calculo.js (modo estático) tem de dar EXATAMENTE os mesmos números do
// pipeline/metrics.py. Referência: python pipeline/tools/gerar_referencia_js.py
//   node --test web/tests/
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { calcularMetricas, seriePorAtraso, horizonteEm, indiceDe, classificar } from "../js/calculo.js";

const raiz = new URL("../../", import.meta.url);
const ler = (rel) => JSON.parse(readFileSync(new URL(rel, raiz), "utf8"));
const ref = ler("web/tests/fixtures/metricas_ref.json");

for (const c of ref.casos) {
    test(`métricas iguais ao Python: ${c.site} (início ${c.inicio_idx}, ${c.janela_h} h, margem ${c.margem})`, () => {
        const ceu = ler(`data/sky/${c.site}.json`), hz = ler(`data/horizon/${c.site}.json`);
        const m = calcularMetricas(ceu, hz, c.inicio_idx, c.janela_h, c.ok, c.crit, c.margem);
        assert.deepStrictEqual(m, c.metricas);
        assert.deepStrictEqual(seriePorAtraso(ceu, hz, c.inicio_idx, c.janela_h, [...Array(15).keys()], c.ok, c.crit, c.margem), c.atrasos);
    });
}

test("horizonte interpolado com wrap (igual ao teste do Python)", () => {
    const h = Array(360).fill(0);
    h[11] = 10; h[0] = 10;
    const hz = { az_step_deg: 1, horizon_deg: h };
    assert.deepEqual([10.5, 10, 11, 359.5, 0, 360, -0.5].map((a) => horizonteEm(hz, a)), [5, 0, 10, 5, 10, 10, 5]);
});

test("classes e limiares", () => {
    assert.deepEqual([0.19, 0.2, 0.49, 0.5].map((s) => classificar(s, 0.5, 0.2)), ["critico", "moderado", "moderado", "ideal"]);
    assert.throws(() => classificar(0.3, 0.2, 0.5), /must be lower/);
});

test("índice na grade e fora do alcance", () => {
    const ceu = ler("data/sky/malapert.json");
    assert.equal(indiceDe(ceu, "2027-01-02T03:00:00Z"), 27);
    assert.throws(() => indiceDe(ceu, "2027-01-01T00:30:00Z"), /grid/);
    assert.throws(() => indiceDe(ceu, "2030-01-01T00:00:00Z"), /out of the sky range/);
    const hz = ler("data/horizon/malapert.json");
    assert.throws(() => calcularMetricas(ceu, hz, 8700, 720), /out of the sky range/);
});
