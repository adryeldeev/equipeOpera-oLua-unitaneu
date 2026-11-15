
const cardsLocais = document.querySelectorAll(".card-local");

const nomeSelecionado = document.getElementById(
    "nome-local-selecionado"
);

function selecionarCard(card) {
    cardsLocais.forEach(function (outroCard) {
        const selecionado = outroCard === card;
        outroCard.classList.toggle("selecionado", selecionado);
        outroCard.setAttribute("aria-pressed", String(selecionado));
    });

    nomeSelecionado.textContent = card.querySelector("strong").textContent.trim();
}

cardsLocais.forEach(function (card) {
    card.addEventListener("click", function () {
        const nome = card.querySelector("strong").textContent.trim();
        document.dispatchEvent(new CustomEvent("destino-lunar-selecionado", {
            detail: { nome: nome }
        }));
    });
});

document.addEventListener("destino-lunar-selecionado", function (evento) {
    const nome = evento.detail.nome;
    const cardSelecionado = Array.from(cardsLocais).find(function (card) {
        return card.querySelector("strong").textContent.trim() === nome;
    });

    if (cardSelecionado) {
        selecionarCard(cardSelecionado);
    }
});
