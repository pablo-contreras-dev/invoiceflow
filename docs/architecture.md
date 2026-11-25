# Arquitectura inicial

## Componentes y límites

- **n8n** coordina la recepción, llama a la API y enruta resultados. Las reglas de negocio no deben duplicarse en el workflow.
- **API Python** valida y normaliza los datos. Devuelve errores legibles y códigos HTTP coherentes.
- **PostgreSQL** es la fuente de verdad para facturas y ejecuciones. La clave de duplicidad inicial es proveedor + número de factura.
- **Alembic** aplica cambios de esquema de manera versionada antes de iniciar la API.
- **CSV/Excel** es una salida de consulta, no una segunda base de datos.
- **Power Automate** puede sustituir la parte de integración Microsoft si el entorno del cliente lo requiere.

## Estados del proceso

```text
received -> validated
         -> needs_review
         -> failed
```

`needs_review` representa un dato ausente, inconsistente o un posible duplicado que requiere decisión humana. `failed` se reserva para fallos técnicos tras aplicar la política de reintentos. Cada transición debe guardar fecha, resultado y detalle suficiente para diagnosticarla.

## Contrato de entrada (borrador)

```json
{
  "supplier_name": "Proveedor Demo SL",
  "supplier_tax_id": "B12345678",
  "invoice_number": "DEMO-2026-001",
  "issue_date": "2026-11-20",
  "currency": "EUR",
  "net_amount": "100.00",
  "tax_amount": "21.00",
  "total_amount": "121.00"
}
```

Los importes se representan como cadenas decimales en la entrada para evitar errores de precisión binaria. El esquema definitivo debe especificar límites, redondeo y reglas fiscales antes de procesar documentos reales.

## API implementada

- `/dashboard/`: panel de revisión servido por la API, con paginación, filtros y exportación.
- `GET /health`: comprobación básica de disponibilidad.
- `POST /invoices`: recibe JSON, valida tipos y límites, compara `net_amount + tax_amount` con `total_amount`, comprueba duplicados y registra cada intento.
- `GET /invoices/{id}`: consulta el resultado registrado.
- `GET /invoices?status=needs_review&limit=25&offset=0`: consulta paginada con filtro opcional por estado.
- `GET /invoices?search=demo&status=needs_review`: busca sin distinguir mayúsculas en proveedor, identificador fiscal o número de factura; permite combinarlo con el estado y la paginación.
- `GET /invoices/export.csv`: descarga el registro en CSV compatible con Excel y admite filtros opcionales por estado y búsqueda.
- `GET /docs`: documentación OpenAPI generada por FastAPI.

El endpoint de recepción devuelve `validated` cuando no encuentra incidencias y `needs_review` cuando detecta diferencias o posibles duplicados. Los motivos actuales son `total_mismatch` y `possible_duplicate`. Los errores de entrada se devuelven como `422`; los errores de persistencia, como `500` y el health check como `503` si no hay conexión con la base de datos.

La exportación usa UTF-8 con BOM para compatibilidad práctica con Excel y antepone un apóstrofo a campos de texto que podrían ejecutarse como fórmulas al abrir el CSV en una hoja de cálculo.

## Workflow n8n

El workflow exportado en `automation/invoiceflow-intake.json` recibe un POST, reenvía el objeto JSON a la API y divide el recorrido por el estado devuelto. Los errores HTTP se devuelven al emisor con su código y cuerpo. Los registros `validated` se responden directamente. Los `needs_review` activan un aviso por email antes de devolver el registro al emisor. La credencial SMTP y las direcciones de destinatario se configuran en la instancia n8n; no se incluyen secretos ni direcciones reales en el repositorio. El aviso reintenta tres veces; si finalmente falla, el registro persiste en la API aunque el webhook no complete la respuesta normal.

En el Compose local, n8n llama a `http://api:8000` por la red privada de Docker. Desde el host, se usa `http://localhost:5678`.

## Siguiente hito

1. Preparar capturas y datos de demostración para la presentación del portfolio.
2. Ampliar la auditoría de notificaciones y añadir un modo de reenvío manual.
3. Permitir revisar y reasignar estados desde el panel.

## Seguridad y privacidad de la demo

- Usar datos totalmente ficticios.
- No versionar credenciales, tokens ni archivos `.env`.
- Evitar guardar el documento original en logs.
- Limitar el acceso al webhook cuando se despliegue fuera del entorno local.
