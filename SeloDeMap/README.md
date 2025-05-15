# SeloDeMap - Validação Ambiental

Sistema web para validação ambiental de propriedades rurais usando dados do CAR e PRODES.

## Requisitos

- Docker
- Docker Compose

## Configuração

1. Clone o repositório:
```bash
git clone https://github.com/seu-usuario/SeloDeMap.git
cd SeloDeMap
```

2. Copie o arquivo de exemplo de variáveis de ambiente:
```bash
cp .env.example .env
```

3. Ajuste as variáveis no arquivo `.env` conforme necessário.

4. Crie a pasta de dados e adicione os arquivos necessários:
```bash
mkdir -p data
# Adicione os arquivos do PRODES na pasta data/
```

## Executando com Docker

1. Construa e inicie os containers:
```bash
docker-compose up --build
```

2. Acesse a aplicação em:
```
http://localhost:5000
```

## Desenvolvimento

Para desenvolvimento local sem Docker:

1. Crie um ambiente virtual:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

2. Instale as dependências:
```bash
pip install -r requirements.txt
```

3. Execute a aplicação:
```bash
python run.py
```

## Estrutura do Projeto

```
SeloDeMap/
├── app/
│   ├── __init__.py
│   ├── routes.py
│   ├── utils.py
│   └── templates/
│       └── index.html
├── data/
│   └── prodes_ms_recorte.tif
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── run.py
```

## Funcionalidades

- Consulta de propriedades por coordenadas ou código CAR
- Visualização de mapas com diferentes camadas (OpenStreetMap, Google Satellite, ESRI)
- Análise de desmatamento usando dados do PRODES
- Integração com banco de dados PostGIS para dados do CAR

## Contribuindo

1. Faça um fork do projeto
2. Crie uma branch para sua feature (`git checkout -b feature/nova-feature`)
3. Commit suas mudanças (`git commit -am 'Adiciona nova feature'`)
4. Push para a branch (`git push origin feature/nova-feature`)
5. Crie um Pull Request

## Licença

Este projeto está licenciado sob a licença MIT - veja o arquivo [LICENSE](LICENSE) para detalhes. 