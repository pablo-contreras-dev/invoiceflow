# InvoiceFlow

**Automatización trazable para la recepción y validación de facturas de proveedores.**

InvoiceFlow es un proyecto de portfolio que modela un proceso habitual de back office: recibir una factura, validar sus datos, registrar el resultado y derivar los casos que necesitan revisión humana. El objetivo es reducir tareas manuales sin ocultar errores ni decisiones.

> Proyecto demostrativo. Usa exclusivamente datos ficticios; no procesa documentos reales ni sustituye un sistema contable.

## Problema

En procesos manuales, los datos de factura se copian entre correo, hojas de cálculo y sistemas internos. Esto facilita duplicados, campos incompletos y falta de seguimiento. InvoiceFlow propone un flujo repetible con validaciones explícitas y un registro de cada resultado.

## Flujo propuesto

1. **Entrada:** n8n recibe una factura de prueba mediante webhook o formulario.
2. **Validación:** un servicio Python comprueba campos obligatorios, formatos, importes y duplicados.
3. **Persistencia:** PostgreSQL conserva la factura, su estado y el historial de procesamiento.
4. **Gestión:** los casos válidos quedan registrados; los inválidos pasan a revisión y generan una notificación.
5. **Salida:** se puede exportar un informe CSV compatible con Excel para revisión operativa.

Power Automate queda como integración opcional para organizaciones que usan Microsoft 365. No es necesario desplegar dos orquestadores en el mismo flujo.

## Alcance inicial

- Datos de factura ficticios en JSON.
- Validación de proveedor, número, fecha, moneda e importes.
- Detección de duplicados por proveedor y número de factura.
- Estados claros: `received`, `validated`, `needs_review` y `failed`.
- Registro auditable de cada intento y motivo de rechazo.
- Exportación CSV para Excel.

La lectura automática de PDF/OCR y cualquier integración externa se dejan para fases posteriores, una vez que el flujo básico sea fiable.

## Tecnologías

| Componente | Tecnología | Responsabilidad |
|---|---|---|
| Orquestación | n8n | Entrada, pasos del flujo y notificaciones |
| Servicio de validación | Python | Reglas de negocio y API |
| Panel de revisión | HTML, CSS y JavaScript | Consulta de estados, incidencias y paginación |
| Base de datos | PostgreSQL | Facturas e historial de procesamiento |
| Informe operativo | CSV / Excel | Revisión y exportación de resultados |
| Alternativa M365 | Power Automate | Integración opcional con Outlook/SharePoint |

## Estructura

```text
.
├── backend/       # API y reglas de validación en Python
│   └── app/static/ # Panel de revisión web
├── automation/    # Flujos exportables de n8n
├── backend/migrations/ # Migraciones versionadas de la base de datos
├── docs/          # Arquitectura, decisiones y guía de demostración
├── examples/      # Datos ficticios para la demo
└── README.md
```

## Estado

**Demo full stack inicial.** Incluye un panel web de revisión, una API Python, persistencia en PostgreSQL, consulta paginada, exportación CSV y un workflow n8n importable para recibir y enrutar facturas.

## Ejecución local

Con Docker instalado, desde la raíz del proyecto:

```bash
docker compose up --build
```

El panel de revisión queda disponible en `http://localhost:8000/dashboard/`; la API y su documentación interactiva están en `http://localhost:8000/docs`, el estado de API y base de datos en `/health` y n8n en `http://localhost:5678`. El panel permite filtrar y paginar facturas, ver incidencias y exportar resultados para Excel. El contenedor de la API aplica las migraciones de Alembic antes de arrancar. En el primer acceso, n8n solicita crear el usuario propietario. Para detener los contenedores, usa `docker compose down`.

Para ejecutar la API sin Docker, instala `requirements.txt` en un entorno virtual, aplica `alembic -c backend/alembic.ini upgrade head` y arranca `uvicorn backend.app.main:app --reload`. En este modo usa SQLite local por defecto. Para PostgreSQL, configura `DATABASE_URL` según `.env.example` antes de aplicar la migración.

Prueba manualmente enviando el contenido de cualquiera de los JSON de `examples/` mediante `POST /invoices`. El primer ejemplo debe quedar `validated`; el segundo `needs_review` con motivo `total_mismatch`. Si se envía dos veces la misma factura, el segundo intento se conserva y queda enlazado al primer registro con motivo `possible_duplicate`.

`GET /invoices?status=needs_review&limit=25&offset=0` devuelve resultados paginados. `GET /invoices/export.csv` descarga todos los registros; también admite el filtro `status`. El CSV incluye BOM UTF-8 para facilitar su apertura en Excel y neutraliza campos de texto que podrían interpretarse como fórmulas.

## Integración n8n

1. En n8n, importa `automation/invoiceflow-intake.json`.
2. En el nodo **Email review alert**, configura una credencial SMTP y cambia los correos de ejemplo `.test` por direcciones de prueba tuyas.
3. Activa el workflow. Envía un `POST` JSON a `http://localhost:5678/webhook/invoiceflow/intake`.

El workflow llama a la API por la red interna de Docker (`http://api:8000`), responde con el registro creado y, si requiere revisión, envía un correo. Los errores HTTP de la API se devuelven al emisor con su código y cuerpo; el correo reintenta hasta tres veces ante fallos. El registro de la factura ya se habrá guardado antes del envío de correo. El workflow se importa inactivo y sin credenciales. `N8N_SECURE_COOKIE=false` en Compose permite el acceso local por HTTP; es una configuración solo para desarrollo local, no para publicar el servicio en Internet.

Ejemplo para probar desde PowerShell una vez activado el workflow:

```powershell
Invoke-RestMethod -Uri http://localhost:5678/webhook/invoiceflow/intake -Method Post -ContentType 'application/json' -InFile examples/invoice-valid.json
```

## Presentación para portfolio

La demo debe explicar el problema, enseñar un caso válido y otro que requiera revisión, y cuantificar el resultado con métricas reproducibles (por ejemplo, tiempo manual estimado frente al flujo automatizado). No se incluyen ahorros ni resultados inventados: se medirán durante la demo con datos de ejemplo.

## Licencia

Pendiente de definir.

## Idempotencia de entrada

La API acepta `Idempotency-Key` (8–128 caracteres). Si se repite la misma petición con la misma clave, devuelve el registro original con `replayed: true` sin crear otro intento. La clave no puede reutilizarse con un cuerpo distinto (`409 Conflict`). Para registrar deliberadamente otra presentación de una factura ya recibida, envía una clave nueva o no envíes el encabezado; el sistema la marcará como posible duplicado.

## Búsqueda en el panel

El panel permite buscar por nombre de proveedor, identificador fiscal o número de factura (mínimo 2 caracteres) y combinar la búsqueda con el filtro de estado. La API admite `GET /invoices?search=demo&status=needs_review`; la descarga CSV conserva esos mismos filtros.
