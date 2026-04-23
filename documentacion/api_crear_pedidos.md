# API – Crear pedidos (`POST /api/pedidos`)

## Endpoint

| Método | Ruta |
|--------|------|
| `POST` | `/api/pedidos` (también `/api/pedidos.json`) |

## Autenticación

Enviar el header:

```http
CAMPE-API-Key: <valor de Rails.application.credentials.campe_api_key>
```

- Sin header → `401 Unauthorized`
- Clave inválida → `403 Forbidden`

## Cuerpo JSON

Los parámetros pueden ir en la raíz, dentro de `pedido`, o (parcialmente) dentro de `payload`.

### Obligatorio

- **Cliente:** `telefono` **o** `cliente_id` (el usuario debe existir con rol `cliente`).
- **Ítems:** al menos un elemento en `items` **o**, si usás `payload`, en `payload.productos`.

### Campos opcionales (pedido)

| Campo | Descripción |
|-------|-------------|
| `fecha` | Fecha del pedido. Por defecto: fecha actual. |
| `tipo_pedido` | Tipo de pedido (texto según dominio). |
| `deposito_id` | ID del depósito. |
| `forma_pago` | Debe ser una de las de `OrdenAcopio::FORMAS_PAGO` (ver abajo). |
| `fecha_pago` | Fecha en formato `YYYY-MM-DD`. |

### Por ítem (`items[]` o `payload.productos[]`)

| Campo | Obligatorio | Notas |
|-------|-------------|--------|
| `producto_id` o `id` | Sí | ID del producto. |
| `cantidad` | Sí | Mayor que 0. |
| `precio_unitario` | No | Si no se envía, se calcula (precio base + costo transporte zona). |
| `descuento_porcentaje` | No | Por defecto 0. |
| `total_linea` | No | Si no se envía, se calcula. |
| `paletizado` | No | Boolean, por defecto false. |

### Formas de pago válidas

- `EFECTIVO EN OFICINA`
- `TRANSFERENCIA`
- `EFECTIVO A RETIRAR`
- `DEPÓSITO CUENTA TERCEROS`
- `ECHEQ`

## Ejemplos

### Mínimo (por teléfono)

```json
{
  "telefono": "+5491123456789",
  "items": [
    { "producto_id": 42, "cantidad": 3 }
  ]
}
```

### Con más campos

```json
{
  "telefono": "+5491123456789",
  "fecha": "2026-04-22",
  "tipo_pedido": "Entrega directa",
  "deposito_id": 1,
  "forma_pago": "TRANSFERENCIA",
  "fecha_pago": "2026-04-23",
  "items": [
    {
      "producto_id": 42,
      "cantidad": 3,
      "descuento_porcentaje": 0,
      "paletizado": false
    }
  ]
}
```

### Anidado bajo `pedido` (y `id` como alias de producto)

```json
{
  "pedido": {
    "cliente_id": 15,
    "fecha": "2026-04-22",
    "items": [
      { "id": 42, "cantidad": 2 }
    ]
  }
}
```

## Respuestas

- **201 Created:** pedido creado (incluye `id`, `estado` típicamente `PENDIENTE`, `total`, `items`, etc.).
- **400 Bad Request:** falta cliente, ítems, item inválido o `forma_pago` inválida.
- **404 Not Found:** cliente o producto no encontrado.

## Ejemplo `curl`

```bash
curl -X POST "https://TU_HOST/api/pedidos" \
  -H "Content-Type: application/json" \
  -H "CAMPE-API-Key: TU_API_KEY" \
  -d '{
    "telefono": "+5491123456789",
    "items": [
      { "producto_id": 1, "cantidad": 2 }
    ]
  }'
```

---

*Referencia de implementación:* `mtm_admin/app/controllers/api/pedidos_controller.rb` (`create`), rutas en `config/routes.rb` (`namespace :api` → `resources :pedidos, only: [:index, :create]`).
