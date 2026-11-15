# Imagem da API + site. Contexto de build = raiz do repositório.
#   docker build -f api/Dockerfile -t landerbnb .
#   docker run -p 8001:8001 landerbnb      ->  http://localhost:8001/
# Serve para hospedar (Render, Railway, Fly.io...): um container só com a API
# e o front (web/). Os kernels (~45 MB) são baixados para cache/ no 1º startup;
# sem rede, a API segue no plano B com data/sky (2027).
FROM python:3.11-slim

WORKDIR /app

COPY pipeline/requirements.txt /app/pipeline/requirements.txt
COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

COPY pipeline/ /app/pipeline/
COPY api/ /app/api/
COPY web/ /app/web/
COPY data/ /app/data/
RUN mkdir -p /app/cache

# A maioria dos serviços define a porta em $PORT; localmente usa 8001.
ENV PORT=8001
EXPOSE 8001
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
