import urllib.request
import urllib.parse
import json
import logging

logger = logging.getLogger("uvicorn.error")

def geocode_address(logradouro: str, numero: str, bairro: str, cidade: str, estado: str, cep: str) -> tuple[float | None, float | None]:
    """
    Converte um endereço em coordenadas usando o Nominatim (OSM) com estratégia de fallback em cascata.
    Retorna uma tupla (latitude, longitude) ou (None, None).
    """
    if not cidade or not estado:
        return None, None
        
    # Definimos as tentativas de mais específicas para mais genéricas.
    # Evitamos incluir CEP e Bairro nas tentativas detalhadas da rua, pois o OSM brasileiro 
    # frequentemente falha se a query for excessivamente restrita.
    attempts = []
    
    if logradouro:
        # 1. Rua + Número + Cidade + Estado
        if numero:
            attempts.append([logradouro, numero, cidade, estado, "Brazil"])
        # 2. Rua + Cidade + Estado
        attempts.append([logradouro, cidade, estado, "Brazil"])
        
    if bairro:
        # 3. Bairro + Cidade + Estado
        attempts.append([bairro, cidade, estado, "Brazil"])
        
    # 4. Cidade + Estado (Último recurso)
    attempts.append([cidade, estado, "Brazil"])
    
    for parts in attempts:
        query_str = ", ".join(parts)
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
            "q": query_str,
            "format": "json",
            "limit": 1
        })
        try:
            req = urllib.request.Request(
                url, 
                headers={"User-Agent": "UMPGestaoApp/2.0 (contato@umpgestao.com.br)"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    if data and len(data) > 0:
                        lat = float(data[0]["lat"])
                        lon = float(data[0]["lon"])
                        logger.info(f"Geocodificação com sucesso para [{query_str}] -> ({lat}, {lon})")
                        return lat, lon
        except Exception as e:
            logger.error(f"Erro na geocodificação da tentativa [{query_str}]: {e}")
            
    return None, None
