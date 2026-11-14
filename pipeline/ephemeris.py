"""Efemérides: posição do Sol e da Terra vistos de um local na Lua.

Responsabilidade (a implementar):
- Carregar os kernels JPL (DE440 + orientação lunar, ex.: moon_pa_de440 /
  frame MOON_ME) a partir de cache/; nunca baixar em tempo de execução
  sem pedido explícito.
- Para cada local (lat, lon com longitude LESTE positiva) e cada instante
  de uma série temporal UTC, calcular azimute e elevação TOPOCÊNTRICOS do
  Sol e da Terra:
    * converter lat/lon do local para um vetor no frame fixo da Lua
      (MOON_ME), sobre a esfera de referência (R = 1737,4 km);
    * obter o vetor local -> corpo no mesmo frame;
    * projetar no sistema local ENU (Leste, Norte, Zênite) do local;
    * azimute = medido a partir do Norte, sentido horário (0..360);
      elevação = ângulo acima do plano tangente (sem relevo).
- Devolver arrays numpy; não sabe nada de JSON nem do frontend.

Validação: comparar alguns instantes com a API Horizons (JPL), via
requests, fora do fluxo normal.
"""
