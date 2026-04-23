"""
Herramienta para crear pedidos via la API de Campechana.
"""

import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

CAMPE_API_URL = os.getenv("CAMPE_API_URL", "").rstrip("/")
CAMPE_API_KEY = os.getenv("CAMPE_API_KEY", "")


def crear_pedido(
    telefono: str,
    items: list[dict],
    forma_pago: str = None,
    fecha_pago: str = None,
    tipo_pedido: str = None,
    deposito_id: int = None,
) -> dict:
    """
    Crea un pedido en el ERP via API.

    Args:
        telefono: Número del cliente en formato +54911...
        items: Lista de dicts con 'producto_id' y 'cantidad' (y opcionalmente
               'precio_unitario', 'descuento_porcentaje', 'paletizado').
        forma_pago: Una de las formas válidas del ERP (opcional).
        fecha_pago: Fecha en formato YYYY-MM-DD (opcional).
        tipo_pedido: Texto libre con el tipo de pedido (opcional).
        deposito_id: ID del depósito (opcional).

    Returns:
        dict con 'ok' (bool), 'pedido_id' (int, si ok), 'mensaje' (str).
    """
    if not CAMPE_API_URL or not CAMPE_API_KEY:
        log.error("CAMPE_API_URL o CAMPE_API_KEY no configurados en .env")
        return {"ok": False, "mensaje": "API del ERP no configurada."}

    payload = {"telefono": telefono, "items": items}
    if forma_pago:
        payload["forma_pago"] = forma_pago
    if fecha_pago:
        payload["fecha_pago"] = fecha_pago
    if tipo_pedido:
        payload["tipo_pedido"] = tipo_pedido
    if deposito_id:
        payload["deposito_id"] = deposito_id

    try:
        response = requests.post(
            f"{CAMPE_API_URL}/api/pedidos",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "CAMPE-API-Key": CAMPE_API_KEY,
            },
            timeout=10,
        )

        if response.status_code == 201:
            data = response.json()
            pedido_id = data.get("id")
            log.info(f"Pedido creado: ID {pedido_id} para {telefono}")
            return {"ok": True, "pedido_id": pedido_id, "mensaje": f"Pedido #{pedido_id} creado correctamente."}

        elif response.status_code == 400:
            detail = response.json().get("error", response.text)
            log.warning(f"Pedido rechazado (400): {detail}")
            return {"ok": False, "mensaje": f"Datos inválidos: {detail}"}

        elif response.status_code == 404:
            detail = response.json().get("error", response.text)
            log.warning(f"No encontrado (404): {detail}")
            return {"ok": False, "mensaje": f"No encontrado: {detail}"}

        elif response.status_code == 401:
            log.error("API Key inválida o faltante (401)")
            return {"ok": False, "mensaje": "Error de autenticación con el ERP."}

        else:
            log.error(f"Error inesperado {response.status_code}: {response.text}")
            return {"ok": False, "mensaje": f"Error del servidor ({response.status_code})."}

    except requests.exceptions.Timeout:
        log.error("Timeout al conectar con la API del ERP")
        return {"ok": False, "mensaje": "El servidor tardó demasiado en responder."}

    except requests.exceptions.ConnectionError:
        log.error("No se pudo conectar con la API del ERP")
        return {"ok": False, "mensaje": "No se pudo conectar con el ERP."}
