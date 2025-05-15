# app/routes.py
from flask import render_template, request, jsonify, current_app
from . import utils # Importa as funções de utils.py
from shapely.geometry import mapping # Para converter geometria Shapely para formato GeoJSON
import geopandas as gpd # Para manipulação de geometrias e CRS
import folium
from folium import plugins
import numpy as np
import json # Para lidar com GeoJSON

# Função auxiliar para renderizar mapa Folium como HTML string
def render_map_html(m):
    """Converte um objeto de mapa Folium para sua representação HTML."""
    return m._repr_html_()

@current_app.route('/')
def index():
    """Rota principal que renderiza a página inicial (index.html)."""
    return render_template('index.html')

@current_app.route('/analisar', methods=['POST'])
def analisar_propriedade():
    """
    Rota principal para análise. Recebe dados do formulário, processa
    e retorna um JSON com o HTML do mapa e outras informações.
    """
    data_form = request.form
    input_type = data_form.get('inputType')
    current_app.logger.info(f"Requisição de análise recebida. Tipo: {input_type}, Dados: {data_form}")

    lat, lon, car_code_input = None, None, None
    imovel_car_data, estado_data = None, None
    map_center_lat, map_center_lon = None, None
    error_message_pipeline = [] # Lista para acumular erros/avisos

    # 1. Obter Estado e Imóvel CAR com base na entrada
    # ----------------------------------------------------
    if input_type == 'coords' or input_type == 'mapselect':
        try:
            lat = float(data_form.get('latitude'))
            lon = float(data_form.get('longitude'))
            map_center_lat, map_center_lon = lat, lon
        except (TypeError, ValueError):
            return jsonify({"error": "Coordenadas inválidas fornecidas."}), 400
        
        estado_data, err_est = utils.get_estado_from_coords(lat, lon)
        if err_est:
            error_message_pipeline.append(f"Estado: {err_est}")
            # Mesmo sem estado, podemos tentar seguir se tivermos o imóvel de outra forma
            # ou podemos parar aqui dependendo da lógica desejada.
            # Por enquanto, vamos registrar e continuar se possível.
            current_app.logger.warning(f"Erro ao obter estado por coords: {err_est}")
        
        if estado_data and estado_data.get('sigla_uf'):
            imovel_car_data, err_car = utils.get_imovel_car_from_coords(lat, lon, estado_data['sigla_uf'])
            if err_car:
                error_message_pipeline.append(f"Imóvel CAR: {err_car}")
                current_app.logger.warning(f"Erro ao obter CAR por coords: {err_car}")
        else:
            # Não foi possível determinar a UF para buscar o CAR
            msg = "Não foi possível determinar a UF para buscar o imóvel CAR por coordenadas."
            error_message_pipeline.append(msg)
            current_app.logger.warning(msg)

    elif input_type == 'car_code':
        car_code_input = data_form.get('car_code')
        estado_sigla_form = data_form.get('estado_sigla_car', 'MS') # Default para MS ou o estado selecionado

        if not car_code_input:
            return jsonify({"error": "Código CAR não fornecido."}), 400
        
        imovel_car_data, err_car = utils.get_imovel_car_from_code(car_code_input, estado_sigla_form)
        if err_car:
            return jsonify({"error": f"Imóvel CAR: {err_car}"}), 500 # Erro crítico se o CAR não for encontrado
        if not imovel_car_data:
             return jsonify({"error": f"Código CAR '{car_code_input}' não encontrado para UF '{estado_sigla_form}'."}), 404

        # Se o CAR foi encontrado, pegar o centroide para o mapa e tentar obter o estado
        if imovel_car_data.get('geometry'):
            centroid = imovel_car_data['geometry'].centroid
            map_center_lat, map_center_lon = centroid.y, centroid.x
            
            estado_data, err_est = utils.get_estado_from_coords(map_center_lat, map_center_lon)
            if err_est:
                error_message_pipeline.append(f"Estado (via centroide CAR): {err_est}")
                current_app.logger.warning(f"Erro ao obter estado pelo centroide do CAR: {err_est}")
        else:
            # Se não tem geometria, não podemos centralizar o mapa ou obter estado por geo.
            # O front-end precisará de um fallback.
            error_message_pipeline.append("Imóvel CAR encontrado, mas sem geometria para definir centro do mapa.")

    else:
        return jsonify({"error": "Tipo de entrada inválido."}), 400

    # Se não conseguimos definir um centro para o mapa, usar um padrão (ex: centro do Brasil)
    if map_center_lat is None or map_center_lon is None:
        map_center_lat, map_center_lon = -15.7801, -47.9292 # Brasília
        zoom_inicial = 4
        if not imovel_car_data: # Se nem o CAR foi achado, é um erro mais sério.
             return jsonify({"error": "Não foi possível processar a requisição. Verifique os dados de entrada.", "details": error_message_pipeline}), 400
    else:
        zoom_inicial = 12 if imovel_car_data else 6 # Zoom maior se tiver imóvel

    # 2. Preparar dados para o mapa Folium
    # -------------------------------------
    m = folium.Map(
        location=[map_center_lat, map_center_lon],
        zoom_start=zoom_inicial,
        tiles='https_server.arcgisonline.com_ArcGIS_rest_services_World_Imagery_MapServer_tile_{z}_{y}_{x}'.replace('_', '/'), # Corrigido
        attr='Esri World Imagery'
    )
    folium.TileLayer('openstreetmap', name='OpenStreetMap').add_to(m)

    # Adicionar marcador do ponto de interesse/centroide
    if lat and lon and (input_type == 'coords' or input_type == 'mapselect'):
        popup_texto = f"Coordenada Analisada<br>Lat: {lat:.5f}, Lon: {lon:.5f}"
        if imovel_car_data and imovel_car_data.get('cod_imovel'):
            popup_texto += f"<br>CAR: {imovel_car_data['cod_imovel']}"
        folium.Marker(
            [lat, lon],
            popup=popup_texto,
            icon=folium.Icon(color="red", icon="info-sign")
        ).add_to(m)
    elif map_center_lat and map_center_lon and input_type == 'car_code': # Ponto do centroide do CAR
        popup_texto = f"Centroide do Imóvel<br>CAR: {imovel_car_data['cod_imovel']}"
        folium.Marker(
            [map_center_lat, map_center_lon],
            popup=popup_texto,
            icon=folium.Icon(color="blue", icon="home")
        ).add_to(m)


    # Adicionar camada do Estado (se disponível)
    if estado_data and estado_data.get('geometry'):
        # A geometria do IBGE WFS já vem como objeto Shapely (via GeoPandas)
        # e o CRS é EPSG:4326, que o Folium entende.
        folium.GeoJson(
            estado_data['geometry'].__geo_interface__, # Converte Shapely para dict GeoJSON
            name=f"Estado: {estado_data.get('nome_uf', 'N/D')}",
            style_function=lambda x: {"color": "blue", "weight": 1.5, "fillOpacity": 0.1, "fillColor": "lightblue"}
        ).add_to(m)

    # Adicionar camada do Imóvel CAR (se disponível)
    if imovel_car_data and imovel_car_data.get('geometry'):
        # A geometria do CAR do PostGIS (via utils.py) está como objeto Shapely.
        # O CRS original é EPSG:4674. Folium espera EPSG:4326 (WGS84).
        # Precisamos reprojetar.
        imovel_geom_shapely = imovel_car_data['geometry']
        imovel_gdf = gpd.GeoDataFrame([{'id':1, 'geometry': imovel_geom_shapely}], crs="EPSG:4674")
        imovel_gdf_4326 = imovel_gdf.to_crs("EPSG:4326")
        
        folium.GeoJson(
            imovel_gdf_4326.geometry.iloc[0].__geo_interface__,
            name=f"Imóvel CAR: {imovel_car_data.get('cod_imovel', 'N/D')}",
            style_function=lambda x: {"color": "yellow", "weight": 2.5, "fillOpacity": 0.2, "fillColor": "yellow"}
        ).add_to(m)

    # 3. Análise PRODES (se o imóvel CAR foi encontrado)
    # -------------------------------------------------
    desmatamento_data_display, desmatamento_areas_ha, prodes_transform, prodes_crs, err_prodes = None, {}, None, None, None
    if imovel_car_data and imovel_car_data.get('geometry'):
        desmatamento_data_display, desmatamento_areas_ha, prodes_transform, prodes_crs, err_prodes = \
            utils.analyze_prodes_recorter(imovel_car_data['geometry'])
        
        if err_prodes:
            error_message_pipeline.append(f"PRODES: {err_prodes}")
            current_app.logger.warning(f"Erro/Aviso na análise PRODES: {err_prodes}")

        if desmatamento_data_display is not None and desmatamento_data_display.size > 0 and prodes_transform is not None:
            # Obter os bounds do raster recortado NO CRS DO RASTER
            height_raster, width_raster = desmatamento_data_display.shape[-2:] # Últimas duas dimensões são altura e largura

            # Cantos do raster no seu CRS original (prodes_crs)
            ul_raster_x, ul_raster_y = prodes_transform * (0, 0)
            lr_raster_x, lr_raster_y = prodes_transform * (width_raster, height_raster)

            # Criar um GeoDataFrame para a bounding box do raster e reprojetar para EPSG:4326 para o Folium
            from shapely.geometry import box
            raster_bbox_geom_original_crs = box(ul_raster_x, lr_raster_y, lr_raster_x, ul_raster_y) # minx, miny, maxx, maxy
            raster_bbox_gdf = gpd.GeoDataFrame([{'id':1, 'geometry': raster_bbox_geom_original_crs}], crs=prodes_crs)
            raster_bbox_gdf_4326 = raster_bbox_gdf.to_crs("EPSG:4326")
            
            # Bounds para ImageOverlay: [[min_lat, min_lon], [max_lat, max_lon]]
            # total_bounds retorna (minx, miny, maxx, maxy) que é (min_lon, min_lat, max_lon, max_lat) para EPSG:4326
            bounds_4326 = raster_bbox_gdf_4326.total_bounds
            image_overlay_bounds = [[bounds_4326[1], bounds_4326[0]], [bounds_4326[3], bounds_4326[2]]]
            
            # Garantir que desmatamento_data_display é float32 ou uint8 e não tem NaNs problemáticos
            # Se o nodata do PRODES (ex: 255) foi usado no mask, ele estará no array.
            # O colormap precisa lidar com esse valor de nodata.
            # Se houver NaNs reais, ImageOverlay pode falhar.
            if np.issubdtype(desmatamento_data_display.dtype, np.floating) and np.isnan(desmatamento_data_display).any():
                current_app.logger.info("Substituindo NaNs no raster PRODES por 0 para ImageOverlay.")
                desmatamento_data_display = np.nan_to_num(desmatamento_data_display, nan=0) # Substitui NaN por 0 (ou outro valor de nodata que seu colormap trate)
            
            # ImageOverlay espera uma matriz 2D (altura, largura) ou 3D (altura, largura, bandas)
            # Nosso desmatamento_data_display já é 2D (vindo da banda 0 do mask)
            if desmatamento_data_display.ndim == 2:
                 folium.raster_layers.ImageOverlay(
                    image=desmatamento_data_display.astype(np.float32), # Assegurar tipo compatível
                    bounds=image_overlay_bounds,
                    opacity=0.7,
                    colormap=utils.prodes_colormap_folium, # Sua função de colormap
                    name="Desmatamento PRODES (Recorte)"
                ).add_to(m)
            else:
                current_app.logger.warning(f"Raster PRODES para ImageOverlay não é 2D. Shape: {desmatamento_data_display.shape}")


    # Tabela de áreas desmatadas PRODES
    tabela_desmatamento_html = "<p>Análise PRODES não disponível ou nenhum desmatamento detectado no recorte.</p>"
    if desmatamento_areas_ha:
        tabela_desmatamento_html = """
        <div style='max-height: 200px; overflow-y: auto; border: 1px solid #ccc; padding: 5px; margin-top:10px;'>
        <b>Área Desmatada por Ano (ha) - PRODES Recorte</b>
        <table border='1' style='width:100%; font-size: 0.9em; border-collapse: collapse;'>
        <thead><tr><th style='padding:2px;'>Ano</th><th style='padding:2px;'>Área (ha)</th></tr></thead><tbody>"""
        for year, area in sorted(desmatamento_areas_ha.items()):
            tabela_desmatamento_html += f"<tr><td style='padding:2px;'>{year}</td><td style='padding:2px;'>{area:.2f}</td></tr>"
        tabela_desmatamento_html += "</tbody></table></div>"
    
    # Legenda PRODES (simplificada)
    legend_html_prodes = """
     <div style='position: fixed; bottom: 10px; left: 10px; width: auto; max-width:180px;
                 border:2px solid grey; z-index:9999; font-size:10px;
                 background-color:white; opacity:0.85; padding: 5px;'>
       <b>Legenda PRODES (Recorte - Exemplo)</b><br>
       <i style="background:#FFFE00; opacity:0.7;">   </i>  Desmat. Recente (Ex: 2023)<br>
       <i style="background:#FF0000; opacity:0.7;">   </i>  Desmat. Antigo (Ex: 2008)<br>
       <i style="background:#008000; opacity:0.7;">   </i>  Vegetação Nativa<br>
       <i style="background:#A52A2A; opacity:0.7;">   </i>  Não Floresta<br>
       <i style="background:#00BFFF; opacity:0.7;">   </i>  Hidrografia<br>
       <i style="background:#D3D3D3; opacity:0.7;">   </i>  Nuvem / Outros<br>
     </div>
    """
    if desmatamento_data_display is not None and desmatamento_data_display.size > 0: # Só adiciona legenda se tiver camada PRODES
        m.get_root().html.add_child(folium.Element(legend_html_prodes))


    # Adicionar Controle de Camadas
    folium.LayerControl().add_to(m)
    map_html_content = render_map_html(m)

    # Montar o resultado JSON
    resultado_final = {
        "map_html": map_html_content,
        "cod_imovel_encontrado": imovel_car_data.get('cod_imovel') if imovel_car_data else "N/D",
        "nome_uf_encontrado": estado_data.get('nome_uf') if estado_data else "N/D",
        "sigla_uf_encontrada": estado_data.get('sigla_uf') if estado_data else "N/D",
        "centro_mapa": {"lat": map_center_lat, "lon": map_center_lon},
        "tabela_desmatamento_html": tabela_desmatamento_html,
        "prodes_disponivel": bool(desmatamento_areas_ha),
        "avisos_erros": error_message_pipeline if error_message_pipeline else None
    }
    
    current_app.logger.info(f"Análise concluída. Enviando resposta.")
    return jsonify(resultado_final)