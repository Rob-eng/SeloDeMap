from flask import render_template, request, jsonify, current_app
from . import utils # ou from app import utils
from shapely.geometry import Point, mapping # para converter geometria para GeoJSON
import geopandas as gpd
import folium
from folium import plugins
from branca.colormap import LinearColormap
import rasterio # para bounds
import numpy as np # Para isnan

# Função auxiliar para salvar/renderizar mapa Folium
def render_map_html(m):
    return m._repr_html_()

@current_app.route('/')
def index():
    return render_template('index.html')

@current_app.route('/analisar', methods=['POST'])
def analisar():
    data = request.form
    lat, lon, car_code = None, None, None
    imovel_geom, cod_imovel_encontrado, estado_obj = None, None, None
    error_message = None

    input_type = data.get('inputType')

    if input_type == 'coords':
        try:
            lat = float(data.get('latitude'))
            lon = float(data.get('longitude'))
        except (TypeError, ValueError):
            return jsonify({"error": "Coordenadas inválidas."}), 400
        
        estado_obj, err = utils.get_estado_from_coords(lat, lon)
        if err: return jsonify({"error": f"Estado: {err}"}), 500
        if estado_obj is None: return jsonify({"error": "Não foi possível determinar o estado."}), 404

        # O objeto estado_obj é uma Series do GeoPandas
        nm_uf = estado_obj['nm_uf']
        sigla_uf = estado_obj['cd_uf'] # ou mapear de nm_uf se cd_uf não for sigla
        
        imovel_geom, cod_imovel_encontrado, err = utils.get_imovel_from_coords(lat, lon, sigla_uf)
        if err: return jsonify({"error": f"Imóvel: {err}"}), 500
        if imovel_geom is None: return jsonify({"error": "Nenhum imóvel CAR encontrado."}), 404

    elif input_type == 'car_code':
        car_code = data.get('car_code')
        # Precisamos do estado para o CAR. Você pode pedir ao usuário ou tentar inferir.
        # Por simplicidade, vamos assumir que temos uma forma de obter o estado (ex: um select no form)
        estado_sigla_form = data.get('estado_sigla_car', 'MS') # Default para MS se não fornecido

        imovel_obj, err = utils.get_imovel_from_car_code(car_code, estado_sigla_form)
        if err: return jsonify({"error": f"Imóvel: {err}"}), 500
        if imovel_obj is None: return jsonify({"error": f"Código CAR {car_code} não encontrado."}), 404
        
        imovel_geom = imovel_obj.geometry
        cod_imovel_encontrado = imovel_obj['cod_imovel']
        
        # Determinar lat/lon do centroide para o mapa
        centroid = imovel_geom.centroid
        lat, lon = centroid.y, centroid.x

        # Obter o estado para o nome e sigla
        estado_obj_car, err_est_car = utils.get_estado_from_coords(lat, lon)
        if err_est_car: return jsonify({"error": f"Estado para CAR: {err_est_car}"}), 500
        if estado_obj_car is None: return jsonify({"error": "Não foi possível determinar o estado para o CAR."}), 404
        nm_uf = estado_obj_car['nm_uf']
        sigla_uf = estado_obj_car['cd_uf'] # Ou mapear

    else:
        return jsonify({"error": "Tipo de entrada inválido."}), 400

    # --- Análise PRODES ---
    desmatamento_data_display, desmatamento_areas_ha, prodes_transform, prodes_crs, err = utils.analyze_prodes(imovel_geom, sigla_uf)
    if err:
        # Mesmo com erro no PRODES, podemos mostrar o mapa do imóvel
        print(f"Aviso PRODES: {err}") # Logar o erro
        error_message = f"Aviso PRODES: {err}" # Enviar para o frontend
        # Ainda podemos tentar gerar o mapa sem a camada PRODES

    # --- Geração do Mapa Folium ---
    map_center_lat = lat if lat else imovel_geom.centroid.y
    map_center_lon = lon if lon else imovel_geom.centroid.x
    
    m = folium.Map(
        location=[map_center_lat, map_center_lon],
        zoom_start=12,
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri World Imagery'
    )
    folium.TileLayer('openstreetmap', name='OpenStreetMap').add_to(m)

    # Coordenada/Ponto de Interesse
    if lat and lon:
        folium.Marker(
            [lat, lon],
            popup=f"Ponto de Análise<br>CAR: {cod_imovel_encontrado}",
            icon=folium.Icon(color="red")
        ).add_to(m)

    # Estado
    if estado_obj is not None: # Se input foi por coords
        folium.GeoJson(
            estado_obj.geometry.__geo_interface__,
            name=f"Estado {nm_uf}",
            style_function=lambda x: {"color": "blue", "weight": 1, "fillOpacity": 0.1}
        ).add_to(m)
    elif input_type == 'car_code' and estado_obj_car is not None: # Se input foi por CAR e estado foi encontrado
         folium.GeoJson(
            estado_obj_car.geometry.__geo_interface__,
            name=f"Estado {nm_uf}",
            style_function=lambda x: {"color": "blue", "weight": 1, "fillOpacity": 0.1}
        ).add_to(m)


    # Imóvel CAR
    if imovel_geom:
        folium.GeoJson(
            imovel_geom.__geo_interface__,
            name=f"Imóvel CAR: {cod_imovel_encontrado}",
            style_function=lambda x: {"color": "white", "weight": 2, "fillOpacity": 0.2, "fillColor": "yellow"}
        ).add_to(m)

    # Camada PRODES
    if desmatamento_data_display is not None and desmatamento_data_display.size > 0 and prodes_transform is not None:
        # Precisamos dos bounds da camada PRODES recortada no CRS do mapa (WGS84 - EPSG:4326)
        # O prodes_transform é relativo ao raster PRODES original, não necessariamente ao mapa Folium
        # Os bounds para ImageOverlay devem ser [min_lat, min_lon], [max_lat, max_lon]
        
        # Obter os bounds da geometria do imóvel (que foi usada para mascarar)
        # e converter para EPSG:4326 se necessário para o ImageOverlay
        imovel_gdf_map_crs = gpd.GeoDataFrame([{'geometry': imovel_geom}], crs="EPSG:4674") # CRS do CAR
        imovel_gdf_map_crs = imovel_gdf_map_crs.to_crs("EPSG:4326") # CRS do Folium
        map_bounds_imovel = imovel_gdf_map_crs.total_bounds # minx, miny, maxx, maxy (lon, lat, lon, lat)

        # rasterio.features.bounds(geometry) também pode ser usado se a geometria estiver no CRS do raster
        # Aqui, desmatamento_data_display é o array numpy, e prodes_transform é sua geotransformação.
        # Precisamos dos limites geográficos (lat/lon) dessa matriz para o ImageOverlay.
        
        # Obter os bounds do raster recortado no CRS original do raster
        height, width = desmatamento_data_display.shape
        # Canto superior esquerdo (lon, lat)
        ul_lon, ul_lat = prodes_transform * (0, 0)
        # Canto inferior direito (lon, lat)
        lr_lon, lr_lat = prodes_transform * (width, height)

        # Criar um GeoDataFrame temporário para os bounds do raster e reprojetar para EPSG:4326
        from shapely.geometry import box
        raster_bbox_geom = box(ul_lon, lr_lat, lr_lon, ul_lat) # minx, miny, maxx, maxy
        raster_bbox_gdf = gpd.GeoDataFrame([{'id':1, 'geometry': raster_bbox_geom}], crs=prodes_crs)
        raster_bbox_gdf_4326 = raster_bbox_gdf.to_crs("EPSG:4326")
        final_bounds_for_map = raster_bbox_gdf_4326.total_bounds # [min_lon, min_lat, max_lon, max_lat]

        # Formato para ImageOverlay: [[min_lat, min_lon], [max_lat, max_lon]]
        image_overlay_bounds = [[final_bounds_for_map[1], final_bounds_for_map[0]], [final_bounds_for_map[3], final_bounds_for_map[2]]]

        # Filtrar NaN do desmatamento_data_display se vierem do rasterio.mask (nodata pode ser NaN)
        # ImageOverlay espera float32 ou uint8. Se for outro tipo, ou tiver NaN, pode dar erro.
        # Se o nodata do raster original não for NaN, rasterio.mask o substituirá por 0 (padrão) ou o valor especificado.
        # Se desmatamento_data_display for float e puder ter NaNs:
        if np.issubdtype(desmatamento_data_display.dtype, np.floating):
            desmatamento_data_display = np.nan_to_num(desmatamento_data_display, nan=0) # Substitui NaN por 0
        
        # ImageOverlay colormap espera uma função que mapeia valores do raster para cores RGBA (0-1)
        # ou uma lista de cores se os dados forem categóricos e normalizados
        folium.raster_layers.ImageOverlay(
            image=desmatamento_data_display.astype(np.float32), # Assegurar tipo compatível
            bounds=image_overlay_bounds, # [[lat_min, lon_min], [lat_max, lon_max]]
            opacity=0.7,
            colormap=utils.prodes_colormap_folium, # Sua função de colormap adaptada
            name="Desmatamento PRODES (Recorte)"
        ).add_to(m)


    # Tabela de áreas desmatadas
    tabela_html = "<p>Nenhum desmatamento PRODES significativo encontrado para este imóvel ou dados não disponíveis.</p>"
    if desmatamento_areas_ha:
        tabela_html = """
        <div style='max-height: 200px; overflow-y: auto; border: 1px solid #ccc; padding: 5px;'>
        <b>Área Desmatada por Ano (ha)</b>
        <table border='1' style='width:100%; font-size: 0.9em;'>
        <tr><th>Ano</th><th>Área (ha)</th></tr>"""
        for year, area in sorted(desmatamento_areas_ha.items()):
            tabela_html += f"<tr><td>{year}</td><td>{area:.2f}</td></tr>"
        tabela_html += "</table></div>"
    
    # Legenda PRODES (simplificada, adapte conforme sua função colormap)
    # (A legenda do notebook era complexa; aqui uma mais simples para Folium)
    legend_html = """
     <div style='position: fixed; 
                 bottom: 50px; left: 50px; width: 180px; height: auto; 
                 border:2px solid grey; z-index:9999; font-size:12px;
                 background-color:white; opacity:0.9;'>
         <b>Legenda PRODES (Exemplo)</b><br>
         <i style="background:#FF0000; opacity:0.7;">   </i>  Desmat. Recente (0-23)<br>
         <i style="background:#FFA500; opacity:0.7;">   </i>  Desmat. Antigo (50-63)<br>
         <i style="background:#008000; opacity:0.7;">   </i>  Vegetação (100)<br>
         <i style="background:#A52A2A; opacity:0.7;">   </i>  Não Floresta (101)<br>
         <i style="background:#00BFFF; opacity:0.7;">   </i>  Hidrografia (91)<br>
         <i style="background:#D3D3D3; opacity:0.7;">   </i>  Nuvem/Outros (99, etc)<br>
     </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))


    # Controle de Camadas
    folium.LayerControl().add_to(m)

    map_html = render_map_html(m)

    resultado = {
        "map_html": map_html,
        "cod_imovel": cod_imovel_encontrado,
        "nm_uf": nm_uf,
        "sigla_uf": sigla_uf,
        "latitude": map_center_lat, # Usar o centro para o front-end se precisar
        "longitude": map_center_lon,
        "tabela_desmatamento_html": tabela_html,
        "prodes_disponivel": bool(desmatamento_areas_ha)
    }
    if error_message: # Adiciona mensagem de erro se houver problema no PRODES
        resultado["aviso_prodes"] = error_message


    return jsonify(resultado)