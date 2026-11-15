# Imagem da API. Contexto de build = raiz do repositório (ver docker-compose.yml).
FROM python:3.11-slim

WORKDIR /app

COPY pipeline/requirements.txt /app/pipeline/requirements.txt
COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

COPY pipeline/ /app/pipeline/
COPY api/ /app/api/

# data/ (somente leitura) e cache/ (kernels; baixados no 1º startup) vêm por volume.
EXPOSE 8001
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8001"]
