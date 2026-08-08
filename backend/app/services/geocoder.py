import urllib.request
import urllib.parse
import json
import logging

logger = logging.getLogger("uvicorn.error")

def geocode_address(logradouro: str, numero: str, bairro: str, cidade: str, estado: str, cep: str) -> tuple[float | None, float | None, str]:
    """
    Converte um endereço em coordenadas usando Nominatim (OSM) e Photon com busca estruturada.
    Retorna uma tupla (latitude, longitude, precision_level).
    precision_level: 'exato', 'aproximado_rua', 'bairro', 'cidade', 'nenhum'
    """
    if not cidade or not estado:
        return None, None, "nenhum"
        
    logradouro_clean = (logradouro or "").strip()
    numero_clean = (numero or "").strip()
    bairro_clean = (bairro or "").strip()
    cidade_clean = (cidade or "").strip()
    estado_clean = (estado or "").strip()
    cep_clean = (cep or "").strip().replace("-", "").replace(".", "")

    headers = {"User-Agent": "UMPGestaoApp/2.0 (contato@umpgestao.com.br)"}

    def determine_precision(item: dict, searched_num: str) -> str:
        addr = item.get("address", {})
        addresstype = item.get("addresstype", "")
        item_type = item.get("type", "")
        item_class = item.get("class", "")

        # Se retornou número da casa explicitamente ou é tipo construção/casa
        if addr.get("house_number") or addresstype in ["building", "house", "amenity", "shop", "office"] or item_class == "building":
            return "exato"
        
        # Se pesquisou número e o nome/exibição contém o número
        disp = item.get("display_name", "")
        if searched_num and searched_num in disp.split(",")[0]:
            return "exato"

        if addresstype == "road" or item_class == "highway" or item_type in ["residential", "pedestrian", "service", "unclassified", "primary", "secondary", "tertiary"]:
            return "aproximado_rua"
            
        if addresstype in ["suburb", "neighbourhood", "quarter"]:
            return "bairro"
            
        return "cidade"

    # ── TENTATIVA 1: Nominatim Busca Estruturada com Número ──
    if logradouro_clean:
        street_str = f"{numero_clean} {logradouro_clean}" if numero_clean else logradouro_clean
        params = {
            "street": street_str,
            "city": cidade_clean,
            "state": estado_clean,
            "country": "Brazil",
            "format": "json",
            "limit": 1,
            "addressdetails": 1
        }
        if cep_clean:
            params["postalcode"] = cep_clean

        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=4) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    if data:
                        lat = float(data[0]["lat"])
                        lon = float(data[0]["lon"])
                        prec = determine_precision(data[0], numero_clean)
                        logger.info(f"Geocodificação Estruturada -> ({lat}, {lon}) [{prec}]")
                        return lat, lon, prec
        except Exception as e:
            logger.warning(f"Erro Nominatim estruturado: {e}")

    # ── TENTATIVA 2: Photon API (Komoot OpenStreetMap Geocoder) ──
    if logradouro_clean:
        q_parts = []
        if logradouro_clean:
            q_parts.append(f"{logradouro_clean} {numero_clean}".strip())
        if bairro_clean:
            q_parts.append(bairro_clean)
        q_parts.extend([cidade_clean, estado_clean, "Brasil"])
        photon_url = "https://photon.komoot.io/api/?" + urllib.parse.urlencode({"q": ", ".join(q_parts), "limit": 1})
        try:
            req = urllib.request.Request(photon_url, headers=headers)
            with urllib.request.urlopen(req, timeout=4) as response:
                if response.status == 200:
                    pdata = json.loads(response.read().decode("utf-8"))
                    features = pdata.get("features", [])
                    if features:
                        coords = features[0]["geometry"]["coordinates"]
                        lon, lat = float(coords[0]), float(coords[1])
                        props = features[0].get("properties", {})
                        has_num = bool(props.get("housenumber"))
                        prec = "exato" if has_num else "aproximado_rua"
                        logger.info(f"Geocodificação Photon -> ({lat}, {lon}) [{prec}]")
                        return lat, lon, prec
        except Exception as e:
            logger.warning(f"Erro Photon API: {e}")

    # ── TENTATIVA 3: Nominatim Texto Livre Fallback (Rua / Bairro / Cidade) ──
    fallback_queries = []
    if logradouro_clean:
        if numero_clean:
            fallback_queries.append(f"{logradouro_clean}, {numero_clean}, {cidade_clean}, {estado_clean}, Brasil")
        fallback_queries.append(f"{logradouro_clean}, {cidade_clean}, {estado_clean}, Brasil")
    if bairro_clean:
        fallback_queries.append(f"{bairro_clean}, {cidade_clean}, {estado_clean}, Brasil")
    fallback_queries.append(f"{cidade_clean}, {estado_clean}, Brasil")

    for q_str in fallback_queries:
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
            "q": q_str,
            "format": "json",
            "limit": 1,
            "addressdetails": 1
        })
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=4) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    if data:
                        lat = float(data[0]["lat"])
                        lon = float(data[0]["lon"])
                        prec = determine_precision(data[0], numero_clean)
                        logger.info(f"Geocodificação Fallback [{q_str}] -> ({lat}, {lon}) [{prec}]")
                        return lat, lon, prec
        except Exception as e:
            logger.error(f"Erro Geocodificação Fallback [{q_str}]: {e}")

    return None, None, "nenhum"
