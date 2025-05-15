# SeloDeMap/app/utils.py
import psycopg2
from psycopg2.extras import RealDictCursor
from shapely.io import from_wkb # Para Shapely 2.x
from shapely.geometry import Point
from flask import current_app
import geopandas as gpd
from owslib.wfs import WebFeatureService
import rasterio
from rasterio.mask import mask
import numpy as np
import os

# Mapeamento de código IBGE da UF para Sigla
IBGE_UF_CODE_TO_SIGLA = {
    '11': 'RO', '12': 'AC', '13': 'AM', '14': 'RR', '15': 'PA', '16': 'AP', '17': 'TO',
    '21': 'MA', '22': 'PI', '23': 'CE', '24': 'RN', '25': 'PB', '26': 'PE', '27': 'AL', '28': 'SE', '29': 'BA',
    '31': 'MG', '32': 'ES', '33': 'RJ', '35': 'SP',
    '41': 'PR', '42': 'SC', '43': 'RS',
    '50': 'MS', '51': 'MT', '52': 'GO', '53': 'DF'
}

# --- Funções de Conexão com Banco de Dados ---
def get_db_connection():
    db_info = current_app.config['DATABASE_CONNECTION_INFO']
    conn = psycopg2.connect(
        host=db_info['host'],
        database=db_info['dbname'],
        user=db_info['user'],
        password=db_info['password'],
        port=db_info['port']
    )
    return conn

# --- Funções de Consulta ao IBGE (WFS) ---
def get_estado_from_coords(lat, lon):
    ponto = Point(lon, lat)
    wfs_url = "https://geoservicos.ibge.gov.br/geoserver/CGMAT/wfs"
    layer_estado = "CGMAT:pbqg22_02_Estado_LimUF"

    try:
        wfs = WebFeatureService(wfs_url, version='1.1.0')
        bbox_estado = (lon - 0.5, lat - 0.5, lon + 0.5, lat + 0.5)
        # Solicitar no CRS nativo do WFS (EPSG:4674)
        response_estado = wfs.getfeature(typename=layer_estado, bbox=bbox_estado, outputFormat='application/json', srsname='urn:ogc:def:crs:EPSG::4674')
        
        estados_gdf = gpd.read_file(response_estado) # Estará em EPSG:4674
        if estados_gdf.empty:
            return None, "Nenhum estado encontrado na área da coordenada (WFS IBGE)."

        ponto_gdf_4326 = gpd.GeoDataFrame([{'geometry': ponto}], crs="EPSG:4326")
        ponto_gdf_4674 = ponto_gdf_4326.to_crs(estados_gdf.crs) # Reprojeta ponto para CRS dos estados
        ponto_reprojetado = ponto_gdf_4674.geometry.iloc[0]

        estado_filtrado_gdf = estados_gdf[estados_gdf.contains(ponto_reprojetado)]
        if estado_filtrado_gdf.empty:
            return None, "Coordenada fora dos limites dos estados brasileiros (WFS IBGE)."

        estado_series = estado_filtrado_gdf.iloc[0]
        codigo_uf_ibge = str(estado_series.get('cd_uf', '')) # Garantir que é string
        sigla_uf_mapeada = IBGE_UF_CODE_TO_SIGLA.get(codigo_uf_ibge)

        if not sigla_uf_mapeada:
            current_app.logger.warning(f"Código UF IBGE '{codigo_uf_ibge}' não encontrado no mapeamento.")
            return None, f"Mapeamento para sigla da UF não encontrado para o código IBGE '{codigo_uf_ibge}'."

        estado_info = {
            'gid_ibge': estado_series.get('id', None),
            'sigla_uf': sigla_uf_mapeada,
            'codigo_ibge_uf': codigo_uf_ibge,
            'nome_uf': estado_series.get('nm_uf', None),
            'geometry': estado_series.geometry # Geometria Shapely em EPSG:4674
        }
        return estado_info, None
    except Exception as e:
        current_app.logger.error(f"Erro ao consultar WFS do IBGE para estados: {e}", exc_info=True)
        return None, f"Erro ao conectar ou consultar serviço do IBGE para estados: {str(e)}"

# --- Funções de Consulta ao CAR (PostGIS) ---
def _process_car_record(imovel_record, conn, table_name):
    """Função auxiliar para processar um registro de imóvel do banco."""
    geom_wkb_data = imovel_record['geom_wkb']

    # Log detalhado do tipo e valor de geom_wkb_data
    temp_cursor = conn.cursor()
    temp_cursor.execute("SHOW bytea_output;")
    bytea_output_setting = temp_cursor.fetchone()[0]
    temp_cursor.close()
    current_app.logger.info(f"PostgreSQL bytea_output setting: {bytea_output_setting}")
    current_app.logger.info(f"Tipo original de geom_wkb_data: {type(geom_wkb_data)}")

    log_value_str = ""
    if isinstance(geom_wkb_data, (bytes, bytearray, memoryview)):
        log_value_str = geom_wkb_data[:100].hex() if hasattr(geom_wkb_data, 'hex') else str(geom_wkb_data[:100])
    else:
        log_value_str = str(geom_wkb_data)[:200]
    current_app.logger.info(f"Valor de geom_wkb_data (início, hex se bytes, ou str): {log_value_str}")

    geom_bytes = None
    if isinstance(geom_wkb_data, str):
        try:
            geom_bytes = bytes.fromhex(geom_wkb_data)
            current_app.logger.info("geom_wkb_data foi TRATADO como string hex e decodificado para bytes.")
        except ValueError as ve_hex:
            current_app.logger.error(f"Falha ao decodificar geom_wkb_data de string hex: {ve_hex}. Valor: {geom_wkb_data[:200]}")
            return None, f"Formato WKB inválido (string não hexadecimal): {str(ve_hex)}"
    elif isinstance(geom_wkb_data, memoryview):
        geom_bytes = geom_wkb_data.tobytes()
        current_app.logger.info("geom_wkb_data era memoryview e foi convertido para bytes.")
    elif isinstance(geom_wkb_data, (bytes, bytearray)):
        geom_bytes = bytes(geom_wkb_data) # Garante que é um objeto bytes imutável
        current_app.logger.info("geom_wkb_data JÁ ERA bytes/bytearray e foi assegurado como bytes.")
    else:
        current_app.logger.error(f"Tipo inesperado para geom_wkb_data: {type(geom_wkb_data)}")
        return None, f"Tipo de dados WKB inesperado: {type(geom_wkb_data)}"

    if geom_bytes:
        try:
            current_app.logger.info(f"Tentando from_wkb() com bytes (início, hex): {geom_bytes[:50].hex()}")
            geom_shapely = from_wkb(geom_bytes)
            current_app.logger.info("from_wkb() bem-sucedido!")
            
            imovel_data = {
                'gid_car': imovel_record['id'],
                'cod_imovel': imovel_record['cod_imovel'],
                'municipio': imovel_record.get('municipio'),
                'area_ha_car': imovel_record.get('area'),
                'geometry': geom_shapely
            }
            return imovel_data, None
        except Exception as e_shapely:
            current_app.logger.error(f"Erro no from_wkb(): {e_shapely}", exc_info=True)
            hex_bytes_inicio = geom_bytes[:50].hex()
            current_app.logger.error(f"Bytes (hex) que causaram o erro no from_wkb (início dos primeiros 50 bytes): {hex_bytes_inicio}")
            try:
                reason_cursor = conn.cursor()
                reason_cursor.execute(f"SELECT ST_IsValidReason(geom) FROM {table_name} WHERE id = %s;", (imovel_record['id'],))
                validity_reason = reason_cursor.fetchone()[0]
                reason_cursor.close()
                current_app.logger.error(f"Razão da validade da geometria (ID: {imovel_record['id']}): {validity_reason}")
            except Exception as e_validity:
                current_app.logger.error(f"Erro ao verificar validade da geometria: {e_validity}")
            return None, f"Erro ao parsear geometria WKB: {str(e_shapely)}"
    else:
        current_app.logger.error("geom_bytes está None após processamento.")
        return None, "Falha interna ao processar dados da geometria."


def get_imovel_car_from_coords(lat, lon, sigla_uf):
    if not sigla_uf:
        return None, "Sigla da UF não fornecida para buscar imóvel CAR."
    table_name = f"imoveis_car_{sigla_uf.lower()}"
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Usar ST_AsEWKB para incluir SRID, e selecionar mais colunas
        query = f"""
            SELECT id, cod_imovel, municipio, area, ST_AsBinary(geom) as geom_wkb
            FROM {table_name}
            WHERE ST_Contains(geom, ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), ST_SRID(geom)));
        """ # ST_SRID(geom) para usar o SRID da coluna geom dinamicamente
        cursor.execute(query, (lon, lat))
        imovel_record = cursor.fetchone()
        if imovel_record:
            return _process_car_record(imovel_record, conn, table_name)
        else:
            return None, f"Nenhum imóvel CAR encontrado para a coordenada na tabela {table_name}."
    except psycopg2.Error as e:
        if e.pgcode == '42P01':
             current_app.logger.error(f"Tabela CAR '{table_name}' não encontrada: {e}")
             return None, f"Dados CAR para a UF '{sigla_uf}' não disponíveis ou tabela não encontrada."
        current_app.logger.error(f"Erro DB (coords): {e}", exc_info=True)
        return None, f"Erro no banco de dados (coords): {str(e)}"
    finally:
        if conn:
            conn.close()

def get_imovel_car_from_code(cod_car, sigla_uf):
    if not sigla_uf:
        return None, "Sigla da UF não fornecida para buscar imóvel CAR."
    table_name = f"imoveis_car_{sigla_uf.lower()}"
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Usar ST_AsEWKB e selecionar mais colunas
        query = f"""
            SELECT id, cod_imovel, municipio, area, ST_AsBinary(geom) as geom_wkb
            FROM {table_name}
            WHERE cod_imovel = %s;
        """
        cursor.execute(query, (cod_car,))
        imovel_record = cursor.fetchone()
        if imovel_record:
            return _process_car_record(imovel_record, conn, table_name)
        else:
            return None, f"Código CAR '{cod_car}' não encontrado na tabela {table_name}."
    except psycopg2.Error as e:
        if e.pgcode == '42P01':
             current_app.logger.error(f"Tabela CAR '{table_name}' não encontrada: {e}")
             return None, f"Dados CAR para a UF '{sigla_uf}' não disponíveis ou tabela não encontrada."
        current_app.logger.error(f"Erro DB (code): {e}", exc_info=True)
        return None, f"Erro no banco de dados (code): {str(e)}"
    finally:
        if conn:
            conn.close()


# --- Funções de Análise PRODES (usando arquivo local por enquanto) ---
def analyze_prodes_recorter(imovel_geometry_shapely):
    prodes_filepath = current_app.config['PRODES_FILE_MS_RECORTE']
    if not os.path.exists(prodes_filepath):
        current_app.logger.error(f"Arquivo PRODES de recorte não encontrado: {prodes_filepath}")
        return None, {}, None, None, f"Arquivo PRODES de recorte não encontrado."
    if not imovel_geometry_shapely or not imovel_geometry_shapely.is_valid:
        return None, {}, None, None, "Geometria do imóvel inválida para análise PRODES."

    try:
        with rasterio.open(prodes_filepath) as src_prodes:
            # Sabemos que os dados do CAR estão em EPSG:4674
            imovel_gdf = gpd.GeoDataFrame([{'id': 1, 'geometry': imovel_geometry_shapely}], crs="EPSG:4674")
            
            if imovel_gdf.crs != src_prodes.crs:
                current_app.logger.info(f"Reprojetando geometria do imóvel de {imovel_gdf.crs} para CRS do PRODES {src_prodes.crs}")
                imovel_gdf_reproj = imovel_gdf.to_crs(src_prodes.crs)
            else:
                imovel_gdf_reproj = imovel_gdf
            
            geometria_para_mascara = [geom for geom in imovel_gdf_reproj.geometry]
            try:
                out_image, out_transform = mask(src_prodes, geometria_para_mascara, crop=True, all_touched=True, nodata=255)
            except ValueError as ve:
                 if "Input shapes do not overlap raster." in str(ve):
                     current_app.logger.info("Imóvel CAR fora da área do raster PRODES de recorte.")
                     return np.array([[]]), {}, None, src_prodes.crs, "Imóvel fora da área do raster PRODES de recorte."
                 else: raise ve
            if out_image.size == 0 or np.all(out_image == 255):
                return np.array([[]]), {}, out_transform, src_prodes.crs, "Nenhuma área PRODES válida no recorte."

            desmatamento_values_2d = out_image[0]
            pixel_area_m2 = 900 # Aproximação para PRODES (pixels de 30m x 30m)
            if not src_prodes.crs.is_geographic: # Se CRS for projetado, calcular área do pixel
                pixel_size_x = out_transform[0]
                pixel_size_y = abs(out_transform[4])
                pixel_area_m2 = pixel_size_x * pixel_size_y
            
            desmatamento_areas_ha = {}
            def get_prodes_year_from_value(value):
                value = int(value)  # Converte para int Python padrão
                if 1 <= value <= 23:
                    return 2000 + value
                return None

            # Converte para array int padrão do Python antes de processar
            values_array = desmatamento_values_2d[desmatamento_values_2d != 255].astype(np.int32)
            unique_values, counts = np.unique(values_array, return_counts=True)
            
            for value, count in zip(unique_values, counts):
                year = get_prodes_year_from_value(value)
                if year and pixel_area_m2 > 0:
                    area_ha = (float(count) * pixel_area_m2) / 10000  # Converte explicitamente para float
                    if area_ha > 0.001:
                        desmatamento_areas_ha[year] = desmatamento_areas_ha.get(year, 0) + area_ha
            
            return desmatamento_values_2d, desmatamento_areas_ha, out_transform, src_prodes.crs, None
    except Exception as e:
        current_app.logger.error(f"Erro na análise PRODES (recorte): {e}", exc_info=True)
        return None, {}, None, None, f"Erro ao processar imagem PRODES: {str(e)}"

# --- Função de Colormap para Folium (PRODES) ---
def prodes_colormap_folium(value):
    """Mapeia valores do raster PRODES para cores RGBA (0-1) para Folium."""
    # Desmatamento recente (2000-2023): Amarelo para Vermelho
    if 1 <= value <= 23:
        scale = (value - 1) / 22  # 22 é o range (23-1)
        r = 255
        g = int(255 * (1 - scale))
        b = 0
        return (r / 255, g / 255, b / 255, 0.7)
    
    # Classes especiais
    elif value == 100:  # Vegetação Nativa
        return (0, 0.5, 0, 0.7)  # Verde escuro
    elif value == 101:  # Não Floresta
        return (0.65, 0.16, 0.16, 0.7)  # Marrom
    elif value == 91:   # Hidrografia
        return (0, 0.75, 1, 0.7)  # Azul claro
    elif value == 99:   # Nuvem
        return (0.83, 0.83, 0.83, 0.7)  # Cinza claro
    elif value == 255:  # NoData
        return (0, 0, 0, 0)  # Transparente
    else:
        return (0, 0, 0, 0)  # Transparente para outros valores