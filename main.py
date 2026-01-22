import os
import httpx
import logging
from fastapi import FastAPI, HTTPException, Header, Response
from pydantic import BaseModel, Field
from typing import Union

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ProxyLogger")

app = FastAPI(title="Clinicorp Type-Fix Proxy", version="1.2.0")

CLINICORP_URL = "https://api.clinicorp.com/rest/v1/appointment/cancel_appointment"

# --- MODELO DE DADOS CORRIGIDO ---
# Agora reflete exatamente o JSON que o Aikortex envia
class AikortexPayload(BaseModel):
    subscriber_id: Union[int, str] = Field(..., description="ID ou Slug da Clínica (ex: odontomaria)")
    id: Union[int, str] = Field(..., description="ID do Agendamento (vem como string, sai como int)")

@app.get("/")
async def health_check():
    return {"status": "online", "mode": "proxy_verbose"}

@app.post("/proxy/cancel")
async def cancel_appointment(
    payload: AikortexPayload,
    response: Response,
    x_proxy_secret: Union[str, None] = Header(default=None, alias="X-Proxy-Secret")
):
    # 1. Validação de Ambiente
    clinicorp_token = os.getenv("CLINICORP_TOKEN")
    if not clinicorp_token:
        logger.error("Token da Clinicorp não configurado.")
        raise HTTPException(status_code=500, detail="Server Error: Token not configured")

    # 2. Tratamento de Tipos (A MÁGICA ACONTECE AQUI)
    try:
        # Forçamos o ID do agendamento ser um INTEIRO
        clean_appointment_id = int(payload.id)
        
        # O subscriber_id pode ser string ("odontomaria") ou int. 
        # Se for numérico (string com números), convertemos para int para garantir.
        # Se for texto (slug), mantemos texto.
        clean_subscriber_id = payload.subscriber_id
        if isinstance(clean_subscriber_id, str) and clean_subscriber_id.isdigit():
            clean_subscriber_id = int(clean_subscriber_id)
            
    except ValueError:
        raise HTTPException(status_code=400, detail=f"O ID informado '{payload.id}' não é válido.")

    # 3. Montagem do Payload Destino (O que a Clinicorp vai receber)
    dest_payload = {
        "subscriber_id": clean_subscriber_id,
        "id": clean_appointment_id # Aqui vai sem aspas: 12345
    }

    headers = {
        "Accept": "application/json",
        "Authorization": clinicorp_token,
        "Content-Type": "application/json"
    }

    logger.info(f"Enviando para Clinicorp -> ID: {clean_appointment_id} | Sub: {clean_subscriber_id}")

    # 4. Envio da Requisição
    async with httpx.AsyncClient() as client:
        try:
            upstream_resp = await client.post(
                CLINICORP_URL,
                json=dest_payload, # json=... serializa automaticamente para JSON correto
                headers=headers,
                timeout=15.0
            )
            
            # Espelha o status code da Clinicorp
            response.status_code = upstream_resp.status_code
            
            try:
                upstream_data = upstream_resp.json()
            except Exception:
                logger.warning("Resposta da Clinicorp não é JSON válido.")
                upstream_data = {"raw_error": upstream_resp.text}

            return {
                "status": "completed",
                "clinicorp_status": upstream_resp.status_code,
                "sent_payload": dest_payload, # Debug: mostra o que enviamos de fato
                "error": upstream_data if upstream_resp.is_error else None,
                "data": upstream_data
            }

        except httpx.TimeoutException:
            logger.error("Timeout Clinicorp")
            raise HTTPException(status_code=504, detail="Gateway Timeout (Clinicorp)")
        except httpx.RequestError as e:
            logger.error(f"Erro Conexão: {str(e)}")
            raise HTTPException(status_code=502, detail=f"Erro Conexão: {str(e)}")

# Configuração para rodar localmente
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
