"""Horizonte do terreno a partir do DEM do LOLA.

Responsabilidade (a implementar):
- Ler o DEM polar do LOLA (estereográfico polar sul) com rasterio, a partir
  de cache/ (arquivos .tif/.img não vão para o git).
- Para cada local, traçar raios em 360 azimutes (passo de 1°) e, ao longo de
  cada raio, calcular o maior ângulo de elevação do terreno visto do local:
      elev = atan2(h_ponto - h_local - queda_curvatura, distância)
  onde queda_curvatura ~ d^2 / (2 R) corrige a curvatura da Lua
  (R = 1737,4 km). Considerar também a altura do observador (ex.: antena).
- Atenção à conversão de referencial: azimute no plano tangente do local
  (a partir do Norte, horário) != direção na grade estereográfica; é preciso
  rotacionar pela longitude do local.
- Devolver horizon_deg[360] (índice = azimute em graus inteiros).
"""
