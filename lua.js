
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

// ENCONTRAR O ESPAÇO DA LUA
const container = document.getElementById("lua-3d");
const coordenadasLocais = {
    "Cratera Shackleton": { latitude: -89.9, longitude: 0 },
    "Malapert Mountain": { latitude: -84.6, longitude: 11.2 },
    "Borda Cratera Nobile": { latitude: -85, longitude: 33 }
};

let lua = null;
let raioLua = 0;
let transicaoCamera = null;
let destinoPendente = null;
const marcadoresLocais = new Map();
const raycaster = new THREE.Raycaster();

const camadaMarcadores = document.createElement("div");
camadaMarcadores.className = "camada-marcadores";
camadaMarcadores.setAttribute("aria-label", "Posições demonstrativas dos locais de pouso");
container.appendChild(camadaMarcadores);

const avisoOrientacao = document.createElement("div");
avisoOrientacao.className = "aviso-orientacao";
avisoOrientacao.textContent = "Posições demonstrativas · orientação geográfica não validada";
camadaMarcadores.appendChild(avisoOrientacao);

const painelLocal = document.createElement("section");
painelLocal.className = "painel-local-visualizador";
painelLocal.setAttribute("aria-label", "Informações do local selecionado");
painelLocal.setAttribute("aria-live", "polite");
painelLocal.hidden = true;

const cabecalhoPainelLocal = document.createElement("div");
cabecalhoPainelLocal.className = "cabecalho-painel-local";

const nomePainelLocal = document.createElement("h3");
nomePainelLocal.className = "nome-painel-local";

const fecharPainelLocal = document.createElement("button");
fecharPainelLocal.type = "button";
fecharPainelLocal.className = "fechar-painel-local";
fecharPainelLocal.setAttribute("aria-label", "Fechar informações do local");
fecharPainelLocal.textContent = "×";
fecharPainelLocal.addEventListener("click", function () {
    painelLocal.hidden = true;
});

cabecalhoPainelLocal.appendChild(nomePainelLocal);
cabecalhoPainelLocal.appendChild(fecharPainelLocal);
painelLocal.appendChild(cabecalhoPainelLocal);

function criarLinhaPainelLocal(rotulo) {
    const linha = document.createElement("p");
    linha.className = "linha-painel-local";

    const nome = document.createElement("span");
    nome.className = "rotulo-painel-local";
    nome.textContent = rotulo;

    const valor = document.createElement("strong");
    valor.className = "valor-painel-local";

    linha.appendChild(nome);
    linha.appendChild(valor);
    painelLocal.appendChild(linha);

    return valor;
}

const coordenadasPainelLocal = criarLinhaPainelLocal("Coordenadas lunares");
const energiaPainelLocal = criarLinhaPainelLocal("Energia solar");
const comunicacaoPainelLocal = criarLinhaPainelLocal("Comunicação");
const avisoIndicadoresPainelLocal = document.createElement("p");
avisoIndicadoresPainelLocal.className = "aviso-indicadores-simulados";
avisoIndicadoresPainelLocal.textContent =
    "Indicadores demonstrativos · simulações, não medições científicas reais";
painelLocal.appendChild(avisoIndicadoresPainelLocal);
container.appendChild(painelLocal);

const destinoSelecionado = document.createElement("div");
destinoSelecionado.setAttribute("aria-live", "polite");
Object.assign(destinoSelecionado.style, {
    position: "absolute",
    top: "16px",
    left: "50%",
    transform: "translateX(-50%)",
    zIndex: "1",
    color: "#ffffff",
    fontSize: "16px",
    fontWeight: "600",
    textAlign: "center",
    pointerEvents: "none"
});
container.appendChild(destinoSelecionado);

const estadoCarregamento = document.createElement("div");
estadoCarregamento.setAttribute("role", "status");
estadoCarregamento.textContent = "Lua 3D carregando...";
Object.assign(estadoCarregamento.style, {
    position: "absolute",
    bottom: "16px",
    left: "50%",
    transform: "translateX(-50%)",
    zIndex: "1",
    color: "#ffffff",
    fontSize: "14px",
    textAlign: "center",
    pointerEvents: "none"
});
container.appendChild(estadoCarregamento);

const estadoIluminacaoSolar = document.createElement("div");
estadoIluminacaoSolar.className = "estado-iluminacao-solar";
estadoIluminacaoSolar.setAttribute("role", "status");
estadoIluminacaoSolar.setAttribute("aria-live", "polite");
estadoIluminacaoSolar.textContent =
    "Cálculo solar indisponível: a orientação geográfica do modelo não foi validada. " +
    "A luz atual é apenas visual, não uma direção solar calculada.";
container.appendChild(estadoIluminacaoSolar);

function formatarOffsetUTC(instante) {
    const offsetMinutos = -instante.getTimezoneOffset();
    const sinal = offsetMinutos >= 0 ? "+" : "−";
    const horas = String(Math.floor(Math.abs(offsetMinutos) / 60)).padStart(2, "0");
    const minutos = String(Math.abs(offsetMinutos) % 60).padStart(2, "0");

    return `UTC${sinal}${horas}:${minutos}`;
}

document.addEventListener("solicitacao-atualizacao-iluminacao", function (evento) {
    const data = evento.detail.data;
    const hora = evento.detail.hora;
    const fusoHorario = evento.detail.fusoHorario;

    if (!data || !hora) {
        estadoIluminacaoSolar.textContent =
            `Iluminação não calculada: falta data ou horário e a orientação do modelo não foi validada. ` +
            `A luz atual é apenas visual; o fuso informado é ${fusoHorario}.`;
        return;
    }

    const instante = new Date(`${data}T${hora}:00`);

    if (Number.isNaN(instante.getTime())) {
        estadoIluminacaoSolar.textContent =
            "Iluminação não calculada: data ou horário inválido.";
        return;
    }

    const partesData = data.split("-");
    const dataFormatada = `${partesData[2]}/${partesData[1]}/${partesData[0]}`;
    const fusoCompleto = `${fusoHorario} (${formatarOffsetUTC(instante)})`;

    estadoIluminacaoSolar.textContent =
        `Instante selecionado: ${dataFormatada} ${hora} · ${fusoCompleto}. ` +
        "Cálculo solar indisponível: a orientação geográfica do modelo não foi validada. " +
        "A luz atual é apenas visual, não uma direção solar calculada.";
});

document.addEventListener("destino-lunar-selecionado", function (evento) {
    destinoPendente = evento.detail.nome;
    destinoSelecionado.textContent = `Destino: ${destinoPendente}`;
    atualizarPainelLocal(destinoPendente);

    marcadoresLocais.forEach(function (marcador, nome) {
        const selecionado = nome === destinoPendente;
        marcador.element.classList.toggle("selecionado", selecionado);
        marcador.element.setAttribute("aria-pressed", String(selecionado));
    });

    if (lua) {
        iniciarTransicaoCamera(destinoPendente);
    }
});

function atualizarPainelLocal(nome) {
    const card = Array.from(document.querySelectorAll(".card-local")).find(
        function (item) {
            return item.querySelector("strong").textContent.trim() === nome;
        }
    );

    if (!card) {
        painelLocal.hidden = true;
        return;
    }

    function obterValorIndicador(rotulo) {
        const linha = Array.from(card.querySelectorAll(".linha-indicador")).find(
            function (item) {
                return item.firstElementChild.textContent.trim() === rotulo;
            }
        );

        return linha ? linha.lastElementChild.textContent.trim() : "";
    }

    nomePainelLocal.textContent = card.querySelector("strong").textContent.trim();
    coordenadasPainelLocal.textContent =
        card.querySelector(".coordenadas-local").textContent.trim();
    energiaPainelLocal.textContent = obterValorIndicador("Energia solar");
    comunicacaoPainelLocal.textContent = obterValorIndicador("Comunicação");
    painelLocal.hidden = false;
}

// CRIAR A CENA
const scene = new THREE.Scene();

// CRIAR A CÂMERA
const camera = new THREE.PerspectiveCamera(
    45,
    1,
    0.1,
    1000
);

camera.position.set(0, 0, 5);

// CRIAR O RENDERIZADOR
const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true
});

renderer.setPixelRatio(
    Math.min(window.devicePixelRatio, 2)
);

renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setSize(
    container.clientWidth,
    container.clientHeight
);

container.appendChild(renderer.domElement);


// ILUMINAÇÃO DA LUA

const luzAmbiente = new THREE.AmbientLight(
    0xffffff,
    0.8
);

scene.add(luzAmbiente);

const luzSolar = new THREE.DirectionalLight(
    0xffffff,
    2.5
);

luzSolar.position.set(5, 3, 5);
scene.add(luzSolar);

// CONTROLES DO MOUSE
const controls = new OrbitControls(
    camera,
    renderer.domElement
);

controls.enableDamping = false;
controls.enableZoom = true;
controls.enablePan = false;
controls.autoRotate = false;
controls.addEventListener("start", function () {
    transicaoCamera = null;
});

function obterDirecaoGeografica(coordenadas) {
    const latitude = THREE.MathUtils.degToRad(coordenadas.latitude);
    const longitude = THREE.MathUtils.degToRad(coordenadas.longitude);

    return new THREE.Vector3(
        Math.cos(latitude) * Math.cos(longitude),
        Math.sin(latitude),
        -Math.cos(latitude) * Math.sin(longitude)
    ).normalize();
}

function criarMarcadoresLocais() {
    const centroLocal = lua.worldToLocal(new THREE.Vector3(0, 0, 0));
    const centroMundo = lua.localToWorld(centroLocal.clone());

    Object.keys(coordenadasLocais).forEach(function (nome) {
        const direcaoLocal = obterDirecaoGeografica(coordenadasLocais[nome]);
        const pontoProximo = lua.localToWorld(
            centroLocal.clone().add(direcaoLocal)
        );
        const direcaoMundo = pontoProximo.sub(centroMundo).normalize();

        raycaster.set(centroMundo, direcaoMundo);
        const intersecoes = raycaster.intersectObject(lua, true);
        let posicaoLocal;

        if (intersecoes.length > 0) {
            posicaoLocal = lua.worldToLocal(intersecoes[0].point.clone());
        } else {
            posicaoLocal = centroLocal.clone().add(
                direcaoLocal.clone().multiplyScalar(raioLua / lua.scale.x)
            );
        }

        posicaoLocal.add(
            direcaoLocal.clone().multiplyScalar(0.02 / lua.scale.x)
        );

        const marcador = document.createElement("button");
        marcador.type = "button";
        marcador.className = "marcador-local";
        marcador.setAttribute("aria-label", `Selecionar ${nome} (posição demonstrativa)`);
        marcador.setAttribute("aria-pressed", "false");

        const ponto = document.createElement("span");
        ponto.className = "ponto-marcador";
        ponto.setAttribute("aria-hidden", "true");

        const rotulo = document.createElement("span");
        rotulo.className = "rotulo-marcador";
        rotulo.textContent = nome;

        marcador.appendChild(ponto);
        marcador.appendChild(rotulo);
        marcador.addEventListener("click", function () {
            document.dispatchEvent(new CustomEvent("destino-lunar-selecionado", {
                detail: { nome: nome }
            }));
        });
        camadaMarcadores.appendChild(marcador);

        marcadoresLocais.set(nome, {
            element: marcador,
            position: posicaoLocal
        });
    });

    if (destinoPendente) {
        const marcadorSelecionado = marcadoresLocais.get(destinoPendente);
        if (marcadorSelecionado) {
            marcadorSelecionado.element.classList.add("selecionado");
            marcadorSelecionado.element.setAttribute("aria-pressed", "true");
        }
    }
}

function atualizarMarcadoresLocais() {
    if (!lua || marcadoresLocais.size === 0) return;

    const largura = container.clientWidth;
    const altura = container.clientHeight;
    const candidatos = [];
    const centroMundo = lua.localToWorld(
        lua.worldToLocal(new THREE.Vector3(0, 0, 0))
    );

    marcadoresLocais.forEach(function (marcador) {
        const posicaoMundo = lua.localToWorld(marcador.position.clone());
        const normalAproximada = posicaoMundo.clone().sub(centroMundo).normalize();
        const direcaoCamera = camera.position.clone().sub(posicaoMundo).normalize();
        const posicaoTela = posicaoMundo.clone().project(camera);
        const dentroDaTela = posicaoTela.x >= -1 && posicaoTela.x <= 1 &&
            posicaoTela.y >= -1 && posicaoTela.y <= 1 &&
            posicaoTela.z >= -1 && posicaoTela.z <= 1;

        if (!dentroDaTela || normalAproximada.dot(direcaoCamera) <= 0) {
            marcador.element.hidden = true;
            return;
        }

        const direcaoRaio = posicaoMundo.clone().sub(camera.position).normalize();
        const distanciaMarcador = camera.position.distanceTo(posicaoMundo);
        raycaster.set(camera.position, direcaoRaio);
        raycaster.far = Math.max(0, distanciaMarcador - 0.01);
        const intersecoes = raycaster.intersectObject(lua, true);
        const ocultoPelaLua = intersecoes.length > 0 &&
            intersecoes[0].distance < distanciaMarcador - 0.01;

        if (ocultoPelaLua) {
            marcador.element.hidden = true;
            return;
        }

        marcador.element.hidden = false;
        candidatos.push({
            element: marcador.element,
            x: (posicaoTela.x * 0.5 + 0.5) * largura,
            y: (-posicaoTela.y * 0.5 + 0.5) * altura
        });
    });

    candidatos.sort(function (a, b) {
        return a.y - b.y;
    });

    let ultimaPosicaoY = 12;
    candidatos.forEach(function (candidato) {
        candidato.rotuloY = Math.max(candidato.y, ultimaPosicaoY);
        ultimaPosicaoY = candidato.rotuloY + 28;
    });

    const excessoInferior = ultimaPosicaoY - 28 - (altura - 12);
    if (excessoInferior > 0) {
        candidatos.forEach(function (candidato) {
            candidato.rotuloY -= excessoInferior;
        });
    }

    candidatos.forEach(function (candidato) {
        const posicaoEsquerda = Number.parseFloat(candidato.element.style.left);
        const posicaoTopo = Number.parseFloat(candidato.element.style.top);
        const deslocamentoRotulo = candidato.rotuloY - candidato.y;
        const deslocamentoAtual = Number.parseFloat(
            candidato.element.style.getPropertyValue("--deslocamento-rotulo-y")
        );

        if (!Number.isFinite(posicaoEsquerda) ||
            Math.abs(posicaoEsquerda - candidato.x) > 0.25) {
            candidato.element.style.left = `${candidato.x}px`;
        }

        if (!Number.isFinite(posicaoTopo) ||
            Math.abs(posicaoTopo - candidato.y) > 0.25) {
            candidato.element.style.top = `${candidato.y}px`;
        }

        if (!Number.isFinite(deslocamentoAtual) ||
            Math.abs(deslocamentoAtual - deslocamentoRotulo) > 0.25) {
            candidato.element.style.setProperty(
                "--deslocamento-rotulo-y",
                `${deslocamentoRotulo}px`
            );
        }
    });
}

function limitarCameraForaDaLua() {
    const raioMinimo = raioLua + Math.max(0.08, raioLua * 0.04);

    if (camera.position.length() < raioMinimo) {
        camera.position.setLength(raioMinimo);
    }
}

function iniciarTransicaoCamera(nome) {
    const coordenadas = coordenadasLocais[nome];

    if (!coordenadas) return;

    limitarCameraForaDaLua();

    const direcaoFinal = obterDirecaoGeografica(coordenadas);
    const raioAlvo = raioLua * 0.97;

    transicaoCamera = {
        inicio: performance.now(),
        duracao: 1800,
        direcaoInicial: camera.position.clone().normalize(),
        direcaoFinal: direcaoFinal,
        rotacaoDirecao: new THREE.Quaternion().setFromUnitVectors(
            camera.position.clone().normalize(),
            direcaoFinal
        ),
        raioInicial: camera.position.length(),
        raioFinal: raioLua + Math.max(0.6, raioLua * 0.45),
        alvoInicial: controls.target.clone(),
        alvoFinal: direcaoFinal.clone().multiplyScalar(raioAlvo)
    };
}

function atualizarTransicaoCamera(agora) {
    if (!transicaoCamera) return;

    const progresso = Math.min(
        (agora - transicaoCamera.inicio) / transicaoCamera.duracao,
        1
    );
    const suavizado = progresso * progresso * (3 - 2 * progresso);
    const rotacao = new THREE.Quaternion().slerp(
        transicaoCamera.rotacaoDirecao,
        suavizado
    );
    const direcao = transicaoCamera.direcaoInicial.clone()
        .applyQuaternion(rotacao)
        .normalize();
    const raio = THREE.MathUtils.lerp(
        transicaoCamera.raioInicial,
        transicaoCamera.raioFinal,
        suavizado
    );

    camera.position.copy(direcao.multiplyScalar(raio));
    controls.target.copy(transicaoCamera.alvoInicial).lerp(
        transicaoCamera.alvoFinal,
        suavizado
    );
    camera.lookAt(controls.target);

    if (progresso === 1) {
        transicaoCamera = null;
    }
}

// CARREGAR O MODELO DA NASA
const loader = new GLTFLoader();

loader.load(
    "./assets/Moon_NASA_LRO_8k_Topo.glb",


    function (gltf) {
        lua = gltf.scene;

        // CENTRALIZAR O MODELO
        const caixa = new THREE.Box3().setFromObject(lua);
        const centro = caixa.getCenter(new THREE.Vector3());
        const tamanho = caixa.getSize(new THREE.Vector3());

        lua.position.sub(centro);

        const maiorDimensao = Math.max(
            tamanho.x,
            tamanho.y,
            tamanho.z
        );

        if (maiorDimensao <= 0) {
            throw new Error("Modelo lunar sem dimensões válidas.");
        }

        // AJUSTAR O TAMANHO
        const escala = 3 / maiorDimensao;
        lua.scale.setScalar(escala);

        scene.add(lua);

        lua.updateMatrixWorld(true);
        raioLua = new THREE.Box3()
            .setFromObject(lua)
            .getBoundingSphere(new THREE.Sphere()).radius;
        criarMarcadoresLocais();

        const direcaoLocais = Object.keys(coordenadasLocais).reduce(
            function (soma, nome) {
                return soma.add(obterDirecaoGeografica(coordenadasLocais[nome]));
            },
            new THREE.Vector3()
        ).normalize();
        camera.position.copy(direcaoLocais.multiplyScalar(5));

        controls.target.set(0, 0, 0);
        controls.update();

        if (destinoPendente) {
            iniciarTransicaoCamera(destinoPendente);
        }

        estadoCarregamento.remove();
        console.log("Lua 3D carregada com sucesso!");
    },

    undefined,

    function (erro) {
        console.error("Erro ao carregar a Lua:", erro);
        estadoCarregamento.textContent = "Navegação indisponível";
        estadoCarregamento.style.color = "#ff454f";
    }
);

// AJUSTAR AO TAMANHO DA TELA
function ajustarTela() {
    const largura = container.clientWidth;
    const altura = container.clientHeight;

    if (!largura || !altura) return;

    camera.aspect = largura / altura;
    camera.updateProjectionMatrix();

    renderer.setSize(largura, altura);
}

window.addEventListener("resize", ajustarTela);
ajustarTela();

// ANIMAÇÃO DA CENA
function animar() {
    requestAnimationFrame(animar);

    controls.update();
    atualizarTransicaoCamera(performance.now());
    limitarCameraForaDaLua();
    atualizarMarcadoresLocais();
    renderer.render(scene, camera);
}

animar();
