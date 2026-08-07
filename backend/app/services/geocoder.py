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
        
    attempts = []
    
    # Normalizar strings
    logradouro_clean = (logradouro or "").strip()
    numero_clean = (numero or "").strip()
    bairro_clean = (bairro or "").strip()
    cidade_clean = (cidade or "").strip()
    estado_clean = (estado or "").strip()
    cep_clean = (cep or "").strip()
    
    if logradouro_clean:
        if numero_clean:
            # 1. Rua, Número, CEP, Cidade, Estado
            if cep_clean:
                attempts.append([f"{logradouro_clean}, {numero_clean}", cep_clean, cidade_clean, estado_clean, "Brazil"])
            # 2. Rua, Número, Bairro, Cidade, Estado
            if bairro_clean:
                attempts.append([f"{logradouro_clean}, {numero_clean}", bairro_clean, cidade_clean, estado_clean, "Brazil"])
            # 3. Rua, Número, Cidade, Estado
            attempts.append([f"{logradouro_clean}, {numero_clean}", cidade_clean, estado_clean, "Brazil"])
            
        # Fallbacks da rua para aproximar do segmento correto (caso o número exato falhe)
        if cep_clean:
            attempts.append([logradouro_clean, cep_clean, cidade_clean, estado_clean, "Brazil"])
        if bairro_clean:
            attempts.append([logradouro_clean, bairro_clean, cidade_clean, estado_clean, "Brazil"])
        attempts.append([logradouro_clean, cidade_clean, estado_clean, "Brazil"])
        
    if bairro_clean:
        # 7. Bairro, Cidade, Estado
        attempts.append([bairro_clean, cidade_clean, estado_clean, "Brazil"])
        
    # 8. Cidade, Estado
    attempts.append([cidade_clean, estado_clean, "Brazil"])
    
    for parts in attempts:
        query_str = ", ".join([p for p in parts if p])
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
