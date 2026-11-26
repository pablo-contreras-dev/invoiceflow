# Guía de demo

Esta guía recorre la recepción, validación y revisión manual de una factura usando exclusivamente datos de demostración.

## Preparación

1. Desde la raíz del proyecto, inicia `docker compose up --build`.
2. Abre `http://localhost:5678` y crea el usuario propietario de n8n en el primer acceso. Si el workflow no aparece en tu instancia, importa `automation/invoiceflow-intake.json`.
3. En **Email review alert**, crea una credencial SMTP con host `mailpit`, puerto `1025`, y sin autenticación ni SSL/TLS. Puedes conservar las direcciones `.test`: Mailpit captura el mensaje localmente y no lo entrega a destinatarios reales.
4. Activa el workflow y abre `http://localhost:8025` para consultar los avisos capturados.
5. Abre el panel en `http://localhost:8000/dashboard/`.

El caso validado no necesita SMTP. Los casos que requieren revisión envían un aviso a Mailpit. Esta configuración es solo para desarrollo local; no la uses como servidor de correo de producción.

## 1. Recibir una factura válida

En PowerShell, desde la raíz del repositorio:

```powershell
$validInvoice = Get-Content -Raw examples/invoice-valid.json
$validKey = "demo-valid-001"
$validResult = Invoke-RestMethod `
  -Uri http://localhost:5678/webhook/invoiceflow/intake `
  -Method Post `
  -ContentType 'application/json' `
  -Headers @{ 'Idempotency-Key' = $validKey } `
  -Body $validInvoice
$validResult
```

El resultado esperado tiene estado `validated`, y la factura aparece en el panel.

## 2. Comprobar el reintento idempotente

Repite la misma llamada con el mismo cuerpo y `$validKey`. La API debe devolver el mismo `id` y `replayed: true`, sin crear otro registro.

Si reutilizas la clave con un cuerpo diferente, la API responde `409 Conflict`.

## 3. Revisar y resolver una incidencia

Envía el ejemplo con diferencia en el total:

```powershell
$reviewInvoice = Get-Content -Raw examples/invoice-needs-review.json
$reviewResult = Invoke-RestMethod `
  -Uri http://localhost:5678/webhook/invoiceflow/intake `
  -Method Post `
  -ContentType 'application/json' `
  -Headers @{ 'Idempotency-Key' = 'demo-review-001' } `
  -Body $reviewInvoice
$reviewResult
```

En el panel, abre la factura pendiente, revisa el motivo, escribe `Demo Reviewer` como persona revisora y añade una nota. Pulsa **Aprobar** o **Rechazar**. La factura cambia a `validated` o `rejected` y el panel permite consultar su historial.

La misma operación está disponible en `POST /invoices/{id}/review`. Para revisar el historial por API, usa `GET /invoices/{id}/reviews`.

## 4. Consultar y exportar

- Filtra pendientes: `GET http://localhost:8000/invoices?status=needs_review`.
- Filtra rechazadas: `GET http://localhost:8000/invoices?status=rejected`.
- Descarga el CSV: `http://localhost:8000/invoices/export.csv`.

El CSV incluye el estado, el motivo de revisión, la decisión, la persona revisora y la nota.

## Notas para repetir la demo

- Las claves del ejemplo deben ser nuevas al iniciar una ejecución de demo distinta, o se devolverá la respuesta idempotente anterior.
- Si se vuelve a enviar el mismo proveedor y número con una clave nueva, se registra como posible duplicado y requiere revisión.
- El campo de persona revisora es texto de demo. El proyecto todavía no incorpora autenticación ni verifica identidades.
- No introduzcas facturas, NIF ni correos reales.
