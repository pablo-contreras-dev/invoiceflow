const pageSize = 25;
let offset = 0;
let total = 0;
let activeStatus = "";

const rows = document.querySelector("#invoice-rows");
const errorBanner = document.querySelector("#error-banner");
const previousButton = document.querySelector("#previous-page");
const nextButton = document.querySelector("#next-page");
const pageSummary = document.querySelector("#page-summary");

function formatDate(value) {
  return new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short", year: "numeric" })
    .format(new Date(`${value}T12:00:00`));
}

function formatAmount(value, currency) {
  return new Intl.NumberFormat("es-ES", { style: "currency", currency }).format(Number(value));
}

function makeCell(className, content) {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  cell.textContent = content;
  return cell;
}

function renderInvoices(invoices) {
  rows.replaceChildren();
  if (!invoices.length) {
    const emptyRow = document.createElement("tr");
    const emptyCell = makeCell("table-message", "No hay facturas para mostrar.");
    emptyCell.colSpan = 5;
    emptyRow.append(emptyCell);
    rows.append(emptyRow);
    return;
  }

  for (const invoice of invoices) {
    const row = document.createElement("tr");
    const invoiceCell = makeCell("invoice-number", invoice.invoice_number);
    row.append(invoiceCell);

    const supplier = document.createElement("td");
    const supplierName = document.createElement("span");
    supplierName.className = "supplier-name";
    supplierName.textContent = invoice.supplier_name;
    const taxId = document.createElement("span");
    taxId.className = "tax-id";
    taxId.textContent = invoice.supplier_tax_id;
    supplier.append(supplierName, taxId);
    row.append(supplier);

    row.append(makeCell("", formatDate(invoice.issue_date)));
    row.append(makeCell("align-right amount", formatAmount(invoice.total_amount, invoice.currency)));

    const statusCell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `status-badge ${invoice.status === "validated" ? "status-validated" : "status-review"}`;
    badge.textContent = invoice.status === "validated" ? "Validada" : "Revisión pendiente";
    statusCell.append(badge);
    row.append(statusCell);
    rows.append(row);
  }
}

function updateMetrics(invoices) {
  document.querySelector("#metric-total").textContent = String(invoices.length);
  document.querySelector("#metric-validated").textContent = String(invoices.filter((item) => item.status === "validated").length);
  document.querySelector("#metric-review").textContent = String(invoices.filter((item) => item.status === "needs_review").length);
}

function updatePagination(itemsOnPage) {
  const start = total === 0 ? 0 : offset + 1;
  const end = offset + itemsOnPage;
  pageSummary.textContent = `Mostrando ${start}–${end} de ${total}`;
  previousButton.disabled = offset === 0;
  nextButton.disabled = offset + pageSize >= total;
}

async function loadInvoices() {
  errorBanner.hidden = true;
  rows.innerHTML = '<tr><td class="table-message" colspan="5">Cargando facturas…</td></tr>';
  const params = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
  if (activeStatus) params.set("status", activeStatus);
  try {
    const response = await fetch(`/invoices?${params.toString()}`);
    if (!response.ok) throw new Error(`La API respondió con el código ${response.status}.`);
    const result = await response.json();
    total = result.total;
    renderInvoices(result.items);
    updateMetrics(result.items);
    updatePagination(result.items.length);
  } catch (error) {
    rows.replaceChildren();
    const errorRow = document.createElement("tr");
    const errorCell = makeCell("table-message", "No se pudieron cargar las facturas.");
    errorCell.colSpan = 5;
    errorRow.append(errorCell);
    rows.append(errorRow);
    errorBanner.textContent = `${error.message} Comprueba que la API y la base de datos estén disponibles.`;
    errorBanner.hidden = false;
    document.querySelector("#metric-total").textContent = "—";
    document.querySelector("#metric-validated").textContent = "—";
    document.querySelector("#metric-review").textContent = "—";
    total = 0;
    updatePagination(0);
  }
}

document.querySelector("#status-filter").addEventListener("change", (event) => {
  activeStatus = event.target.value;
  offset = 0;
  document.querySelector("#export-link").href = activeStatus
    ? `/invoices/export.csv?status=${encodeURIComponent(activeStatus)}`
    : "/invoices/export.csv";
  loadInvoices();
});
document.querySelector("#refresh-button").addEventListener("click", loadInvoices);
previousButton.addEventListener("click", () => {
  offset = Math.max(0, offset - pageSize);
  loadInvoices();
});
nextButton.addEventListener("click", () => {
  offset += pageSize;
  loadInvoices();
});

loadInvoices();
