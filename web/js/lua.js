// Lua 3D (Three.js). Baseado no visualizador do LanderBnB (feature/landerbnb).
//
// Esfera com as texturas do NASA SVS CGI Moon Kit (cor LROC + relevo LOLA)
// e, por cima, uma calota do polo sul (-80° a -90°) feita com o mesmo DEM do
// LOLA usado no horizonte (pipeline/tools/gerar_texturas_lua.py).
// Orientação: a de geo.js (lon 0 em +X, norte em +Y), conferida com
// Tycho, Copérnico e Mare Crisium na textura e com testes em web/tests/.
//
// Eventos que este módulo ESCUTA (disparados por etapas.js / locais.js):
//   locais-carregados          {sites: [{id, name, lat, lon, category}]}
//   destino-lunar-selecionado  {id}
//   direcao-sol                {direcao: [x, y, z] | null, texto}
//   metricas-local             {id, energia, comunicacao, classe}
// E DISPARA: destino-lunar-selecionado {id} ao clicar num marcador.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import { direcaoCena, latLonDaCena, uvCalotaSul, CALOTA_LAT_BORDA } from "./geo.js";

const RAIO = 1.5;                 // unidades da cena
const container = document.getElementById("lua-3d");

let locais = new Map();           // id -> {id, name, lat, lon, category}
let selecionado = null;
let transicaoCamera = null;
const marcadores = new Map();     // id -> {element, position}
const indicadores = new Map();    // id -> {energia, comunicacao}
const raycaster = new THREE.Raycaster();

// ---------------------------------------------------------------- camadas HTML

const camadaMarcadores = document.createElement("div");
camadaMarcadores.className = "camada-marcadores";
camadaMarcadores.setAttribute("aria-label", "Landing sites");
container.appendChild(camadaMarcadores);

const avisoOrientacao = document.createElement("div");
avisoOrientacao.className = "aviso-orientacao";
avisoOrientacao.textContent = "True positions (MOON_ME) · polar terrain: LOLA · texture: NASA SVS";
camadaMarcadores.appendChild(avisoOrientacao);

const painelLocal = document.createElement("section");
painelLocal.className = "painel-local-visualizador";
painelLocal.setAttribute("aria-label", "Selected site details");
painelLocal.setAttribute("aria-live", "polite");
painelLocal.hidden = true;

const cabecalhoPainel = document.createElement("div");
cabecalhoPainel.className = "cabecalho-painel-local";
const nomePainel = document.createElement("h3");
nomePainel.className = "nome-painel-local";
const fecharPainel = document.createElement("button");
fecharPainel.type = "button";
fecharPainel.className = "fechar-painel-local";
fecharPainel.setAttribute("aria-label", "Close site details");
fecharPainel.textContent = "×";
fecharPainel.addEventListener("click", () => { painelLocal.hidden = true; });
cabecalhoPainel.append(nomePainel, fecharPainel);
painelLocal.appendChild(cabecalhoPainel);

function linhaPainel(rotulo) {
    const linha = document.createElement("p");
    linha.className = "linha-painel-local";
    const nome = document.createElement("span");
    nome.className = "rotulo-painel-local";
    nome.textContent = rotulo;
    const valor = document.createElement("strong");
    valor.className = "valor-painel-local";
    linha.append(nome, valor);
    painelLocal.appendChild(linha);
    return valor;
}

const coordenadasPainel = linhaPainel("Lunar coordinates");
const energiaPainel = linhaPainel("Solar power");
const comunicacaoPainel = linhaPainel("Earth link");
const notaPainel = document.createElement("p");
notaPainel.className = "aviso-indicadores-simulados";
notaPainel.textContent = "% of time in the selected window · sky: Skyfield/DE440 · terrain: LOLA";
painelLocal.appendChild(notaPainel);
container.appendChild(painelLocal);

const destinoTexto = document.createElement("div");
destinoTexto.className = "destino-lua";
destinoTexto.setAttribute("aria-live", "polite");
container.appendChild(destinoTexto);

const estadoCarregamento = document.createElement("div");
estadoCarregamento.className = "estado-carregamento-lua";
estadoCarregamento.setAttribute("role", "status");
estadoCarregamento.textContent = "Loading 3D Moon...";
container.appendChild(estadoCarregamento);

const estadoIluminacao = document.createElement("div");
estadoIluminacao.className = "estado-iluminacao-solar";
estadoIluminacao.setAttribute("role", "status");
estadoIluminacao.setAttribute("aria-live", "polite");
estadoIluminacao.textContent = "Pick a site, date and time: the light follows the real Sun direction.";
container.appendChild(estadoIluminacao);

function formatarCoord(lat, lon) {
    return `${Math.abs(lat).toFixed(2)}° ${lat < 0 ? "S" : "N"} · ${Math.abs(lon).toFixed(2)}° ${lon < 0 ? "W" : "E"}`;
}

function atualizarPainel() {
    const local = locais.get(selecionado);
    if (!local) { painelLocal.hidden = true; return; }
    const ind = indicadores.get(selecionado) || {};
    nomePainel.textContent = local.name;
    coordenadasPainel.textContent = formatarCoord(local.lat, local.lon);
    energiaPainel.textContent = ind.energia ?? "—";
    comunicacaoPainel.textContent = ind.comunicacao ?? "—";
    painelLocal.hidden = false;
}

// ---------------------------------------------------------------- cena

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 1000);
camera.up.set(1, 0, 0); // ver direcaoCamera(); precisa vir ANTES de criar o OrbitControls
camera.position.set(1, -3, 1);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
container.appendChild(renderer.domElement);

// Luz fraca de preenchimento + "Sol" direcional (posição definida pelo evento direcao-sol).
const luzAmbiente = new THREE.AmbientLight(0xffffff, 0.12);
scene.add(luzAmbiente);
const luzSolar = new THREE.DirectionalLight(0xffffff, 3.0);
luzSolar.position.set(5, 3, 5);
scene.add(luzSolar);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = false;
controls.enableZoom = true;
controls.enablePan = false;
// Sem minDistance/maxDistance: o OrbitControls mede até o ALVO (que fica na
// superfície depois de escolher um local) e empurraria a câmera para longe.
// O limite é aplicado em relação ao CENTRO da Lua, em limitarDistancia().
controls.addEventListener("start", () => { transicaoCamera = null; });

// ---------------------------------------------------------------- Lua

const lua = new THREE.Group();
scene.add(lua);

function carregarTextura(url, srgb = true) {
    return new Promise((resolve, reject) => {
        new THREE.TextureLoader().load(url, (t) => {
            if (srgb) t.colorSpace = THREE.SRGBColorSpace;
            t.anisotropy = renderer.capabilities.getMaxAnisotropy();
            resolve(t);
        }, undefined, reject);
    });
}

function criarCalotaSul(cor, normal) {
    // Faixa da esfera de -80° a -90°, um pouco acima da superfície global.
    const largura = (90 + CALOTA_LAT_BORDA) * Math.PI / 180;
    const geo = new THREE.SphereGeometry(RAIO * 1.0006, 256, 64, 0, Math.PI * 2, Math.PI - largura, largura);
    // UV na grade estereográfica do DEM (em vez do UV equirretangular padrão).
    const pos = geo.attributes.position;
    const uv = geo.attributes.uv;
    for (let i = 0; i < pos.count; i++) {
        const [lat, lon] = latLonDaCena(pos.getX(i), pos.getY(i), pos.getZ(i));
        const [u, v] = uvCalotaSul(lat, lon);
        uv.setXY(i, u, v);
    }
    uv.needsUpdate = true;
    const mat = new THREE.MeshStandardMaterial({
        map: cor, normalMap: normal, normalMapType: THREE.ObjectSpaceNormalMap,
        transparent: true, roughness: 1, metalness: 0, depthWrite: false,
    });
    return new THREE.Mesh(geo, mat);
}

async function montarLua() {
    const [cor, relevo, calotaCor, calotaNormal] = await Promise.all([
        carregarTextura("./assets/lroc_color_2k.jpg"),
        carregarTextura("./assets/ldem_3_8bit.jpg", false),
        carregarTextura("./assets/polo_sul_cor.png"),
        carregarTextura("./assets/polo_sul_normal.jpg", false),
    ]);
    const esfera = new THREE.Mesh(
        new THREE.SphereGeometry(RAIO, 192, 96),
        new THREE.MeshStandardMaterial({ map: cor, bumpMap: relevo, bumpScale: 2, roughness: 1, metalness: 0 }),
    );
    lua.add(esfera, criarCalotaSul(calotaCor, calotaNormal));
}

// ---------------------------------------------------------------- marcadores

function posicaoDoLocal(local) {
    const [x, y, z] = direcaoCena(local.lat, local.lon);
    return new THREE.Vector3(x, y, z).multiplyScalar(RAIO * 1.003);
}

function criarMarcadores() {
    marcadores.forEach((m) => m.element.remove());
    marcadores.clear();
    locais.forEach((local) => {
        const botao = document.createElement("button");
        botao.type = "button";
        botao.className = "marcador-local";
        botao.setAttribute("aria-label", `Select ${local.name}`);
        botao.setAttribute("aria-pressed", String(local.id === selecionado));
        botao.classList.toggle("selecionado", local.id === selecionado);
        const ponto = document.createElement("span");
        ponto.className = "ponto-marcador";
        ponto.setAttribute("aria-hidden", "true");
        const rotulo = document.createElement("span");
        rotulo.className = "rotulo-marcador";
        rotulo.textContent = local.name;
        botao.append(ponto, rotulo);
        botao.addEventListener("click", () => {
            document.dispatchEvent(new CustomEvent("destino-lunar-selecionado", { detail: { id: local.id } }));
        });
        camadaMarcadores.appendChild(botao);
        marcadores.set(local.id, { element: botao, position: posicaoDoLocal(local) });
    });
}

function atualizarMarcadores() {
    if (marcadores.size === 0) return;
    const largura = container.clientWidth;
    const altura = container.clientHeight;
    const candidatos = [];

    marcadores.forEach((m) => {
        const p = m.position;
        const normal = p.clone().normalize();
        const paraCamera = camera.position.clone().sub(p).normalize();
        const tela = p.clone().project(camera);
        const dentro = tela.x >= -1 && tela.x <= 1 && tela.y >= -1 && tela.y <= 1 && tela.z >= -1 && tela.z <= 1;
        if (!dentro || normal.dot(paraCamera) <= 0) { m.element.hidden = true; return; }

        const dist = camera.position.distanceTo(p);
        raycaster.set(camera.position, p.clone().sub(camera.position).normalize());
        raycaster.far = Math.max(0, dist - 0.005);
        const hits = raycaster.intersectObject(lua, true);
        if (hits.length > 0 && hits[0].distance < dist - 0.005) { m.element.hidden = true; return; }

        m.element.hidden = false;
        candidatos.push({ element: m.element, x: (tela.x * 0.5 + 0.5) * largura, y: (-tela.y * 0.5 + 0.5) * altura });
    });

    // Rótulos sem sobreposição (mesma lógica do LanderBnB).
    candidatos.sort((a, b) => a.y - b.y);
    let ultimoY = 12;
    candidatos.forEach((c) => { c.rotuloY = Math.max(c.y, ultimoY); ultimoY = c.rotuloY + 26; });
    const excesso = ultimoY - 26 - (altura - 12);
    if (excesso > 0) candidatos.forEach((c) => { c.rotuloY -= excesso; });
    candidatos.forEach((c) => {
        c.element.style.left = `${c.x}px`;
        c.element.style.top = `${c.y}px`;
        c.element.style.setProperty("--deslocamento-rotulo-y", `${c.rotuloY - c.y}px`);
    });
}

// ---------------------------------------------------------------- câmera

// O "para cima" da câmera é +X (lon 0°, face voltada para a Terra), e não o
// polo norte: assim a câmera pode olhar o polo sul de frente sem a matriz de
// visão degenerar, e a tela fica como num mapa polar (lon 0° em cima).
// A singularidade passa para os pontos lat 0°/lon 0° e lon 180°, onde não há
// locais; mesmo assim a direção é desviada se chegar a menos de 5° deles.
function direcaoCamera(lat, lon) {
    const v = new THREE.Vector3(...direcaoCena(lat, lon));
    if (Math.abs(v.x) > Math.cos(5 * Math.PI / 180)) v.y -= 0.1;
    return v.normalize();
}

function iniciarTransicao(id) {
    const local = locais.get(id);
    if (!local) return;
    const [x, y, z] = direcaoCena(local.lat, local.lon);
    const alvo = new THREE.Vector3(x, y, z);
    const destino = direcaoCamera(local.lat, local.lon);
    const polo = local.lat < -60;
    transicaoCamera = {
        inicio: performance.now(),
        duracao: 1800,
        direcaoInicial: camera.position.clone().normalize(),
        rotacao: new THREE.Quaternion().setFromUnitVectors(camera.position.clone().normalize(), destino),
        raioInicial: camera.position.length(),
        // Locais polares ficam a poucos km uns dos outros: chega mais perto.
        raioFinal: RAIO * (polo ? 1.25 : 1.8),
        alvoInicial: controls.target.clone(),
        alvoFinal: alvo.multiplyScalar(RAIO * 0.97),
    };
}

function atualizarTransicao(agora) {
    if (!transicaoCamera) return;
    const t = transicaoCamera;
    const prog = Math.min((agora - t.inicio) / t.duracao, 1);
    const s = prog * prog * (3 - 2 * prog);
    const rot = new THREE.Quaternion().slerp(t.rotacao, s);
    const dir = t.direcaoInicial.clone().applyQuaternion(rot).normalize();
    camera.position.copy(dir.multiplyScalar(THREE.MathUtils.lerp(t.raioInicial, t.raioFinal, s)));
    controls.target.copy(t.alvoInicial).lerp(t.alvoFinal, s);
    camera.lookAt(controls.target);
    if (prog === 1) transicaoCamera = null;
}

/** Mantém a câmera fora da Lua e não longe demais (distância ao centro). */
function limitarDistancia() {
    const d = camera.position.length();
    const min = RAIO * 1.04, max = RAIO * 8;
    if (d < min) camera.position.setLength(min);
    else if (d > max) camera.position.setLength(max);
}

// ---------------------------------------------------------------- eventos

document.addEventListener("locais-carregados", (e) => {
    locais = new Map(e.detail.sites.map((s) => [s.id, s]));
    criarMarcadores();
    // Câmera inicial: face voltada para a Terra, inclinada para o polo sul
    // (onde estão os locais), sem ficar exatamente sobre o polo.
    if (!selecionado) {
        camera.position.copy(direcaoCamera(-70, 0).multiplyScalar(RAIO * 2.6));
        controls.target.set(0, 0, 0);
        controls.update();
    }
});

document.addEventListener("destino-lunar-selecionado", (e) => {
    selecionado = e.detail.id;
    const local = locais.get(selecionado);
    destinoTexto.textContent = local ? `Destination: ${local.name}` : "";
    marcadores.forEach((m, id) => {
        m.element.classList.toggle("selecionado", id === selecionado);
        m.element.setAttribute("aria-pressed", String(id === selecionado));
    });
    atualizarPainel();
    iniciarTransicao(selecionado);
});

document.addEventListener("direcao-sol", (e) => {
    const { direcao, texto } = e.detail;
    if (direcao) {
        luzSolar.position.set(direcao[0], direcao[1], direcao[2]).multiplyScalar(10);
    }
    estadoIluminacao.textContent = texto;
});

document.addEventListener("metricas-local", (e) => {
    indicadores.set(e.detail.id, { energia: e.detail.energia, comunicacao: e.detail.comunicacao });
    if (e.detail.id === selecionado) atualizarPainel();
});

// ---------------------------------------------------------------- laço

function ajustarTela() {
    const w = container.clientWidth, h = container.clientHeight;
    if (!w || !h) return;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
}

window.addEventListener("resize", ajustarTela);
ajustarTela();

function animar() {
    requestAnimationFrame(animar);
    controls.update();
    atualizarTransicao(performance.now());
    limitarDistancia();
    atualizarMarcadores();
    renderer.render(scene, camera);
}

montarLua()
    .then(() => { estadoCarregamento.remove(); animar(); })
    .catch((erro) => {
        console.error("Erro ao carregar a Lua:", erro);
        estadoCarregamento.textContent = "Could not load the Moon textures (web/assets/).";
        estadoCarregamento.classList.add("erro");
        animar();
    });
