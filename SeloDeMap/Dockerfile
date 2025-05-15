FROM python:3.11-slim

# Instalar dependências do sistema necessárias para GDAL, rasterio e psycopg2
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Configurar variáveis de ambiente para GDAL
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Criar diretório da aplicação
WORKDIR /app

# Copiar requirements primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o resto do código
COPY . .

# Expor a porta que o Flask vai usar
EXPOSE 5000

# Comando para iniciar a aplicação
CMD ["python", "run.py"] 