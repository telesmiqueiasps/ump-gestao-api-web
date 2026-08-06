import urllib.request
import urllib.parse
import json
import logging

logger = logging.getLogger("uvicorn.error")

def geocode_address(logradouro: str, numero: str, bairro: str, cidade: str, estado: str, cep: str) -> tuple[float | None, float | None]:
    """
    Converte um endereço textual em coordenadas de Latitude e Longitude usando a API pública e gratuita do Nominatim (OSM).
    Retorna uma tupla (latitude, longitude) ou (None, None) em caso de erro/não encontrado.
    """
    if not logradouro or not cidade or not estado:
        return None, None
        
    # Limpa o CEP para formatação da busca
    clean_cep = str(cep).replace("-", "").strip() if cep else ""
    
    # Constrói o texto de busca do endereço. 
    # Nominatim funciona melhor se o endereço for estruturado de forma legível.
    address_parts = []
    if logradouro:
        address_parts.append(f"{logradouro}")
    if numero:
        address_parts.append(f"{numero}")
    if bairro:
        address_parts.append(f"{bairro}")
    if cidade:
        address_parts.append(f"{cidade}")
    if estado:
        address_parts.append(f"{estado}")
    if clean_cep:
        address_parts.append(f"{clean_cep}")
    address_parts.append("Brazil")
    
    query_str = ", ".join(address_parts)
    
    # Codifica a URL de forma segura
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": query_str,
        "format": "json",
        "limit": 1
    })
    
    try:
        # IMPORTANTE: Nominatim requer um User-Agent descritivo e único
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "UMPGestaoApp/2.0 (contato@umpgestao.com.br)"}
        )
        
        # Define um timeout curto para não travar a requisição da API principal do sistema
        with urllib.request.urlopen(req, timeout=6) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                if data and len(data) > 0:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    logger.info(f"Geocodificação com sucesso para [{query_str}] -> ({lat}, {lon})")
                    return lat, lon
                else:
                    # Se não encontrou com o número do endereço, tenta buscar sem o número (apenas rua, bairro, cidade, estado)
                    if numero:
                        logger.info(f"Endereço exato não encontrado. Tentando geocodificar sem o número: {logradouro}")
                        return geocode_address(logradouro, "", bairro, cidade, estado, cep)
                    logger.warning(f"Nenhum resultado de geolocalização encontrado para: {query_str}")
    except Exception as e:
        logger.error(f"Erro na geocodificação do endereço [{query_str}]: {e}")
        
    return None, None
