# Agente WhatsApp — Setup

## ¿Cómo funciona?

```
Cliente escribe por WhatsApp
        ↓
   Twilio recibe el mensaje
        ↓
   Llama a tu webhook (whatsapp_server.py)
        ↓
   Claude genera la respuesta
        ↓
   Twilio envía la respuesta al cliente
```

---

## Paso 1 — Instalar dependencias

```bash
pip install -r requirements.txt
```

---

## Paso 2 — Crear cuenta en Twilio

1. Entrá a [twilio.com](https://www.twilio.com) y creá una cuenta gratuita.
2. En el dashboard, andá a **Console > Messaging > Try it out > Send a WhatsApp message**.
3. Vas a ver el **Twilio Sandbox for WhatsApp**:
   - Anotá el número del sandbox: `+1 415 523 8886`
   - Para probar, mandá desde tu WhatsApp el código que te muestran (ej: `join copper-fox`)
4. Copiá tu **Account SID** y **Auth Token** del dashboard principal.

---

## Paso 3 — Configurar el .env

Completá estas variables en tu `.env`:

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

# Describí tus servicios (el agente los usa para responder clientes)
FRANCO_SERVICES=- Consultoría de negocios\n- Planes comerciales\n- Mentoring

# Opcional: link de Calendly para que el bot comparta directamente
FRANCO_CALENDAR_LINK=https://calendly.com/tu-usuario
```

---

## Paso 4 — Instalar ngrok

ngrok te da una URL pública para que Twilio pueda llegar a tu servidor local.

```bash
# En Windows (con chocolatey):
choco install ngrok

# O descargalo de https://ngrok.com/download
```

---

## Paso 5 — Arrancar el servidor

**Terminal 1 — el servidor:**
```bash
python whatsapp_server.py
```

**Terminal 2 — ngrok:**
```bash
ngrok http 5001
```

ngrok te va a mostrar algo así:
```
Forwarding  https://abc123.ngrok.io → http://localhost:5001
```

---

## Paso 6 — Conectar Twilio con ngrok

1. Copiá la URL de ngrok (ej: `https://abc123.ngrok.io`).
2. En Twilio, andá a **Messaging > Try it out > Send a WhatsApp message**.
3. En el campo **"When a message comes in"**, pegá:
   ```
   https://abc123.ngrok.io/webhook
   ```
4. Método: **HTTP POST**. Guardá.

---

## ¡Listo! Probá mandando un mensaje

Desde el WhatsApp que registraste en el sandbox, mandá un mensaje al número de Twilio.
El agente va a responder automáticamente.

---

## Endpoints de monitoreo

| Endpoint | Descripción |
|---|---|
| `GET /health` | Estado del servidor |
| `GET /conversations` | Ver todos los chats activos |
| `DELETE /conversations/5491112345678` | Limpiar historial de un número |

---

## Para producción (cuando quieras ir en serio)

- **Número propio de WhatsApp Business:** en lugar del sandbox, registrá tu número real en Twilio. Requiere verificación de negocio con Meta.
- **Servidor real:** deployá en Railway, Render o un VPS para no necesitar tener la compu prendida.
- **Base de datos:** reemplazá el dict en memoria por Redis o SQLite para no perder los historiales si se reinicia el servidor.
