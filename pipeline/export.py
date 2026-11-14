"""Exportação para data/ (o contrato com o frontend).

Responsabilidade (a implementar):
- Escrever, seguindo exatamente o contrato de dados:
    data/sites.json             lista de {id, name, lat, lon, category, mission}
    data/horizon/<id>.json      {site, az_step_deg, horizon_deg[360]}
    data/sky/<id>.json          {site, start, step_min,
                                 sun:{az[], el[]}, earth:{az[], el[]}}
- start em ISO 8601 UTC ("2027-01-01T00:00:00Z"); ângulos em graus,
  arredondados (ex.: 2 casas) para manter os arquivos pequenos.
- É o ÚNICO módulo que escreve em data/. O frontend só lê.
"""
