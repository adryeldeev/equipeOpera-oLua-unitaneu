// Cards dos locais de pouso (painel direito), gerados a partir de /api/sites.
// Ao clicar, dispara "destino-lunar-selecionado" {id} (a Lua 3D e as etapas escutam).

import { pct, classeCss, rotuloClasse } from "./geo.js";

const lista = document.getElementById("lista-locais");
const nomeSelecionado = document.getElementById("nome-local-selecionado");

function formatarCoord(lat, lon) {
    return `${Math.abs(lat).toFixed(2)}° ${lat < 0 ? "S" : "N"} · ${Math.abs(lon).toFixed(2)}° ${lon < 0 ? "O" : "L"}`;
}

function el(tag, classe, texto) {
    const e = document.createElement(tag);
    if (classe) e.className = classe;
    if (texto !== undefined) e.textContent = texto;
    return e;
}

function indicador(rotulo, valor, classeBarra) {
    const bloco = el("span", "indicador-local");
    const linha = el("span", "linha-indicador");
    linha.append(el("span", "", rotulo), el("span", "valor-indicador", valor === null ? "…" : pct(valor)));
    const trilha = el("span", "trilha-indicador");
    const barra = el("span", `preenchimento ${classeBarra}`);
    barra.style.width = `${Math.round((valor ?? 0) * 100)}%`;
    trilha.appendChild(barra);
    bloco.append(linha, trilha);
    return bloco;
}

/**
 * Desenha os cards.
 * @param {Array} sites           [{id, name, lat, lon, mission, mock}]
 * @param {Map} metricas          id -> resposta de /metricas (ou {erro})
 * @param {string|null} selecionado
 */
export function desenharCards(sites, metricas, selecionado) {
    lista.replaceChildren(...sites.map((s) => {
        const m = metricas.get(s.id);
        const classe = m && !m.erro ? m.class : null;
        const card = el("button", `card-local ${classe ? classeCss(classe) : "carregando"}`);
        card.type = "button";
        card.dataset.id = s.id;
        card.setAttribute("aria-pressed", String(s.id === selecionado));
        card.classList.toggle("selecionado", s.id === selecionado);

        const cab = el("span", "cabecalho-local");
        const nome = el("strong", "", s.name);
        const status = el("span", "status-local", m?.erro ? "Indisponível" : classe ? rotuloClasse(classe) : "Calculando…");
        cab.append(nome, status);
        card.appendChild(cab);

        const coord = el("span", "coordenadas-local", formatarCoord(s.lat, s.lon));
        card.appendChild(coord);
        if (s.mock || m?.mock) card.appendChild(el("span", "tag-mock", "dados mock (horizonte falso)"));

        if (m && !m.erro) {
            card.append(
                indicador("Energia solar", m.energy.pct, `energia-${classeCss(classe)}`),
                indicador("Comunicação", m.comms.pct, "comunicacao"),
            );
            const faixa = el("span", "faixa-incerteza",
                `Score ${pct(m.score)} · faixa ${pct(m.incerteza.score_min)}–${pct(m.incerteza.score_max)} (relevo ±${m.incerteza.margem_graus}°)`);
            card.appendChild(faixa);
        } else if (m?.erro) {
            card.appendChild(el("span", "erro-card", m.erro));
        }
        card.addEventListener("click", () => {
            document.dispatchEvent(new CustomEvent("destino-lunar-selecionado", { detail: { id: s.id } }));
        });
        return card;
    }));
    const atual = sites.find((s) => s.id === selecionado);
    nomeSelecionado.textContent = atual ? atual.name : "Nenhum local selecionado";
}
