"""Métricas de energia (Sol) e comunicação direta (Terra).

Responsabilidade (a implementar):
- Regra de visibilidade do contrato:
      visível = elevação do corpo > horizon_deg[round(azimute) % 360]
- Para o Sol, considerar depois o disco solar (~0,27° de raio) para
  iluminação parcial.
- Métricas por local e período, por exemplo:
    * % do tempo com Sol visível / com Terra visível / com ambos;
    * maior período contínuo sem Sol (noite mais longa) e sem Terra;
    * janelas contínuas de iluminação/comunicação.
- Veredito verde/amarelo/vermelho a partir de limiares configuráveis.
- Funções puras sobre arrays numpy; não leem nem escrevem arquivos.
"""
