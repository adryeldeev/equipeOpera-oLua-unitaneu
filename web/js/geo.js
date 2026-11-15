// Funções puras (sem DOM nem Three.js): geometria, datas e simulação de bateria.
// Testadas com: node --test web/tests/
//
// Eixos da cena (Three.js), a partir do referencial lunar MOON_ME:
//   X = ME x (lat 0°, lon 0°: centro da face visível)
//   Y = ME z (polo norte)
//   Z = −ME y (lon 90° L fica em −Z)
// É a mesma convenção da textura equirretangular numa SphereGeometry padrão
// (lon −180° na borda esquerda, leste para a direita, norte em cima).

const RAD = Math.PI / 180;
export const R_LUA_M = 1_737_400;
// Calota sul (web/assets/polo_sul_*): grade estereográfica polar do LOLA.
export const CALOTA_MEIA_LARGURA_M = 304_000;
export const CALOTA_LAT_BORDA = -80;

/** Vetor unitário da cena para (lat, lon) em graus (lon leste positiva). */
export function direcaoCena(lat, lon) {
    const f = lat * RAD, l = lon * RAD;
    return [Math.cos(f) * Math.cos(l), Math.sin(f), -Math.cos(f) * Math.sin(l)];
}

/** (lat, lon) em graus a partir de um vetor da cena (qualquer módulo). */
export function latLonDaCena(x, y, z) {
    const r = Math.hypot(x, y, z);
    return [Math.asin(y / r) / RAD, Math.atan2(-z, x) / RAD];
}

/** UV da calota sul: projeção estereográfica polar, igual à do DEM. */
export function uvCalotaSul(lat, lon) {
    const rho = 2 * R_LUA_M * Math.tan((45 + lat / 2) * RAD);
    const x = rho * Math.sin(lon * RAD);
    const y = rho * Math.cos(lon * RAD);
    const L = CALOTA_MEIA_LARGURA_M;
    return [(x + L) / (2 * L), (y + L) / (2 * L)];
}

/**
 * Direção (vetor da cena) de um astro visto do local com azimute/elevação.
 * Azimute a partir do Norte, horário. O Sol está tão longe que a mesma
 * direção vale para a Lua inteira: serve para posicionar a luz.
 */
export function direcaoDoCeu(lat, lon, azGraus, elGraus) {
    const f = lat * RAD, l = lon * RAD, a = azGraus * RAD, e = elGraus * RAD;
    const sf = Math.sin(f), cf = Math.cos(f), sl = Math.sin(l), cl = Math.cos(l);
    const leste = [-sl, cl, 0];
    const norte = [-sf * cl, -sf * sl, cf];
    const cima = [cf * cl, cf * sl, sf];
    const ce = Math.cos(e), se = Math.sin(e), sa = Math.sin(a), ca = Math.cos(a);
    const me = [0, 1, 2].map((i) => ce * sa * leste[i] + ce * ca * norte[i] + se * cima[i]);
    return [me[0], me[2], -me[1]];
}

/** "AAAA-MM-DD" + "HH:MM" no fuso do navegador -> ISO 8601 em UTC ("...Z"). */
export function paraUTC(data, hora) {
    if (!data) return null;
    const d = new Date(`${data}T${hora || "00:00"}:00`);
    if (Number.isNaN(d.getTime())) return null;
    d.setUTCMinutes(0, 0, 0); // a API trabalha em passos de 1 h
    return d.toISOString().replace(".000Z", "Z");
}

/** Fraction (0–1) -> "66%" (or "66.4%" with decimals). */
export function pct(fracao, casas = 0) {
    if (fracao === null || fracao === undefined || Number.isNaN(fracao)) return "—";
    return `${(fracao * 100).toFixed(casas)}%`;
}

/** Hours -> "5 h" or "6.7 days". */
export function duracao(horas) {
    if (horas === null || horas === undefined) return "—";
    if (horas < 48) return `${Math.round(horas)} h`;
    return `${(horas / 24).toFixed(1)} days`;
}

/**
 * Simula a bateria hora a hora com a linha do tempo de Sol visível.
 *
 * Modelo simples e declarado: com Sol visível, o painel gera
 * potência × eficiência (painel sempre apontado para o Sol, sem perda por
 * ângulo); sem Sol, gera 0. Consumo constante. Carga limitada a [0, capacidade].
 *
 * @param {boolean[]} solVisivel  um valor por passo
 * @param {number} passoH         duração do passo em horas
 * @param {{potenciaW, consumoW, capacidadeWh, cargaInicialPct, eficienciaPct}} p
 */
export function simularBateria(solVisivel, passoH, p) {
    const geracao = p.potenciaW * (p.eficienciaPct / 100);
    let carga = p.capacidadeWh * (p.cargaInicialPct / 100);
    let minima = carga;
    let horasSemEnergia = 0;
    let deficitWh = 0;
    let primeiraFalhaH = null;
    solVisivel.forEach((visivel, i) => {
        const saldo = ((visivel ? geracao : 0) - p.consumoW) * passoH;
        let nova = carga + saldo;
        if (nova < 0) {
            deficitWh += -nova;
            horasSemEnergia += passoH;
            if (primeiraFalhaH === null) primeiraFalhaH = i * passoH;
            nova = 0;
        }
        carga = Math.min(nova, p.capacidadeWh);
        minima = Math.min(minima, carga);
    });
    return {
        cargaFinalPct: (carga / p.capacidadeWh) * 100,
        cargaMinimaPct: (minima / p.capacidadeWh) * 100,
        horasSemEnergia,
        deficitWh,
        primeiraFalhaH,
        sobrevive: horasSemEnergia === 0,
    };
}

/** Classe da API -> classe CSS do card (o design usa "risco" para crítico). */
export function classeCss(classe) {
    return { ideal: "ideal", moderado: "moderado", critico: "risco" }[classe] || "moderado";
}

export function rotuloClasse(classe) {
    return { ideal: "Ideal", moderado: "Moderate", critico: "Critical" }[classe] || "—";
}
