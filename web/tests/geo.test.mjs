// node --test web/tests/
import test from "node:test";
import assert from "node:assert/strict";

import {
    direcaoCena, latLonDaCena, uvCalotaSul, direcaoDoCeu, paraUTC, pct, duracao,
    simularBateria, classeCss,
} from "../js/geo.js";

const perto = (a, b, tol = 1e-9) => a.forEach((v, i) => assert.ok(Math.abs(v - b[i]) < tol, `${a} != ${b}`));

test("direção da cena: lon 0 em +X, norte em +Y, lon 90° L em −Z", () => {
    perto(direcaoCena(0, 0), [1, 0, 0]);
    perto(direcaoCena(90, 0), [0, 1, 0]);
    perto(direcaoCena(0, 90), [0, 0, -1]);
    perto(direcaoCena(-90, 0), [0, -1, 0]);
});

test("lat/lon da cena é a inversa", () => {
    for (const [lat, lon] of [[-85.99, 2.05], [-89.77, -156.44], [0.67, 23.47]]) {
        perto(latLonDaCena(...direcaoCena(lat, lon)), [lat, lon], 1e-9);
    }
});

test("UV da calota: polo no centro; lon 0 para cima (v>0,5); lon 90° L para a direita (u>0,5)", () => {
    perto(uvCalotaSul(-90, 0), [0.5, 0.5]);
    const [u0, v0] = uvCalotaSul(-85, 0);
    assert.ok(Math.abs(u0 - 0.5) < 1e-12 && v0 > 0.5);
    const [u90, v90] = uvCalotaSul(-85, 90);
    assert.ok(u90 > 0.5 && Math.abs(v90 - 0.5) < 1e-12);
    // O paralelo −80° cai na borda da textura (o DEM vai até 304.000 m; −80° fica a 304.006 m).
    const [, vb] = uvCalotaSul(-80, 0);
    assert.ok(vb > 0.999 && vb < 1.0001);
});

test("direção do céu: zênite = vertical local; norte a partir do polo sul = lon 0", () => {
    perto(direcaoDoCeu(0, 0, 0, 90), direcaoCena(0, 0));
    perto(direcaoDoCeu(-30, 40, 123, 90), direcaoCena(-30, 40));
    // No equador, lon 0: leste (az 90, el 0) aponta para lon 90° L (−Z).
    perto(direcaoDoCeu(0, 0, 90, 0), [0, 0, -1]);
    // No equador, norte (az 0) aponta para o polo norte (+Y).
    perto(direcaoDoCeu(0, 0, 0, 0), [0, 1, 0]);
    // Quase no polo sul, em lon 0: o norte aponta para lon 0 no horizonte (+X).
    perto(direcaoDoCeu(-89.9999, 0, 0, 0), [1, 0, 0], 1e-5);
});

test("paraUTC devolve ISO em UTC, na hora cheia", () => {
    const iso = paraUTC("2027-03-01", "12:34");
    assert.match(iso, /^2027-03-0[12]T\d\d:00:00Z$/);
    assert.equal(new Date(iso).getUTCMinutes(), 0);
    assert.equal(paraUTC("", "10:00"), null);
    assert.equal(paraUTC("xx", "10:00"), null);
});

test("formatação", () => {
    assert.equal(pct(0.658), "66%");
    assert.equal(pct(0.6584, 1), "65,8%");
    assert.equal(pct(null), "—");
    assert.equal(duracao(5), "5 h");
    assert.equal(duracao(161), "6,7 dias");
    assert.equal(classeCss("critico"), "risco");
});

test("bateria: sol o tempo todo com geração > consumo nunca falha", () => {
    const r = simularBateria(Array(48).fill(true), 1,
        { potenciaW: 200, consumoW: 100, capacidadeWh: 1000, cargaInicialPct: 50, eficienciaPct: 100 });
    assert.equal(r.sobrevive, true);
    assert.equal(r.cargaFinalPct, 100);
});

test("bateria: noite de 10 h com 1000 Wh e 150 W de consumo falha na 7ª hora", () => {
    const sol = Array(10).fill(false);
    const r = simularBateria(sol, 1,
        { potenciaW: 500, consumoW: 150, capacidadeWh: 1000, cargaInicialPct: 100, eficienciaPct: 90 });
    // 1000 Wh / 150 W = 6,67 h -> falta energia a partir do passo 6 (7ª hora).
    assert.equal(r.sobrevive, false);
    assert.equal(r.primeiraFalhaH, 6);
    assert.equal(r.horasSemEnergia, 4);
    assert.ok(Math.abs(r.deficitWh - (1500 - 1000)) < 1e-9);
    assert.equal(r.cargaMinimaPct, 0);
});

test("bateria: eficiência reduz a geração", () => {
    const p = { potenciaW: 100, consumoW: 60, capacidadeWh: 100, cargaInicialPct: 0, eficienciaPct: 50 };
    const r = simularBateria([true, true], 1, p); // gera 50 W < 60 W
    assert.equal(r.sobrevive, false);
});
