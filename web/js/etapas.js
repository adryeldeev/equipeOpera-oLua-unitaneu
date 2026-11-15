// Controle das 5 etapas (Local → Data/Hora → Sol/Terra → Energia → Comunicação),
// do simulador de atraso e da simulação de bateria. Toda a ciência vem da API;
// aqui só se busca, combina e mostra.

import { conectar, api, sitesSemApi } from "./api.js";
import { desenharCards } from "./locais.js";
import { direcaoDoCeu, paraUTC, pct, duracao, simularBateria, rotuloClasse } from "./geo.js";

const $ = (id) => document.getElementById(id);

const estado = {
    padroes: { janela_h: 720, ok: 0.5, crit: 0.2 },
    sites: [],
    selecionado: null,
    inicio: null,           // ISO UTC
    metricas: new Map(),    // id -> /metricas
    visibilidade: new Map(),// id -> /visibilidade (janela inteira)
    horizontes: new Map(),  // id -> /horizonte
    atrasos: null,          // /atrasos do selecionado
    conectada: false,
    pedido: 0,              // descarta respostas de pedidos antigos
};

// ---------------------------------------------------------------- utilidades

function el(tag, classe, texto) {
    const e = document.createElement(tag);
    if (classe) e.className = classe;
    if (texto !== undefined) e.textContent = texto;
    return e;
}

function local(id = estado.selecionado) {
    return estado.sites.find((s) => s.id === id);
}

function aviso(texto, tipo = "info") {
    const caixa = $("aviso-api");
    caixa.textContent = texto;
    caixa.dataset.tipo = tipo;
    caixa.hidden = !texto;
}

function fmtDataLocal(iso) {
    const d = new Date(iso);
    return `${d.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })} (local time) · ` +
        `${iso.replace("T", " ").replace(":00Z", " UTC")}`;
}

// ---------------------------------------------------------------- etapas (navegação)

const ETAPAS = ["localizacao", "data-hora", "sol-terra", "energia", "comunicacao"];

function mostrarEtapa(nome) {
    document.querySelectorAll(".botao-passo").forEach((b) => {
        const ativo = b.dataset.etapa === nome;
        b.classList.toggle("ativo", ativo);
        if (ativo) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
    });
    const i = ETAPAS.indexOf(nome);
    document.querySelectorAll("[data-indicador-etapa]").forEach((e) => {
        const j = ETAPAS.indexOf(e.dataset.indicadorEtapa);
        e.classList.toggle("atual", j === i);
        e.classList.toggle("feita", j < i);
    });
    document.querySelectorAll("[data-conteudo-etapa]").forEach((s) => {
        s.hidden = s.dataset.conteudoEtapa !== nome;
    });
}

document.querySelectorAll(".botao-passo").forEach((b) => {
    b.addEventListener("click", () => mostrarEtapa(b.dataset.etapa));
});
document.querySelectorAll("[data-indicador-etapa]").forEach((e) => {
    e.addEventListener("click", () => mostrarEtapa(e.dataset.indicadorEtapa));
});

// ---------------------------------------------------------------- data e hora

function hojeAoMeioDia() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return [`${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`, "12:00"];
}

function lerDataHora() {
    const iso = paraUTC($("data-missao").value, $("hora-missao").value);
    if (!iso) return;
    estado.inicio = iso;
    $("resumo-data-missao").hidden = false;
    $("valor-resumo-data-missao").textContent = fmtDataLocal(iso);
    recarregarTudo();
}

$("data-missao").addEventListener("change", lerDataHora);
$("hora-missao").addEventListener("change", lerDataHora);

// ---------------------------------------------------------------- dados da API

async function recarregarTudo() {
    if (!estado.conectada || !estado.inicio) return;
    const pedido = ++estado.pedido;
    const janela_h = estado.padroes.janela_h;
    estado.metricas.clear();
    estado.visibilidade.clear();
    desenharCards(estado.sites, estado.metricas, estado.selecionado);

    await Promise.all(estado.sites.map(async (s) => {
        const params = { inicio: estado.inicio, janela_h };
        const [m, v] = await Promise.allSettled([
            api.metricas(s.id, params),
            api.visibilidade(s.id, { inicio: estado.inicio, dias: janela_h / 24 }),
        ]);
        if (pedido !== estado.pedido) return;
        estado.metricas.set(s.id, m.status === "fulfilled" ? m.value : { erro: m.reason.message });
        if (v.status === "fulfilled") estado.visibilidade.set(s.id, v.value);
        desenharCards(estado.sites, estado.metricas, estado.selecionado);
        const mm = estado.metricas.get(s.id);
        if (!mm.erro) {
            document.dispatchEvent(new CustomEvent("metricas-local", {
                detail: { id: s.id, energia: pct(mm.energy.pct), comunicacao: pct(mm.comms.pct), classe: mm.class },
            }));
        }
    }));
    if (pedido !== estado.pedido) return;
    const erros = [...estado.metricas.values()].filter((m) => m.erro);
    aviso(erros.length ? `Some sites failed: ${erros[0].erro}` : "");
    await carregarAtrasos();
    atualizarPaineis();
}

async function carregarAtrasos() {
    estado.atrasos = null;
    if (!estado.selecionado || !estado.inicio) return;
    const pedido = estado.pedido;
    try {
        const a = await api.atrasos(estado.selecionado, {
            inicio: estado.inicio, janela_h: estado.padroes.janela_h, atraso_max_dias: 14,
        });
        if (pedido === estado.pedido) estado.atrasos = a;
    } catch (e) {
        $("resultado-atraso").textContent = `Delay simulation unavailable: ${e.message}`;
    }
}

async function horizonte(id) {
    if (!estado.horizontes.has(id)) estado.horizontes.set(id, await api.horizonte(id));
    return estado.horizontes.get(id);
}

// ---------------------------------------------------------------- painéis

function atualizarPaineis() {
    atualizarLocalizacao();
    atualizarSolTerra();
    atualizarEnergia();
    atualizarComunicacao();
    atualizarAtraso();
    atualizarLuz();
}

function atualizarLocalizacao() {
    const s = local();
    $("valor-etapa-localizacao").textContent = s ? s.name : "No site selected";
    $("coordenadas-etapa-localizacao").textContent = s
        ? `${s.lat.toFixed(4)}°, ${s.lon.toFixed(4)}° (east-positive longitude) · ${s.mission}`
        : "Select a landing site in the cards or on the Moon.";
}

function instante0(id) {
    const v = estado.visibilidade.get(id);
    if (!v) return null;
    const pega = (c) => ({ az: c.az[0], el: c.el[0], rad: c.rad_deg[0], hz: c.horizonte[0], visivel: c.visivel[0] });
    return { sol: pega(v.sol), terra: pega(v.terra) };
}

function textoAstro(nome, a) {
    return `${nome}: azimuth ${a.az.toFixed(1)}°, elevation ${a.el.toFixed(2)}° · terrain at that azimuth ` +
        `${a.hz.toFixed(2)}° → ${a.visivel ? "VISIBLE" : "behind the terrain"}`;
}

async function atualizarSolTerra() {
    const caixa = $("texto-sol-terra");
    const svg = $("grafico-ceu");
    const s = local();
    const i0 = s && instante0(s.id);
    if (!s || !i0) {
        caixa.textContent = s ? "Pick the date and time (step 2)." : "Select a site (step 1).";
        svg.replaceChildren();
        return;
    }
    caixa.replaceChildren(
        el("span", `linha-astro ${i0.sol.visivel ? "ok" : "nao"}`, textoAstro("☀ Sun", i0.sol)),
        el("span", `linha-astro ${i0.terra.visivel ? "ok" : "nao"}`, textoAstro("🌍 Earth", i0.terra)),
    );
    try {
        desenharCeu(svg, await horizonte(s.id), i0);
    } catch (e) {
        svg.replaceChildren();
        caixa.appendChild(el("span", "erro-card", `Horizon unavailable: ${e.message}`));
    }
}

/** Panorama: horizonte do relevo (0–360°) com o Sol e a Terra no instante escolhido. */
function desenharCeu(svg, hz, i0) {
    const NS = "http://www.w3.org/2000/svg";
    const W = 300, H = 120, M = 14;
    const h = hz.horizon_deg;
    const passo = hz.az_step_deg;
    const els = [...h, i0.sol.el + i0.sol.rad, i0.terra.el + i0.terra.rad];
    const yMin = Math.floor(Math.min(...h, i0.sol.el, i0.terra.el, 0) - 1);
    const yMax = Math.ceil(Math.max(...els, 1) + 1);
    const X = (az) => M + (az / 360) * (W - 2 * M);
    const Y = (e) => H - M - ((e - yMin) / (yMax - yMin)) * (H - 2 * M);
    const mk = (tag, attrs, texto) => {
        const n = document.createElementNS(NS, tag);
        Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
        if (texto) n.textContent = texto;
        return n;
    };
    const pontos = h.map((v, i) => `${X(i * passo).toFixed(1)},${Y(v).toFixed(1)}`);
    pontos.push(`${X(360).toFixed(1)},${Y(h[0]).toFixed(1)}`);
    const filhos = [
        mk("rect", { x: 0, y: 0, width: W, height: H, class: "ceu-fundo" }),
        mk("line", { x1: M, x2: W - M, y1: Y(0), y2: Y(0), class: "ceu-zero" }),
        mk("polygon", { points: `${X(0)},${H - M} ${pontos.join(" ")} ${X(360)},${H - M}`, class: "ceu-relevo" }),
    ];
    [["N", 0], ["L", 90], ["S", 180], ["O", 270], ["N", 360]].forEach(([t, az]) => {
        filhos.push(mk("text", { x: X(az), y: H - 2, class: "ceu-rotulo", "text-anchor": "middle" }, t));
    });
    filhos.push(mk("text", { x: 2, y: Y(0) - 2, class: "ceu-rotulo" }, "0°"));
    const escalaY = (H - 2 * M) / (yMax - yMin);
    [["sol", i0.sol, "ceu-sol"], ["terra", i0.terra, "ceu-terra"]].forEach(([, a, classe]) => {
        filhos.push(mk("circle", { cx: X(a.az), cy: Y(a.el), r: Math.max(2.5, a.rad * escalaY), class: classe }));
    });
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.replaceChildren(...filhos);
}

function parametrosEnergia() {
    const n = (id) => Number.parseFloat($(id).value);
    const p = {
        potenciaW: n("potencia-paineis"), consumoW: n("consumo-missao"), capacidadeWh: n("capacidade-bateria"),
        cargaInicialPct: n("carga-bateria"), eficienciaPct: n("eficiencia-paineis"),
    };
    return Object.values(p).every(Number.isFinite) ? p : null;
}

function atualizarEnergia() {
    const s = local();
    const m = s && estado.metricas.get(s.id);
    $("valor-etapa-energia").textContent = m && !m.erro
        ? `Sun visible ${pct(m.energy.pct)} of the time · longest night: ${duracao(m.energy.longest_without_h)} · ` +
          `longest sunlit period: ${duracao(m.energy.longest_with_h)} · site score ${pct(m.score)} ` +
          `(range ${pct(m.incerteza.score_min)}–${pct(m.incerteza.score_max)})`
        : "Select a landing site.";

    // Comparação de todos os locais (mesmos parâmetros).
    const p = parametrosEnergia();
    $("resumo-parametros-energia").textContent = p
        ? `Panels ${p.potenciaW} W × ${p.eficienciaPct}% · load ${p.consumoW} W · battery ${p.capacidadeWh} Wh ` +
          `(start ${p.cargaInicialPct}%) · ${estado.padroes.janela_h} h window.`
        : "Fill in the 5 parameters to simulate the battery at every site.";
    const lista = $("lista-resultados-energia");
    lista.replaceChildren(...estado.sites.map((st) => {
        const mm = estado.metricas.get(st.id);
        const v = estado.visibilidade.get(st.id);
        const item = el("li", "resultado-local-energia");
        item.appendChild(el("span", "nome-resultado-energia", st.name));
        const linha = (rotulo, valor) => {
            const l = el("span", "metrica-simulacao-energia");
            l.append(el("span", "", rotulo), el("strong", "", valor));
            item.appendChild(l);
        };
        if (!mm || mm.erro) { linha("Status", mm?.erro || "computing…"); return item; }
        linha("Time in sunlight", pct(mm.energy.pct));
        linha("Longest night", duracao(mm.energy.longest_without_h));
        if (p && v) {
            const r = simularBateria(v.sol.visivel, v.step_min / 60, p);
            linha("Minimum battery", pct(r.cargaMinimaPct / 100));
            linha("Hours without power", r.sobrevive ? "0 h (survives)" : `${Math.round(r.horasSemEnergia)} h`);
            if (!r.sobrevive) linha("First outage after", duracao(r.primeiraFalhaH));
        }
        return item;
    }));
    const erroEnergia = $("estado-simulacao-energia");
    erroEnergia.textContent = estado.metricas.size ? "" : "Waiting for the API…";
    erroEnergia.hidden = !erroEnergia.textContent;

    // Elevação do Sol no instante escolhido, por local.
    const lst = $("lista-elevacao-solar");
    lst.replaceChildren(...estado.sites.map((st) => {
        const i0 = instante0(st.id);
        const item = el("li", "resultado-elevacao-solar");
        item.appendChild(el("span", "nome-local-elevacao", st.name));
        item.appendChild(el("span", "valor-elevacao-solar", i0
            ? `Sun at ${i0.sol.el.toFixed(2)}° · terrain ${i0.sol.hz.toFixed(2)}° at azimuth ${i0.sol.az.toFixed(0)}° → ` +
              (i0.sol.visivel ? "sunlit" : "in shadow")
            : "—"));
        return item;
    }));
    $("estado-calculo-elevacao").textContent = estado.inicio
        ? `Instant: ${fmtDataLocal(estado.inicio)}. Sky: Skyfield + DE440; terrain: LOLA.`
        : "Pick the date and time (step 2).";
}

function atualizarComunicacao() {
    const s = local();
    const m = s && estado.metricas.get(s.id);
    const i0 = s && instante0(s.id);
    $("valor-etapa-comunicacao").textContent = m && !m.erro
        ? `Earth visible ${pct(m.comms.pct)} of the time · longest blackout: ${duracao(m.comms.longest_without_h)} · ` +
          `Sun and Earth together: ${pct(m.both.pct)}` +
          (i0 ? ` · now: ${i0.terra.visivel ? "Earth visible" : "Earth behind the terrain"} (elevation ${i0.terra.el.toFixed(1)}°)` : "")
        : "Select a landing site.";
}

function atualizarAtraso() {
    const dias = Number($("simulador-atraso").value);
    $("dias-atraso").textContent = `+${dias} ${dias === 1 ? "day" : "days"}`;
    const resultado = $("resultado-atraso");
    const svg = $("grafico-atraso");
    const a = estado.atrasos;
    if (!a) {
        resultado.textContent = estado.selecionado ? "Computing…" : "Select a site to simulate a delay.";
        svg.replaceChildren();
        return;
    }
    const p = a.serie[dias];
    const base = a.serie[0];
    const dif = (p.score - base.score) * 100;
    resultado.textContent = `With +${dias} ${dias === 1 ? "day" : "days"}: score ${pct(p.score)} (${rotuloClasse(p.class)})` +
        (dias ? ` · ${dif >= 0 ? "+" : ""}${dif.toFixed(1)} pts vs. landing on schedule` : "");
    resultado.dataset.classe = p.class;

    const NS = "http://www.w3.org/2000/svg";
    const W = 300, H = 70, n = a.serie.length, bw = W / n;
    const barras = a.serie.map((q, i) => {
        const r = document.createElementNS(NS, "rect");
        const h = Math.max(1, q.score * (H - 12));
        r.setAttribute("x", (i * bw + 1).toFixed(1));
        r.setAttribute("width", (bw - 2).toFixed(1));
        r.setAttribute("y", (H - h).toFixed(1));
        r.setAttribute("height", h.toFixed(1));
        r.setAttribute("class", `barra-atraso ${q.class}${i === dias ? " atual" : ""}`);
        const t = document.createElementNS(NS, "title");
        t.textContent = `+${i} d: ${pct(q.score)} (${rotuloClasse(q.class)})`;
        r.appendChild(t);
        return r;
    });
    const linha = (v, classe) => {
        const l = document.createElementNS(NS, "line");
        const y = H - v * (H - 12);
        Object.entries({ x1: 0, x2: W, y1: y, y2: y, class: classe }).forEach(([k, val]) => l.setAttribute(k, val));
        return l;
    };
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.replaceChildren(...barras, linha(a.thresholds.ok, "limiar-ok"), linha(a.thresholds.crit, "limiar-crit"));
}

$("simulador-atraso").addEventListener("input", atualizarAtraso);
document.querySelectorAll(".parametros-energia input").forEach((i) => i.addEventListener("input", atualizarEnergia));

function atualizarLuz() {
    // A direção do Sol é a mesma para a Lua toda; usa o local selecionado
    // (ou o primeiro com dados) só para converter az/el em vetor.
    const s = local() || estado.sites.find((x) => estado.visibilidade.has(x.id));
    const i0 = s && instante0(s.id);
    document.dispatchEvent(new CustomEvent("direcao-sol", {
        detail: i0
            ? { direcao: direcaoDoCeu(s.lat, s.lon, i0.sol.az, i0.sol.el),
                texto: `Light from the real Sun direction at ${fmtDataLocal(estado.inicio)} (Skyfield/DE440).` }
            : { direcao: null, texto: "Pick a site, date and time: the light follows the real Sun direction." },
    }));
}

// ---------------------------------------------------------------- seleção

document.addEventListener("destino-lunar-selecionado", async (e) => {
    estado.selecionado = e.detail.id;
    desenharCards(estado.sites, estado.metricas, estado.selecionado);
    atualizarPaineis();
    await carregarAtrasos();
    atualizarAtraso();
});

// ---------------------------------------------------------------- início

async function iniciar() {
    const [d, h] = hojeAoMeioDia();
    $("data-missao").value = d;
    $("hora-missao").value = h;
    mostrarEtapa("localizacao");
    try {
        const { base, saude } = await conectar();
        estado.conectada = true;
        estado.padroes = { ...estado.padroes, ...saude.padroes };
        if (saude.intervalo_suportado) {
            $("data-missao").min = saude.intervalo_suportado.inicio.slice(0, 10);
            $("data-missao").max = saude.intervalo_suportado.fim.slice(0, 10);
        }
        aviso(saude.efemerides ? "" : `API in fallback mode (year 2027 only): ${saude.erro_efemerides}`, "alerta");
        estado.sites = await api.sites();
        console.info(`API conectada em ${base}`);
    } catch (e) {
        estado.sites = await sitesSemApi();
        aviso(`${e.message}. From the project root run: uvicorn api.main:app --port 8001 ` +
              "and open http://localhost:8001/ . Without the API only the site list is shown.", "erro");
    }
    desenharCards(estado.sites, estado.metricas, estado.selecionado);
    document.dispatchEvent(new CustomEvent("locais-carregados", { detail: { sites: estado.sites } }));

    // Cenário pela URL (link compartilhável): ?local=malapert&data=2027-03-01&hora=12:00&etapa=energia&atraso=5
    const url = new URLSearchParams(location.search);
    if (url.get("data")) $("data-missao").value = url.get("data");
    if (url.get("hora")) $("hora-missao").value = url.get("hora");
    if (url.get("atraso")) $("simulador-atraso").value = url.get("atraso");
    if (ETAPAS.includes(url.get("etapa"))) mostrarEtapa(url.get("etapa"));
    const id = url.get("local");
    if (id && estado.sites.some((s) => s.id === id)) {
        document.dispatchEvent(new CustomEvent("destino-lunar-selecionado", { detail: { id } }));
    }
    atualizarPaineis();
    lerDataHora();
    iniciado = true;
}

// Mantém a URL igual ao cenário na tela (para copiar e compartilhar).
let iniciado = false;
function sincronizarURL() {
    if (!iniciado) return;
    const p = new URLSearchParams();
    if (estado.selecionado) p.set("local", estado.selecionado);
    if ($("data-missao").value) p.set("data", $("data-missao").value);
    if ($("hora-missao").value) p.set("hora", $("hora-missao").value);
    const etapa = document.querySelector(".botao-passo.ativo")?.dataset.etapa;
    if (etapa && etapa !== "localizacao") p.set("etapa", etapa);
    if ($("simulador-atraso").value !== "0") p.set("atraso", $("simulador-atraso").value);
    history.replaceState(null, "", `${location.pathname}?${p}`);
}
["change", "input", "click"].forEach((ev) => document.addEventListener(ev, () => setTimeout(sincronizarURL)));
document.addEventListener("destino-lunar-selecionado", () => setTimeout(sincronizarURL));

iniciar();
