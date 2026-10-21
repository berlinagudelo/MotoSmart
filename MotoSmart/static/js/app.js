const state = {
  token: localStorage.getItem('motosmart_token'),
  role: localStorage.getItem('motosmart_role'),
  username: localStorage.getItem('motosmart_username'),
  motos: [],
  diags: [],
  citas: [],
  prioridades: [],
  inventario: [],
  facturas: [],
  ordenes: [],
  mecanicos: [],
  isWorkshopOwner: false
};

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const isAdmin = () => state.role === 'admin';
const isMechanic = () => state.role === 'mecanico';
const isCustomer = () => state.role === 'cliente';
const isWorkshopOwner = () => isMechanic() && state.isWorkshopOwner;
const canManageInventory = () => isAdmin() || isWorkshopOwner();
let openAppointmentAfterMoto = false;
let scanPreviewUrl = '';
let clientWelcomeTimer = null;

function playGarageTransition() {
  const garage = $('#garage-intro');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  garage.classList.remove('hidden');
  garage.classList.add('is-opening');
  garage.setAttribute('aria-hidden', 'false');
  window.setTimeout(() => {
    garage.classList.remove('is-opening');
    garage.classList.add('hidden');
    garage.setAttribute('aria-hidden', 'true');
  }, reduceMotion ? 30 : 2300);
}

function playClientWelcome() {
  const welcome = $('#client-welcome');
  if (!welcome || !isCustomer() || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const close = () => {
    window.clearTimeout(clientWelcomeTimer);
    welcome.classList.remove('is-playing');
    welcome.classList.add('hidden');
    welcome.setAttribute('aria-hidden', 'true');
  };
  welcome.classList.remove('hidden');
  welcome.classList.add('is-playing');
  welcome.setAttribute('aria-hidden', 'false');
  clientWelcomeTimer = window.setTimeout(close, 3200);
  welcome.onclick = event => {
    if (event.target.closest('.client-welcome-skip')) close();
  };
}

function decode(token) {
  try { return JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); }
  catch { return {}; }
}

function escapeHtml(value) {
  const element = document.createElement('span');
  element.textContent = value ?? '-';
  return element.innerHTML;
}

function toast(text, type = 'error') {
  const element = document.createElement('div');
  element.className = `toast ${type}`;
  element.textContent = text;
  $('#toast-region').append(element);
  setTimeout(() => element.classList.add('is-leaving'), 3800);
  setTimeout(() => element.remove(), 4100);
}

function setFormPending(form, pending, message = 'Guardando...') {
  const submit = form.querySelector('button.primary:not([type="button"])');
  if (!submit) return;
  if (pending) {
    submit.dataset.label = submit.textContent;
    submit.textContent = message;
    submit.disabled = true;
    submit.classList.add('is-pending');
    form.classList.add('is-pending');
    return;
  }
  submit.textContent = submit.dataset.label || submit.textContent;
  submit.disabled = false;
  submit.classList.remove('is-pending');
  form.classList.remove('is-pending');
}

function clearScannerImage() {
  if (scanPreviewUrl) URL.revokeObjectURL(scanPreviewUrl);
  scanPreviewUrl = '';
  $('#image').value = '';
  $('#file-name').textContent = '';
  const preview = $('#image-preview');
  preview.removeAttribute('src');
  preview.classList.add('hidden');
}

function resetScannerFlow() {
  const form = $('#scanner-form');
  const submit = $('#scan-submit');
  form.reset();
  form.classList.remove('is-pending');
  submit.disabled = false;
  submit.classList.remove('is-pending');
  submit.textContent = 'Procesar diagnóstico →';
  delete submit.dataset.label;
  clearScannerImage();
}

async function api(path, options = {}) {
  const headers = {
    ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
    ...(options.headers || {})
  };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.mensaje || 'No fue posible completar la solicitud.');
  return data;
}

function roleUI() {
  $$('.client').forEach(element => element.classList.toggle('hidden', !isMechanic()));
  $$('.customer-only').forEach(element => element.classList.toggle('hidden', !isCustomer()));
  $$('.admin-col').forEach(element => element.classList.toggle('hidden', !isMechanic()));
  $$('.mecanico-action').forEach(element => element.classList.toggle('hidden', !isMechanic()));
  $$('[data-client]').forEach(element => element.classList.toggle('hidden', !isCustomer()));
  $$('[data-admin]').forEach(element => element.classList.toggle('hidden', isCustomer()));

  $('.nav[data-view="motos"]').classList.toggle('hidden', !(isCustomer() || isMechanic()));
  $('.nav[data-view="inicio"]').classList.toggle('hidden', isMechanic() && !isWorkshopOwner());
  $('.nav[data-view="diagnosticos"]').classList.toggle('hidden', isCustomer());
  $('.nav[data-view="inventario"]').classList.toggle('hidden', !(isMechanic() || isAdmin()));
  $('.nav[data-view="mecanicos"]').classList.toggle('hidden', !isWorkshopOwner());
  $('#add-item').classList.toggle('hidden', !canManageInventory());
  $('#add-moto').classList.toggle('hidden', !(isCustomer() || isMechanic()));
  $$('.mechanic-field').forEach(element => {
    element.classList.toggle('hidden', !isMechanic());
    element.querySelector('input').required = isMechanic();
  });
  $('#user-role').textContent = isWorkshopOwner() ? 'Titular del taller' : isMechanic() ? 'Mecanico' : isAdmin() ? 'Administrador' : 'Cliente';
  $('#workshop-dashboard').classList.toggle('hidden', !isWorkshopOwner());
  $('#diagnostics-summary').classList.toggle('hidden', isMechanic());
  $('#home-heading').textContent = isWorkshopOwner() ? 'El taller, bajo control.' : 'Todo listo para rodar.';
  $('#welcome').textContent = isWorkshopOwner()
    ? 'Consulta la operación del taller y gestiona a tu equipo.'
    : isMechanic()
    ? 'Gestiona motos y procesa las lecturas del escaner.'
    : isAdmin()
      ? 'Supervisa motos y diagnosticos de toda la plataforma.'
      : 'Consulta los resultados y especificaciones de tus servicios.';
  $('#citas-subtitle').textContent = isMechanic()
    ? 'Consulta, edita o elimina las citas solicitadas por los clientes.'
    : 'Programa el servicio para una de tus motos y consulta el estado de la solicitud.';
}

function motoName(id, diagnostic) {
  if (diagnostic?.moto) return `${diagnostic.moto.marca} ${diagnostic.moto.modelo}`;
  const moto = state.motos.find(item => String(item.id) === String(id));
  return moto ? `${moto.marca} ${moto.modelo}` : `Moto #${id}`;
}

function renderMotos() {
  const body = $('#motos-body');
  body.innerHTML = '';
  $('#motos-empty').classList.toggle('hidden', state.motos.length > 0);
  state.motos.forEach(moto => {
    const row = document.createElement('tr');
    const tipo = moto.tipo_tecnologia === 'no_electronica' ? 'No electrónica' : 'Electrónica';
    const trabajo = moto.trabajo_actual;
    const estadosTrabajo = { recibida: 'Recibida', diagnostico: 'En diagnóstico', reparacion: 'En reparación', lista: 'Lista para entrega', entregada: 'Entregada' };
    const estadoTrabajo = trabajo
      ? `<span class="work-status ${escapeHtml(trabajo.estado)}">${estadosTrabajo[trabajo.estado] || escapeHtml(trabajo.estado)}</span><small>${escapeHtml(trabajo.numero)}</small>`
      : '<span class="work-status sin-orden">Sin orden de trabajo</span>';
    row.innerHTML = `<td>#${moto.id}</td><td>${escapeHtml(moto.marca)}</td><td>${escapeHtml(moto.modelo)}</td><td>${tipo}</td><td>${estadoTrabajo}</td>${isMechanic() ? `<td>${escapeHtml(moto.placa)}</td><td><button class="delete" data-delete="${moto.id}" aria-label="Eliminar moto">x</button></td>` : ''}`;
    body.append(row);
  });
  $('#moto-count').textContent = state.motos.length;
  fillSelect();
  renderMotoHealth();
  renderClientServiceHero();
}

function renderMotoHealth() {
  const target = $('#moto-health');
  if (!target || !isCustomer()) return;
  const priorityStates = {
    CRITICA: { label: 'Atención inmediata', health: 20, color: '#ee3d3b', action: 'Agenda una revisión urgente.' },
    ALTA: { label: 'Requiere revisión', health: 40, color: '#e2853c', action: 'Te recomendamos agendar servicio pronto.' },
    MEDIA: { label: 'Seguimiento recomendado', health: 65, color: '#d0a93f', action: 'Mantén esta moto bajo observación.' },
    BAJA: { label: 'En buen estado', health: 88, color: '#4f9a72', action: 'No hay acciones urgentes por ahora.' }
  };
  const diagnosticsByMoto = new Map();
  [...state.diags]
    .sort((first, second) => new Date(second.fecha || 0) - new Date(first.fecha || 0))
    .forEach(diag => {
      if (!diagnosticsByMoto.has(String(diag.moto_id))) diagnosticsByMoto.set(String(diag.moto_id), diag);
    });
  target.innerHTML = state.motos.map((moto, index) => {
    const diag = diagnosticsByMoto.get(String(moto.id));
    const stateInfo = diag
      ? priorityStates[(diag.prioridad || 'BAJA').toUpperCase()] || priorityStates.BAJA
      : { label: 'Sin diagnóstico', health: 100, color: '#77777d', action: 'Agenda una primera revisión para conocer su estado.' };
    const date = diag?.fecha
      ? new Date(diag.fecha).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' })
      : 'Aún sin revisión';
    const recommendation = diag?.recomendacion || stateInfo.action;
    const actionLabel = diag ? 'Ver resultado' : 'Agendar servicio';
    const actionView = diag ? 'resultados' : 'citas';
    return `<article class="moto-health-card" style="--health:${stateInfo.health}%;--health-color:${stateInfo.color};--health-delay:${index * 70}ms"><div class="moto-health-top"><div><p class="eyebrow">Estado de la moto</p><h3>${escapeHtml(moto.marca)} <em>${escapeHtml(moto.modelo)}</em></h3><small>${escapeHtml(moto.placa || 'Sin placa registrada')}</small></div><div class="moto-health-ring"><span>${stateInfo.health}<small>%</small></span></div></div><div class="moto-health-status"><i></i><strong>${stateInfo.label}</strong><time>Última revisión: ${date}</time></div><div class="moto-health-detail"><span>${diag ? 'Último resultado' : 'Siguiente paso'}</span><strong>${escapeHtml(diag?.codigo_error || 'Revisión pendiente')}</strong><p>${escapeHtml(recommendation)}</p></div><button class="text-btn moto-health-action" data-moto-action="${actionView}">${actionLabel} →</button></article>`;
  }).join('') || '<p class="empty panel">Registra tu primera moto para ver su ficha de estado.</p>';
}

function renderClientServiceHero() {
  const motoCount = $('#client-moto-count');
  if (!motoCount) return;
  motoCount.textContent = state.motos.length;
  $('#client-result-count').textContent = state.diags.length;
  const latest = state.diags[0]?.fecha;
  $('#client-latest-date').textContent = latest
    ? new Date(latest).toLocaleDateString('es-CO', { day: '2-digit', month: 'short' })
    : 'Pendiente';
  $('#client-service-status').textContent = state.diags.length
    ? 'Tus resultados están actualizados. Revisa las recomendaciones de tu último servicio.'
    : state.motos.length
      ? 'Aún no tienes servicios registrados. Agenda una revisión cuando tu moto lo necesite.'
      : 'Registra tu primera moto para centralizar sus servicios y diagnósticos.';
}

function renderRecent() {
  const target = $('#recent');
  if (!state.diags.length) {
    target.innerHTML = '<p class="empty">Aun no hay resultados de servicio.</p>';
    return;
  }
  target.innerHTML = state.diags.slice(0, 4).map(diag => `<article class="recent-diagnostic"><span class="badge">${escapeHtml(diag.codigo_error)}</span><div class="recent-diagnostic-info"><strong>${escapeHtml(motoName(diag.moto_id, diag))}</strong><p>${escapeHtml(diag.descripcion || 'Resultado de servicio')}</p></div><time>${diag.fecha ? new Date(diag.fecha).toLocaleDateString('es-CO') : '-'}</time></article>`).join('');
}

function renderResults() {
  renderClientServiceHero();
  const target = $('#resultados-list');
  if (!state.diags.length) {
    target.innerHTML = '<p class="empty">Aun no tienes resultados de servicio disponibles.</p>';
    return;
  }
  target.innerHTML = state.diags.map(diag => {
    const detalles = Array.isArray(diag.detalles) && diag.detalles.length
      ? diag.detalles
      : [{ codigo: diag.codigo_error, descripcion: diag.descripcion || 'Sin descripcion disponible.' }];
    const codigos = detalles.map(detalle => `<div class="client-result-code"><strong>${escapeHtml(detalle.codigo)}</strong><p>${escapeHtml(detalle.descripcion)}</p></div>`).join('');
    const fecha = diag.fecha ? new Date(diag.fecha).toLocaleDateString('es-CO', { day: '2-digit', month: 'long', year: 'numeric' }) : '-';
    return `<article class="client-result-card"><header><div><p class="eyebrow">Resultado del servicio</p><h3>${escapeHtml(motoName(diag.moto_id, diag))}${diag.moto?.placa ? ` - ${escapeHtml(diag.moto.placa)}` : ''}</h3></div><time>${fecha}</time></header><div class="client-result-codes">${codigos}</div></article>`;
  }).join('');
}

function renderDiagnostics() {
  const body = $('#diagnosticos-body');
  body.innerHTML = '';
  $('#diags-empty').classList.toggle('hidden', state.diags.length > 0);
  state.diags.forEach(diag => {
    const date = diag.fecha ? new Date(diag.fecha).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' }) : '-';
    const detalles = Array.isArray(diag.detalles) && diag.detalles.length
      ? diag.detalles
      : [{ codigo: diag.codigo_error, descripcion: diag.descripcion || 'Sin descripcion disponible.' }];
    const codigos = detalles.map(detalle => `<article class="diagnostic-code-block"><span>Codigo detectado</span><strong>${escapeHtml(detalle.codigo)}</strong><p>${escapeHtml(detalle.descripcion)}</p></article>`).join('');
    const card = document.createElement('article');
    card.className = 'diagnostic-card';
    card.innerHTML = `<div class="diagnostic-card-head"><small>Diagnostico #${diag.id}</small><time>${date}</time></div><div class="diagnostic-code-list">${codigos}</div><div class="diagnostic-card-foot"><div><span>Moto</span><strong>${escapeHtml(motoName(diag.moto_id, diag))}</strong></div>${isMechanic() ? `<button class="delete" data-delete-diagnostic="${diag.id}" aria-label="Eliminar diagnostico">x</button>` : ''}</div>`;
    body.append(card);
  });
  $('#diag-count').textContent = state.diags.length;
  renderMotoHealth();
  renderRecent();
  renderResults();
}

function renderPrioridades() {
  const body = $('#prioridades-body');
  body.innerHTML = '';
  $('#prioridades-empty').classList.toggle('hidden', state.prioridades.length > 0);
  state.prioridades.forEach(item => {
    const card = document.createElement('article');
    const priorityClass = (item.prioridad || 'BAJA').toLowerCase();
    card.className = `priority-card priority-${priorityClass}`;
    card.innerHTML = `<div class="priority-card-head"><span class="priority-pill">${escapeHtml(item.prioridad)}</span><time>${item.fecha ? new Date(item.fecha).toLocaleDateString('es-CO') : '-'}</time></div><div><p class="eyebrow">${escapeHtml(motoName(item.moto_id, item))}</p><h3>${escapeHtml(item.codigo_error)}</h3></div><p class="priority-reason">${escapeHtml(item.motivo_prioridad)}</p><div class="priority-recommendation"><span>Recomendación</span><p>${escapeHtml(item.recomendacion)}</p></div></article>`;
    body.append(card);
  });
}

function renderInventario() {
  const body = $('#inventario-body');
  body.innerHTML = '';
  $('#inventario-empty').classList.toggle('hidden', state.inventario.length > 0);
  state.inventario.forEach(item => {
    const labels = { disponible: 'Disponible', bajo: 'Stock bajo', agotado: 'Agotado' };
    const row = document.createElement('tr');
    const acciones = canManageInventory() ? `<button class="text-btn" data-edit-item="${item.id}">Editar</button><button class="delete" data-delete-item="${item.id}" aria-label="Eliminar ítem">x</button>` : '<small>Solo lectura</small>';
    row.innerHTML = `<td>#${item.id}</td><td><strong>${escapeHtml(item.nombre)}</strong>${item.proveedor ? `<br><small>${escapeHtml(item.proveedor)}</small>` : ''}</td><td>${escapeHtml(item.categoria)}</td><td>${item.cantidad} ${escapeHtml(item.unidad)}</td><td>${item.stock_minimo}</td><td><span class="inventory-status ${escapeHtml(item.estado)}">${labels[item.estado] || 'Disponible'}</span></td><td>${acciones}</td>`;
    body.append(row);
  });
  $('#inventario-count').textContent = state.inventario.length;
  $('#inventario-bajo-count').textContent = state.inventario.filter(item => item.estado !== 'disponible').length;
  $('#inventario-cat-count').textContent = new Set(state.inventario.map(item => item.categoria)).size;
}

function formatCurrency(value) {
  return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', minimumFractionDigits: 2 }).format(Number(value || 0));
}

function renderFacturas() {
  const cliente = isCustomer();
  const body = cliente ? $('#facturas-cliente-body') : $('#facturacion-body');
  const empty = cliente ? $('#facturas-cliente-empty') : $('#facturacion-empty');
  body.innerHTML = '';
  empty.classList.toggle('hidden', state.facturas.length > 0);
  state.facturas.forEach(factura => {
    const moto = factura.moto ? `${factura.moto.marca} ${factura.moto.modelo} - ${factura.moto.placa}` : '-';
    const row = document.createElement('tr');
    const estado = factura.estado === 'pagada' ? 'Pagada' : 'Pendiente';
    const base = `<td><strong>${escapeHtml(factura.numero)}</strong></td><td>${new Date(`${factura.fecha}T00:00:00`).toLocaleDateString('es-CO')}</td>`;
    if (cliente) {
      row.innerHTML = `${base}<td>${escapeHtml(moto)}</td><td>${formatCurrency(factura.total)}</td><td><span class="invoice-status ${escapeHtml(factura.estado)}">${estado}</span></td><td><button class="text-btn" data-download-factura="${factura.id}">Descargar PDF</button></td>`;
    } else {
      row.innerHTML = `${base}<td>${escapeHtml(factura.cliente?.nombre || '-')}</td><td>${escapeHtml(moto)}</td><td>${formatCurrency(factura.total)}</td><td><span class="invoice-status ${escapeHtml(factura.estado)}">${estado}</span></td><td><button class="text-btn" data-edit-factura="${factura.id}">Editar</button><button class="delete" data-delete-factura="${factura.id}" aria-label="Eliminar factura">x</button></td>`;
    }
    body.append(row);
  });
}

function fillSelect() {
  const select = $('#scan-moto');
  const electronicas = state.motos.filter(moto => moto.tipo_tecnologia !== 'no_electronica');
  select.innerHTML = '<option value="">Elige una moto electrónica</option>' + electronicas.map(moto => `<option value="${moto.id}">${escapeHtml(moto.marca)} ${escapeHtml(moto.modelo)}${moto.placa ? ` - ${escapeHtml(moto.placa)}` : ''}</option>`).join('');
}

function fillRevisionMotoSelect() {
  const select = $('#revision-moto');
  if (!select) return;
  const noElectronicas = state.motos.filter(moto => moto.tipo_tecnologia === 'no_electronica');
  select.innerHTML = '<option value="">Elige una moto no electrónica</option>' + noElectronicas.map(moto => `<option value="${moto.id}">${escapeHtml(moto.marca)} ${escapeHtml(moto.modelo)}${moto.placa ? ` - ${escapeHtml(moto.placa)}` : ''}</option>`).join('');
}

function fillCitaSelect(selected = '') {
  const select = $('#cita-moto');
  select.innerHTML = '<option value="">Elige una moto</option>' + state.motos.map(moto => `<option value="${moto.id}" ${String(moto.id) === String(selected) ? 'selected' : ''}>${escapeHtml(moto.marca)} ${escapeHtml(moto.modelo)} - ${escapeHtml(moto.placa)}</option>`).join('');
}

function renderCitas() {
  const body = $('#citas-body');
  body.innerHTML = '';
  $('#citas-empty').classList.toggle('hidden', state.citas.length > 0);
  state.citas.forEach(cita => {
    const row = document.createElement('tr');
    row.innerHTML = `<td>${new Date(`${cita.fecha}T00:00:00`).toLocaleDateString('es-CO')}</td><td>${escapeHtml(cita.moto ? `${cita.moto.marca} ${cita.moto.modelo}` : '-')}</td><td>${escapeHtml(cita.moto?.cliente || '-')}</td><td>${escapeHtml(cita.descripcion || '-')}</td>${isMechanic() ? `<td><button class="text-btn" data-edit-cita="${cita.id}">Editar</button><button class="delete" data-delete-cita="${cita.id}" aria-label="Eliminar cita">x</button></td>` : ''}`;
    body.append(row);
  });
}

async function loadMotos() {
  try {
    state.motos = await api((isMechanic() || isAdmin()) ? '/motos/detalle' : '/motos');
    renderMotos();
  } catch (error) { toast(error.message); }
}

async function loadDiagnostics() {
  try {
    state.diags = await api((isMechanic() || isAdmin()) ? '/diagnosticos' : '/mis_diagnosticos');
    renderDiagnostics();
  } catch (error) { toast(error.message); }
}

async function loadCitas() {
  try {
    state.citas = await api(isMechanic() ? '/citas/detalle' : '/mis_citas');
    renderCitas();
  } catch (error) { toast(error.message); }
}

async function loadPrioridades() {
  try {
    state.prioridades = await api('/prioridades');
    renderPrioridades();
  } catch (error) { toast(error.message); }
}

async function loadInventario() {
  try {
    state.inventario = await api('/inventario');
    renderInventario();
  } catch (error) { toast(error.message); }
}

async function loadFacturas() {
  try {
    state.facturas = await api(isCustomer() ? '/mis_facturas' : '/facturas');
    renderFacturas();
  } catch (error) { toast(error.message); }
}

function renderMecanicos() {
  const body = $('#mecanicos-body');
  body.innerHTML = '';
  $('#mecanicos-empty').classList.toggle('hidden', state.mecanicos.length > 0);
  state.mecanicos.forEach(mecanico => {
    const row = document.createElement('tr');
    row.innerHTML = `<td>${escapeHtml(mecanico.email)}</td><td><button class="delete" data-delete-mecanico="${mecanico.id}" aria-label="Eliminar mecánico">×</button></td>`;
    body.append(row);
  });
}

async function loadMecanicos() {
  try {
    state.mecanicos = await api('/mecanicos');
    renderMecanicos();
  } catch (error) { toast(error.message); }
}

async function loadCuenta() {
  try {
    const cuenta = await api('/mi-cuenta');
    $('#cuenta-email').value = cuenta.email || state.username;
  } catch (error) { toast(error.message); }
}

function renderOrdenes() {
  const body = $('#ordenes-body');
  body.innerHTML = '';
  $('#ordenes-empty').classList.toggle('hidden', state.ordenes.length > 0);
  const estados = { recibida: 'Recibida', diagnostico: 'En diagnóstico', reparacion: 'En reparación', lista: 'Lista', entregada: 'Entregada' };
  state.ordenes.forEach(orden => {
    const repuestos = orden.repuestos.length
      ? orden.repuestos.map(item => `${escapeHtml(item.nombre)} ×${item.cantidad}`).join('<br>')
      : '<small>Sin repuestos</small>';
    const row = document.createElement('tr');
    row.innerHTML = `<td><strong>${escapeHtml(orden.numero)}</strong></td><td>${escapeHtml(orden.moto?.marca)} ${escapeHtml(orden.moto?.modelo)}<br><small>${escapeHtml(orden.moto?.cliente || '')}</small></td><td>${escapeHtml(orden.descripcion)}</td><td>${repuestos}</td><td><select class="order-status" data-orden-estado="${orden.id}">${Object.entries(estados).map(([key, label]) => `<option value="${key}" ${orden.estado === key ? 'selected' : ''}>${label}</option>`).join('')}</select></td>`;
    body.append(row);
  });
}

async function loadOrdenes() {
  try {
    state.ordenes = await api('/ordenes-servicio');
    renderOrdenes();
  } catch (error) { toast(error.message); }
}

async function loadPanelTaller() {
  if (!isMechanic()) return;
  try {
    const panel = await api('/panel-taller');
    $('#moto-count').textContent = panel.servicios_mes;
    $('#diag-count').textContent = panel.ordenes_activas;
    $('#view-inicio .stats article:nth-child(1) [data-admin]').textContent = 'Servicios últimos 30 días';
    $('#view-inicio .stats article:nth-child(2) p').textContent = 'Órdenes activas';
    $('#view-inicio .stats article:nth-child(3) p').textContent = panel.stock_bajo ? `Stock bajo: ${panel.stock_bajo}` : 'Inventario al día';
    $('#view-inicio .stats article:nth-child(3) strong').textContent = formatCurrency(panel.ventas_mes);
    renderWorkshopDashboard(panel);
  } catch (error) { /* El resumen no debe impedir cargar el panel. */ }
}

function renderWorkshopDashboard(panel) {
  const estados = { recibida: 'Recibida', diagnostico: 'En diagnóstico', reparacion: 'En reparación', lista: 'Lista', entregada: 'Entregada' };
  const orders = panel.ordenes_recientes || [];
  $('#workshop-orders').innerHTML = orders.length
    ? orders.map(order => `<article class="workshop-row"><div><strong>${escapeHtml(order.numero)}</strong><p>${escapeHtml(order.moto?.marca)} ${escapeHtml(order.moto?.modelo)} · ${escapeHtml(order.moto?.cliente || 'Sin cliente')}</p></div><span class="workshop-status ${escapeHtml(order.estado)}">${estados[order.estado] || escapeHtml(order.estado)}</span></article>`).join('')
    : '<p class="empty">Aún no hay órdenes de servicio.</p>';
  const alerts = panel.alertas_inventario || [];
  $('#workshop-stock').innerHTML = alerts.length
    ? alerts.map(item => `<article class="workshop-row"><div><strong>${escapeHtml(item.nombre)}</strong><p>Mínimo: ${item.stock_minimo} ${escapeHtml(item.unidad)}</p></div><span class="stock-quantity">${item.cantidad} ${escapeHtml(item.unidad)}</span></article>`).join('')
    : '<p class="empty workshop-ok">✓ Inventario al día. No hay alertas de stock.</p>';
}

function show(view) {
  if (isMechanic() && !isWorkshopOwner() && view === 'inicio') view = 'ordenes';
  if (isCustomer() && !['inicio', 'resultados', 'citas', 'motos', 'facturas', 'cuenta'].includes(view)) view = 'resultados';
  if (!isMechanic() && view === 'scanner') view = 'inicio';
  if (view === 'mecanicos' && !isWorkshopOwner()) view = 'inicio';
  $$('.view').forEach(element => element.classList.toggle('active', element.id === `view-${view}`));
  $$('.nav').forEach(element => element.classList.toggle('active', element.dataset.view === view));
  const titles = { inicio: 'Resumen', resultados: 'Resultados del servicio', motos: 'Motos', citas: 'Citas', scanner: 'Escaner OCR', 'revision-mecanica': 'Revisión mecánica', prioridades: 'Prioridades', diagnosticos: 'Diagnosticos', inventario: 'Inventario', facturas: 'Mis facturas', facturacion: 'Facturación' };
  $('#title').textContent = view === 'mecanicos' ? 'Mi equipo' : view === 'cuenta' ? 'Ajustes de cuenta' : view === 'ordenes' ? 'Órdenes de servicio' : titles[view];
  $('#overline').textContent = isMechanic() ? 'Panel de mecanico' : isAdmin() ? 'Administracion' : 'Panel de cliente';
  $('#app-view').classList.remove('menu-open');
  if (view === 'motos') loadMotos();
  if (view === 'citas') { loadMotos().then(() => fillCitaSelect()); loadCitas(); }
  if (view === 'prioridades') loadPrioridades();
  if (view === 'diagnosticos' || view === 'resultados') loadDiagnostics();
  if (view === 'scanner') fillSelect();
  if (view === 'revision-mecanica') { loadMotos().then(fillRevisionMotoSelect); }
  if (view === 'inventario') loadInventario();
  if (view === 'mecanicos') loadMecanicos();
  if (view === 'cuenta') loadCuenta();
  if (view === 'ordenes') loadOrdenes();
  if (view === 'facturas' || view === 'facturacion') loadFacturas();
}

async function boot() {
  const payload = decode(state.token);
  state.role = state.role || payload.rol || 'cliente';
  state.isWorkshopOwner = Boolean(payload.es_titular_taller);
  state.username = state.username || payload.username || 'Usuario';
  localStorage.setItem('motosmart_role', state.role);
  $('#user-name').textContent = state.username;
  $('#initial').textContent = state.username.charAt(0).toUpperCase();
  roleUI();
  $('#auth-view').classList.add('hidden');
  $('#app-view').classList.remove('hidden');
  playGarageTransition();
  if (isCustomer()) window.setTimeout(playClientWelcome, 2350);
  await Promise.all([loadMotos(), loadDiagnostics()]);
  if (isWorkshopOwner()) await loadPanelTaller();
  if (isMechanic() && !isWorkshopOwner()) show('ordenes');
  else if (isCustomer()) show('resultados');
}

$$('[data-tab]').forEach(button => button.addEventListener('click', () => {
  const login = button.dataset.tab === 'login';
  $$('.tab').forEach(item => item.classList.toggle('active', item === button));
  $('#login-form').classList.toggle('hidden', !login);
  $('#register-form').classList.toggle('hidden', login);
}));

$('#login-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const data = await api('/login', { method: 'POST', body: JSON.stringify({ username: form.get('email'), password: form.get('password') }) });
    state.token = data.token;
    state.role = decode(data.token).rol || 'cliente';
    state.isWorkshopOwner = Boolean(decode(data.token).es_titular_taller);
    state.username = form.get('email').split('@')[0];
    localStorage.setItem('motosmart_token', state.token);
    localStorage.setItem('motosmart_role', state.role);
    localStorage.setItem('motosmart_username', state.username);
    await boot();
    toast(data.mensaje || 'Sesion iniciada.', 'success');
  } catch (error) { toast(error.message); }
});

$('#register-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const data = await api('/register', { method: 'POST', body: JSON.stringify({ username: form.get('email'), nombre: form.get('name') }) });
    toast(data.mensaje || 'Revisa tu correo para verificar la cuenta.', 'success');
    event.currentTarget.reset();
  } catch (error) { toast(error.message); }
});

$$('.nav').forEach(button => button.addEventListener('click', () => show(button.dataset.view)));
$$('[data-go]').forEach(button => button.addEventListener('click', () => show(button.dataset.go)));
$('#moto-health').addEventListener('click', event => {
  const action = event.target.closest('[data-moto-action]');
  if (action) show(action.dataset.motoAction);
});
$('#menu').addEventListener('click', () => $('#app-view').classList.toggle('menu-open'));
function logout() {
  ['motosmart_token', 'motosmart_role', 'motosmart_username'].forEach(key => localStorage.removeItem(key));
  location.reload();
}

function closeAccountMenu() {
  $('#account-menu').classList.add('hidden');
  $('#account-menu-button').setAttribute('aria-expanded', 'false');
}

$('#account-logout').addEventListener('click', logout);
$('#account-menu-button').addEventListener('click', () => {
  const menu = $('#account-menu');
  const isHidden = menu.classList.toggle('hidden');
  $('#account-menu-button').setAttribute('aria-expanded', String(!isHidden));
});
$('#account-menu [data-go]').addEventListener('click', event => {
  show(event.currentTarget.dataset.go);
  closeAccountMenu();
});
document.addEventListener('click', event => {
  if (!event.target.closest('.account-menu')) closeAccountMenu();
});
function openMotoModal() {
  $('#moto-form').reset();
  $('#moto-modal').showModal();
}

$('#add-moto').addEventListener('click', () => openMotoModal());
$('#moto-modal .close').addEventListener('click', () => $('#moto-modal').close());

function openCitaModal(cita = null) {
  fillCitaSelect(cita?.moto?.id || '');
  $('#cita-id').value = cita?.id || '';
  $('#cita-fecha').value = cita?.fecha || '';
  $('#cita-descripcion').value = cita?.descripcion || '';
  $('#cita-modal-label').textContent = cita ? 'Editar cita' : 'Nueva cita';
  $('#cita-modal-title').textContent = cita ? 'Actualiza el servicio' : 'Agendar servicio';
  $('#save-cita').textContent = cita ? 'Guardar cambios' : 'Agendar cita';
  $('#cita-modal').showModal();
}

$('#add-cita').addEventListener('click', async () => {
  await loadMotos();
  if (isCustomer() && !state.motos.length) {
    openAppointmentAfterMoto = true;
    toast('Primero registra tu moto para poder agendar la cita.', 'success');
    openMotoModal();
    return;
  }
  openCitaModal();
});
$$('.close-cita').forEach(button => button.addEventListener('click', () => $('#cita-modal').close()));

$('#moto-form').addEventListener('submit', async event => {
  event.preventDefault();
  setFormPending(event.currentTarget, true, 'Registrando moto...');
  try {
    const data = await api('/motos', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
    $('#moto-modal').close();
    event.currentTarget.reset();
    toast(data.mensaje || 'Moto registrada.', 'success');
    await loadMotos();
    if (openAppointmentAfterMoto) {
      openAppointmentAfterMoto = false;
      openCitaModal();
    }
  } catch (error) { toast(error.message); }
  finally { setFormPending(event.currentTarget, false); }
});

$('#motos-body').addEventListener('click', async event => {
  const button = event.target.closest('[data-delete]');
  if (!button || !confirm('Eliminar esta moto?')) return;
  try {
    const data = await api(`/motos/${button.dataset.delete}`, { method: 'DELETE' });
    toast(data.mensaje || 'Moto eliminada.', 'success');
    loadMotos();
  } catch (error) { toast(error.message); }
});

$('#cita-form').addEventListener('submit', async event => {
  event.preventDefault();
  const id = $('#cita-id').value;
  const data = Object.fromEntries(new FormData(event.currentTarget));
  setFormPending(event.currentTarget, true, id ? 'Guardando cambios...' : 'Agendando cita...');
  try {
    const response = await api(id ? `/citas/${id}` : '/citas', { method: id ? 'PUT' : 'POST', body: JSON.stringify(data) });
    $('#cita-modal').close();
    toast(response.mensaje || 'Cita guardada.', 'success');
    loadCitas();
  } catch (error) { toast(error.message); }
  finally { setFormPending(event.currentTarget, false); }
});

$('#citas-body').addEventListener('click', async event => {
  const edit = event.target.closest('[data-edit-cita]');
  if (edit) {
    const cita = state.citas.find(item => String(item.id) === edit.dataset.editCita);
    if (cita) openCitaModal(cita);
    return;
  }
  const remove = event.target.closest('[data-delete-cita]');
  if (!remove || !confirm('Eliminar esta cita?')) return;
  try {
    const response = await api(`/citas/${remove.dataset.deleteCita}`, { method: 'DELETE' });
    toast(response.mensaje || 'Cita eliminada.', 'success');
    loadCitas();
  } catch (error) { toast(error.message); }
});

$('#diagnosticos-body').addEventListener('click', async event => {
  const button = event.target.closest('[data-delete-diagnostic]');
  if (!button || !confirm('Eliminar este diagnostico?')) return;
  try {
    const response = await api(`/diagnosticos/${button.dataset.deleteDiagnostic}`, { method: 'DELETE' });
    toast(response.mensaje || 'Diagnostico eliminado.', 'success');
    loadDiagnostics();
  } catch (error) { toast(error.message); }
});

function openInventarioModal(item = null) {
  const form = $('#inventario-form');
  form.reset();
  $('#inventario-id').value = item?.id || '';
  if (item) {
    for (const field of ['nombre', 'categoria', 'unidad', 'cantidad', 'stock_minimo', 'proveedor']) {
      form.elements[field].value = item[field] ?? '';
    }
  }
  $('#inventario-modal .eyebrow').textContent = item ? 'Editar ítem' : 'Nuevo ítem';
  $('#inventario-modal h2').textContent = item ? 'Actualizar inventario' : 'Agregar al inventario';
  $('#save-item').textContent = item ? 'Guardar cambios' : 'Guardar ítem';
  $('#inventario-modal').showModal();
}

$('#add-item').addEventListener('click', () => openInventarioModal());
$$('.close-inventario').forEach(button => button.addEventListener('click', () => $('#inventario-modal').close()));

$('#inventario-form').addEventListener('submit', async event => {
  event.preventDefault();
  const id = $('#inventario-id').value;
  const data = Object.fromEntries(new FormData(event.currentTarget));
  setFormPending(event.currentTarget, true, id ? 'Actualizando inventario...' : 'Agregando al inventario...');
  try {
    const response = await api(id ? `/inventario/${id}` : '/inventario', {
      method: id ? 'PUT' : 'POST', body: JSON.stringify(data)
    });
    $('#inventario-modal').close();
    toast(response.mensaje || 'Ítem guardado.', 'success');
    loadInventario();
  } catch (error) { toast(error.message); }
  finally { setFormPending(event.currentTarget, false); }
});

$('#inventario-body').addEventListener('click', async event => {
  const edit = event.target.closest('[data-edit-item]');
  if (edit) {
    const item = state.inventario.find(candidate => String(candidate.id) === edit.dataset.editItem);
    if (item) openInventarioModal(item);
    return;
  }
  const remove = event.target.closest('[data-delete-item]');
  if (!remove || !confirm('¿Eliminar este ítem del inventario?')) return;
  try {
    const response = await api(`/inventario/${remove.dataset.deleteItem}`, { method: 'DELETE' });
    toast(response.mensaje || 'Ítem eliminado.', 'success');
    loadInventario();
  } catch (error) { toast(error.message); }
});

$('#cuenta-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const password = form.elements.password.value;
  if (password !== form.elements.password_confirm.value) {
    toast('Las contraseñas no coinciden.');
    return;
  }
  setFormPending(form, true, 'Guardando cambios...');
  try {
    await api('/mi-cuenta', { method: 'PUT', body: JSON.stringify({ password }) });
    form.elements.password.value = '';
    form.elements.password_confirm.value = '';
    toast(response.mensaje || 'Cuenta actualizada.', 'success');
  } catch (error) { toast(error.message); }
  finally { setFormPending(form, false); }
});

function renderOrdenRepuesto() {
  const row = document.createElement('div');
  row.className = 'order-part-row';
  row.innerHTML = `<select class="orden-repuesto-item"><option value="">Selecciona un repuesto</option>${state.inventario.map(item => `<option value="${item.id}">${escapeHtml(item.nombre)} (${item.cantidad} ${escapeHtml(item.unidad)})</option>`).join('')}</select><input class="orden-repuesto-cantidad" type="number" min="1" step="1" value="1" aria-label="Cantidad"><button class="delete remove-orden-repuesto" type="button" aria-label="Quitar repuesto">×</button>`;
  $('#orden-repuestos').append(row);
}

async function openOrdenModal() {
  await Promise.all([loadMotos(), loadInventario()]);
  const select = $('#orden-moto');
  select.innerHTML = '<option value="">Elige una moto</option>' + state.motos.map(moto => `<option value="${moto.id}">${escapeHtml(moto.marca)} ${escapeHtml(moto.modelo)} - ${escapeHtml(moto.placa)}</option>`).join('');
  $('#orden-form').reset();
  $('#orden-repuestos').innerHTML = '';
  $('#orden-modal').showModal();
}

$('#add-orden').addEventListener('click', openOrdenModal);
$('#add-orden-repuesto').addEventListener('click', renderOrdenRepuesto);
$$('.close-orden').forEach(button => button.addEventListener('click', () => $('#orden-modal').close()));
$('#orden-repuestos').addEventListener('click', event => event.target.closest('.remove-orden-repuesto')?.parentElement.remove());

$('#orden-form').addEventListener('submit', async event => {
  event.preventDefault();
  const repuestos = [...document.querySelectorAll('.order-part-row')]
    .map(row => ({ inventario_id: row.querySelector('.orden-repuesto-item').value, cantidad: row.querySelector('.orden-repuesto-cantidad').value }))
    .filter(item => item.inventario_id);
  setFormPending(event.currentTarget, true, 'Creando orden...');
  try {
    const data = Object.fromEntries(new FormData(event.currentTarget));
    data.repuestos = repuestos;
    const response = await api('/ordenes-servicio', { method: 'POST', body: JSON.stringify(data) });
    $('#orden-modal').close();
    toast(response.mensaje || 'Orden creada.', 'success');
    await Promise.all([loadOrdenes(), loadInventario(), loadPanelTaller()]);
  } catch (error) { toast(error.message); }
  finally { setFormPending(event.currentTarget, false); }
});

$('#ordenes-body').addEventListener('change', async event => {
  const select = event.target.closest('[data-orden-estado]');
  if (!select) return;
  try {
    const response = await api(`/ordenes-servicio/${select.dataset.ordenEstado}/estado`, { method: 'PUT', body: JSON.stringify({ estado: select.value }) });
    toast(response.notificacion_enviada ? 'Estado actualizado y cliente notificado.' : (response.mensaje || 'Estado actualizado.'), 'success');
    loadOrdenes();
    loadPanelTaller();
  } catch (error) { toast(error.message); loadOrdenes(); }
});

$('#mecanico-form').addEventListener('submit', async event => {
  event.preventDefault();
  setFormPending(event.currentTarget, true, 'Agregando mecánico...');
  try {
    const response = await api('/mecanicos', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
    event.currentTarget.reset();
    toast(response.mensaje || 'Mecánico agregado.', 'success');
    loadMecanicos();
  } catch (error) { toast(error.message); }
  finally { setFormPending(event.currentTarget, false); }
});

$('#mecanicos-body').addEventListener('click', async event => {
  const remove = event.target.closest('[data-delete-mecanico]');
  if (!remove || !confirm('¿Eliminar el acceso de este mecánico?')) return;
  try {
    const response = await api(`/mecanicos/${remove.dataset.deleteMecanico}`, { method: 'DELETE' });
    toast(response.mensaje || 'Acceso eliminado.', 'success');
    loadMecanicos();
  } catch (error) { toast(error.message); }
});

function fillFacturaMoto(selected = '') {
  const select = $('#factura-moto');
  select.innerHTML = '<option value="">Elige una moto</option>' + state.motos.map(moto =>
    `<option value="${moto.id}" ${String(moto.id) === String(selected) ? 'selected' : ''}>${escapeHtml(moto.marca)} ${escapeHtml(moto.modelo)} - ${escapeHtml(moto.placa)}</option>`
  ).join('');
}

async function openFacturaModal(factura = null) {
  await loadMotos();
  const form = $('#factura-form');
  form.reset();
  $('#factura-id').value = factura?.id || '';
  fillFacturaMoto(factura?.moto?.id || '');
  form.elements.fecha.value = factura?.fecha || new Date().toISOString().slice(0, 10);
  form.elements.estado.value = factura?.estado || 'pendiente';
  form.elements.descripcion.value = factura?.descripcion || '';
  form.elements.subtotal.value = factura?.subtotal || '';
  form.elements.iva.value = factura?.iva || '19';
  $('#factura-modal .eyebrow').textContent = factura ? 'Editar factura' : 'Nueva factura';
  $('#factura-modal h2').textContent = factura ? 'Actualizar factura' : 'Crear factura';
  $('#save-factura').textContent = factura ? 'Guardar cambios' : 'Crear factura';
  $('#factura-modal').showModal();
}

$('#add-factura').addEventListener('click', () => openFacturaModal());
$$('.close-factura').forEach(button => button.addEventListener('click', () => $('#factura-modal').close()));

$('#factura-form').addEventListener('submit', async event => {
  event.preventDefault();
  const id = $('#factura-id').value;
  const data = Object.fromEntries(new FormData(event.currentTarget));
  setFormPending(event.currentTarget, true, id ? 'Actualizando factura...' : 'Creando factura...');
  try {
    const response = await api(id ? `/facturas/${id}` : '/facturas', {
      method: id ? 'PUT' : 'POST', body: JSON.stringify(data)
    });
    $('#factura-modal').close();
    toast(response.mensaje || 'Factura guardada.', 'success');
    loadFacturas();
  } catch (error) { toast(error.message); }
  finally { setFormPending(event.currentTarget, false); }
});

$('#facturacion-body').addEventListener('click', async event => {
  const edit = event.target.closest('[data-edit-factura]');
  if (edit) {
    const factura = state.facturas.find(item => String(item.id) === edit.dataset.editFactura);
    if (factura) openFacturaModal(factura);
    return;
  }
  const remove = event.target.closest('[data-delete-factura]');
  if (!remove || !confirm('¿Eliminar esta factura?')) return;
  try {
    const response = await api(`/facturas/${remove.dataset.deleteFactura}`, { method: 'DELETE' });
    toast(response.mensaje || 'Factura eliminada.', 'success');
    loadFacturas();
  } catch (error) { toast(error.message); }
});

async function descargarFactura(id) {
  try {
    const response = await fetch(`/facturas/${id}/pdf`, { headers: { Authorization: `Bearer ${state.token}` } });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || 'No fue posible descargar la factura.');
    }
    const factura = state.facturas.find(item => String(item.id) === String(id));
    const enlace = document.createElement('a');
    enlace.href = URL.createObjectURL(await response.blob());
    enlace.download = `${factura?.numero || 'factura'}.pdf`;
    enlace.click();
    URL.revokeObjectURL(enlace.href);
  } catch (error) { toast(error.message); }
}

$('#facturas-cliente-body').addEventListener('click', event => {
  const download = event.target.closest('[data-download-factura]');
  if (download) descargarFactura(download.dataset.downloadFactura);
});

$('#revision-mecanica-form').addEventListener('submit', async event => {
  event.preventDefault();
  setFormPending(event.currentTarget, true, 'Guardando revisión...');
  try {
    const data = Object.fromEntries(new FormData(event.currentTarget));
    const response = await api('/revisiones-mecanicas', { method: 'POST', body: JSON.stringify(data) });
    event.currentTarget.reset();
    fillRevisionMotoSelect();
    toast(response.mensaje || 'Revisión mecánica guardada.', 'success');
    await loadDiagnostics();
  } catch (error) { toast(error.message); }
  finally { setFormPending(event.currentTarget, false); }
});

$('#image').addEventListener('change', event => {
  const file = event.target.files[0];
  const preview = $('#image-preview');
  if (!file) {
    clearScannerImage();
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    toast('La imagen supera el limite de 10 MB.');
    clearScannerImage();
    return;
  }
  if (scanPreviewUrl) URL.revokeObjectURL(scanPreviewUrl);
  $('#file-name').textContent = file.name;
  scanPreviewUrl = URL.createObjectURL(file);
  preview.src = scanPreviewUrl;
  preview.classList.remove('hidden');
});
$('#scanner-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!$('#image').files[0]) { toast('Selecciona una imagen antes de procesar.'); return; }
  setFormPending(event.currentTarget, true, 'Analizando lectura...');
  try {
    const data = await api('/upload_scanner', { method: 'POST', body: new FormData(event.currentTarget) });
    const detalles = Array.isArray(data.detalles) && data.detalles.length
      ? data.detalles
      : [{ codigo: data.codigo_error || 'SIN_CODIGO', descripcion: data.descripcion || 'Sin descripcion disponible.' }];
    $('#ocr-text').textContent = 'Codigos y descripciones detectados';
    $('#ocr-description').innerHTML = detalles.map(detalle => `<div class="ocr-detail"><strong>${escapeHtml(detalle.codigo)}</strong><span>${escapeHtml(detalle.descripcion)}</span></div>`).join('');
    $('#ocr-result').classList.remove('hidden');
    $('#ocr-result').classList.remove('result-reveal');
    requestAnimationFrame(() => $('#ocr-result').classList.add('result-reveal'));
    $('#view-scanner .scanner').classList.add('hidden');
    $('#scanner-complete').classList.remove('hidden');
    toast(data.mensaje || 'Diagnostico guardado.', 'success');
    resetScannerFlow();
    loadDiagnostics();
  } catch (error) { toast(error.message); }
  finally {
    setFormPending(event.currentTarget, false);
  }
});

$('#new-scan').addEventListener('click', () => {
  resetScannerFlow();
  $('#scanner-complete').classList.add('hidden');
  $('#view-scanner .scanner').classList.remove('hidden');
  $('#ocr-result').classList.add('hidden');
  fillSelect();
});

if (state.token) boot();
