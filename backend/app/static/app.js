const pageSize = 25;
let offset = 0;
let total = 0;
let activeStatus = "";

const rows = document.querySelector("#invoice-rows");
const errorBanner = document.querySelector("#error-banner");
const previousButton = document.querySelector("#previous-page");
const nextButton = document.querySelector("#next-page");
const pageSummary = document.querySelector("#page-summary");
const reviewDialog = document.querySelector("#review-dialog");
const reviewForm = document.querySelector("#review-form");
const reviewError = document.querySelector("#review-error");
const invoiceCache = new Map();

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
    emptyCell.colSpan = 6;
    emptyRow.append(emptyCell);
    rows.append(emptyRow);
    return;
  }

  for (const invoice of invoices) {
    invoiceCache.set(invoice.id, invoice);
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
    const statusPresentation = {
      validated: ["Validada", "status-validated"],
      needs_review: ["Revisión pendiente", "status-review"],
      rejected: ["Rechazada", "status-rejected"],
    }[invoice.status] || [invoice.status, "status-review"];
    badge.className = `status-badge ${statusPresentation[1]}`;
    badge.textContent = statusPresentation[0];
    const actionCell = document.createElement("td");
    if (invoice.status === "needs_review" || invoice.review_decision) {
      const action = document.createElement("button");
      action.type = "button";
      action.className = "review-action";
      action.dataset.invoiceId = String(invoice.id);
      action.dataset.mode = invoice.status === "needs_review" ? "review" : "history";
      action.textContent = invoice.status === "needs_review" ? "Resolver" : "Historial";
      actionCell.append(action);
    }
    row.append(actionCell);
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
  rows.innerHTML = '<tr><td class="table-message" colspan="6">Cargando facturas…</td></tr>';
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
    errorCell.colSpan = 6;
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

function showReviewDialog(invoice, historyOnly = false) {
  reviewDialog.dataset.invoiceId = String(invoice.id);
  reviewError.hidden = true;
  if (!historyOnly) document.querySelector("#review-note").value = "";
  document.querySelector("#review-title").textContent = historyOnly ? "Historial de revisión" : "Resolver factura";
  document.querySelector("#review-invoice-summary").textContent =
    `${invoice.invoice_number} · ${invoice.supplier_name} · ${formatAmount(invoice.total_amount, invoice.currency)}`;
  const reasons = document.querySelector("#review-reasons");
  reasons.replaceChildren();
  if (invoice.reasons.length) {
    const heading = document.createElement("strong");
    heading.textContent = "Motivos detectados";
    const list = document.createElement("ul");
    for (const reason of invoice.reasons) {
      const item = document.createElement("li");
      item.textContent = reason === "total_mismatch" ? "La suma de base imponible e impuestos no coincide con el total." :
        reason === "possible_duplicate" ? "Ya existe una factura con este proveedor y número." : reason;
      list.append(item);
    }
    reasons.append(heading, list);
  } else if (invoice.review_note) {
    reasons.textContent = invoice.review_note;
  }
  document.querySelector("#decision-fields").hidden = historyOnly;
  document.querySelector(".dialog-actions").hidden = historyOnly;
  document.querySelector("#review-history").textContent = "Cargando historial…";
  reviewDialog.showModal();
  loadReviewHistory(invoice.id);
}

async function loadReviewHistory(invoiceId) {
  const history = document.querySelector("#review-history");
  try {
    const response = await fetch(`/invoices/${invoiceId}/reviews`);
    if (!response.ok) throw new Error(`La API respondió con el código ${response.status}.`);
    const events = await response.json();
    history.replaceChildren();
    if (!events.length) {
      history.textContent = "Aún no hay decisiones registradas.";
      return;
    }
    for (const event of events) {
      const entry = document.createElement("article");
      entry.className = "review-event";
      const title = document.createElement("strong");
      title.textContent = `${event.decision === "approved" ? "Aprobada" : "Rechazada"} · ${event.reviewer}`;
      const date = document.createElement("time");
      date.dateTime = event.created_at;
      date.textContent = new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short" }).format(new Date(event.created_at));
      entry.append(title, date);
      if (event.note) {
        const note = document.createElement("p");
        note.textContent = event.note;
        entry.append(note);
      }
      history.append(entry);
    }
  } catch (error) {
    history.textContent = `No se pudo cargar el historial. ${error.message}`;
  }
}

async function submitReview(decision) {
  if (!reviewForm.reportValidity()) return;
  const submitButtons = [...reviewForm.querySelectorAll(".dialog-actions button")];
  submitButtons.forEach((button) => { button.disabled = true; });
  reviewError.hidden = true;
  const invoiceId = Number(reviewDialog.dataset.invoiceId);
  try {
    const response = await fetch(`/invoices/${invoiceId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision,
        reviewer: document.querySelector("#reviewer-name").value.trim(),
        note: document.querySelector("#review-note").value.trim(),
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `La API respondió con el código ${response.status}.`);
    reviewDialog.close();
    await loadInvoices();
  } catch (error) {
    reviewError.textContent = error.message;
    reviewError.hidden = false;
  } finally {
    submitButtons.forEach((button) => { button.disabled = false; });
  }
}

rows.addEventListener("click", (event) => {
  const action = event.target.closest("button[data-invoice-id]");
  if (!action) return;
  const invoice = invoiceCache.get(Number(action.dataset.invoiceId));
  if (invoice) showReviewDialog(invoice, action.dataset.mode === "history");
});
document.querySelector("#approve-invoice").addEventListener("click", () => submitReview("approved"));
document.querySelector("#reject-invoice").addEventListener("click", () => submitReview("rejected"));
document.querySelector("#close-review").addEventListener("click", () => reviewDialog.close());

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
