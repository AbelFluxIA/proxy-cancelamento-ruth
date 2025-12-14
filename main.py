import os
import httpx
import logging
from fastapi import FastAPI, HTTPException, Header, Response
from pydantic import BaseModel, Field
from typing import Union

# --- LOGGING (Para você ver o que acontece nos logs do Railway) ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ProxyLogger")

app = FastAPI(title="Clinicorp Type-Fix Proxy", version="1.1.0")

CLINICORP_URL = "https://api.clinicorp.com/rest/v1/appointment/cancel_appointment"

class AikortexPayload(BaseModel):
    # Aceita string ou int, converte para o que precisamos
    id_agendamento: Union[int, str] = Field(..., description="ID do agendamento")

@app.get("/")
async def health_check():
    return {"status": "online", "mode": "proxy_verbose"}

@app.post("/proxy/cancel")
async def cancel_appointment(
    payload: AikortexPayload,
    response: Response, # Injeção para manipular o Status Code
    x_proxy_secret: Union[str, None] = Header(default=None, alias="X-Proxy-Secret")
):
    # 1. Validação de Ambiente
    clinicorp_token = os.getenv("CLINICORP_TOKEN")
    if not clinicorp_token:
        logger.error("Token da Clinicorp não configurado.")
        raise HTTPException(status_code=500, detail="Server Error: Token not configured")

    # 2. Tratamento de Tipos (String -> Int)
    try:
        clean_id = int(payload.id_agendamento)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"O ID informado '{payload.id_agendamento}' não é um número válido.")

    # 3. Payload Destino
    dest_payload = {
        "subscriber_id": clean_id,
        "id": clean_id
    }

    headers = {
        "Accept": "application/json",
        "Authorization": clinicorp_token,
        "Content-Type": "application/json"
    }

    logger.info(f"Enviando requisicao para Clinicorp. ID: {clean_id}")

    # 4. Envio com Tratamento de Erro Robusto
    async with httpx.AsyncClient() as client:
        try:
            upstream_resp = await client.post(
                CLINICORP_URL,
                json=dest_payload,
                headers=headers,
                timeout=15.0 # Aumentei um pouco o timeout por segurança
            )
            
            # --- AQUI ESTÁ A MUDANÇA ---
            
            # 1. Espelhamos o Status Code da Clinicorp (Se der 400 lá, dá 400 aqui)
            response.status_code = upstream_resp.status_code
            
            # 2. Tentamos ler o JSON de erro original
            try:
                upstream_data = upstream_resp.json()
            except Exception:
                # Se não for JSON (ex: erro 500 do Nginx deles), devolvemos o texto cru
                logger.warning("Resposta da Clinicorp não é JSON válido.")
                upstream_data = {"raw_error": upstream_resp.text}

            # 3. Retornamos tudo para o Aikortex analisar
            return {
                "status": "completed", # Indica que o proxy rodou
                "clinicorp_status": upstream_resp.status_code,
                "error": upstream_data if upstream_resp.is_error else None, # Campo explícito de erro
                "data": upstream_data # Dados completos
            }

        except httpx.TimeoutException:
            logger.error("Timeout ao conectar na Clinicorp")
            raise HTTPException(status_code=504, detail="Erro: A Clinicorp demorou muito para responder (Gateway Timeout).")
            
        except httpx.RequestError as e:
            logger.error(f"Erro de conexão: {str(e)}")
            raise HTTPException(status_code=502, detail=f"Erro de Conexão com Clinicorp: {str(e)}")
