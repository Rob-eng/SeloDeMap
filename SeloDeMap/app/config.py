import os

class Config:
    # Configurações do Banco de Dados PostGIS na VPS
    POSTGRES_HOST = os.environ.get('POSTGRES_HOST', '191.252.102.219')
    POSTGRES_PORT = os.environ.get('POSTGRES_PORT', '5432')
    POSTGRES_USER = os.environ.get('POSTGRES_USER', 'selodemapuser')
    # ATENÇÃO: Nunca coloque senhas diretamente no código em produção!
    # Use variáveis de ambiente. Para desenvolvimento local, pode ser assim temporariamente.
    POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD', 'Robson@1000') # Sua senha
    POSTGRES_DB = os.environ.get('POSTGRES_DB', 'selodemapdb')

    # String de conexão para psycopg2 (se não for usar SQLAlchemy)
    DATABASE_CONNECTION_INFO = {
        'host': POSTGRES_HOST,
        'port': POSTGRES_PORT,
        'user': POSTGRES_USER,
        'password': POSTGRES_PASSWORD,
        'dbname': POSTGRES_DB
    }

    # Caminho para a pasta de dados locais (para o PRODES.tif, por exemplo)
    # __file__ é o caminho deste arquivo (config.py)
    # os.path.dirname(__file__) é a pasta 'app'
    # os.path.join(..., '..', 'dados') sobe um nível e entra em 'dados'
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DADOS_PATH = os.path.join(BASE_DIR, '..', 'dados')
    PRODES_FILE_MS_RECORTE = os.path.join(DADOS_PATH, 'prodes_desmatamento.tif') # Nome do seu recorte
    # Adicione outros caminhos de arquivos de dados se necessário