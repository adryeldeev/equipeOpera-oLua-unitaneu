# Imagem do pipeline. Contexto de build = raiz do repositório
# (ver docker-compose.yml), para que os caminhos abaixo funcionem.
FROM python:3.11-slim

WORKDIR /app

# As wheels do rasterio para Linux já trazem o GDAL embutido,
# por isso a imagem slim é suficiente.
COPY pipeline/requirements.txt /app/pipeline/requirements.txt
RUN pip install --no-cache-dir -r /app/pipeline/requirements.txt

COPY pipeline/ /app/pipeline/

# Os scripts escrevem em /app/data e /app/cache (montados via volume).
CMD ["python", "pipeline/tools/gerar_mock.py"]
