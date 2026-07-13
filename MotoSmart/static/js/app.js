const state = {
  token: localStorage.getItem('motosmart_token'),
  role: localStorage.getItem('motosmart_role'),
  username: localStorage.getItem('motosmart_username'),
  motos: [],
  diags: [],
  citas: [],
  prioridades: []
};

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const isAdmin = () => state.role === 'admin';
const isMechanic = () => state.role === 'mecanico';
const isCustomer = () => state.role === 'cliente';
let openAppointmentAfterMoto = false;

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
  setTimeout(() => element.remove(), 4200);
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
  $('.nav[data-view="diagnosticos"]').classList.toggle('hidden', isCustomer());
  $('#add-moto').classList.toggle('hidden', !(isCustomer() || isMechanic()));
  $$('.mechanic-field').forEach(element => {
    element.classList.toggle('hidden', !isMechanic());
    element.querySelector('input').required = isMechanic();
  });
  $('#user-role').textContent = isMechanic() ? 'Mecanico' : isAdmin() ? 'Administrador' : 'Cliente';
  $('#welcome').textContent = isMechanic()
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
    row.innerHTML = `<td>#${moto.id}</td><td>${escapeHtml(moto.marca)}</td><td>${escapeHtml(moto.modelo)}</td>${isMechanic() ? `<td>${escapeHtml(moto.placa)}</td><td><button class="delete" data-delete="${moto.id}" aria-label="Eliminar moto">x</button></td>` : ''}`;
    body.append(row);
  });
  $('#moto-count').textContent = state.motos.length;
  fillSelect();
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

function fillSelect() {
  const select = $('#scan-moto');
  select.innerHTML = '<option value="">Elige una moto</option>' + state.motos.map(moto => `<option value="${moto.id}">${escapeHtml(moto.marca)} ${escapeHtml(moto.modelo)}${moto.placa ? ` - ${escapeHtml(moto.placa)}` : ''}</option>`).join('');
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

function show(view) {
  if (isCustomer() && !['inicio', 'resultados', 'citas', 'motos'].includes(view)) view = 'resultados';
  if (!isMechanic() && view === 'scanner') view = 'inicio';
  $$('.view').forEach(element => element.classList.toggle('active', element.id === `view-${view}`));
  $$('.nav').forEach(element => element.classList.toggle('active', element.dataset.view === view));
  const titles = { inicio: 'Resumen', resultados: 'Resultados del servicio', motos: 'Motos', citas: 'Citas', scanner: 'Escaner OCR', prioridades: 'Prioridades', diagnosticos: 'Diagnosticos' };
  $('#title').textContent = titles[view];
  $('#overline').textContent = isMechanic() ? 'Panel de mecanico' : isAdmin() ? 'Administracion' : 'Panel de cliente';
  $('#app-view').classList.remove('menu-open');
  if (view === 'motos') loadMotos();
  if (view === 'citas') { loadMotos().then(() => fillCitaSelect()); loadCitas(); }
  if (view === 'prioridades') loadPrioridades();
  if (view === 'diagnosticos' || view === 'resultados') loadDiagnostics();
  if (view === 'scanner') fillSelect();
}

async function boot() {
  const payload = decode(state.token);
  state.role = state.role || payload.rol || 'cliente';
  state.username = state.username || payload.username || 'Usuario';
  localStorage.setItem('motosmart_role', state.role);
  $('#user-name').textContent = state.username;
  $('#initial').textContent = state.username.charAt(0).toUpperCase();
  roleUI();
  $('#auth-view').classList.add('hidden');
  $('#app-view').classList.remove('hidden');
  await Promise.all([loadMotos(), loadDiagnostics()]);
  if (isCustomer()) show('resultados');
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
    const data = await api('/register', { method: 'POST', body: JSON.stringify({ username: form.get('email'), password: form.get('password'), nombre: form.get('name'), rol: form.get('role') }) });
    toast(data.mensaje || 'Cuenta creada. Ya puedes iniciar sesion.', 'success');
    document.querySelector('[data-tab="login"]').click();
    $('#login-form [name="email"]').value = form.get('email');
    event.currentTarget.reset();
  } catch (error) { toast(error.message); }
});

$$('.nav').forEach(button => button.addEventListener('click', () => show(button.dataset.view)));
$$('[data-go]').forEach(button => button.addEventListener('click', () => show(button.dataset.go)));
$('#menu').addEventListener('click', () => $('#app-view').classList.toggle('menu-open'));
$('#logout').addEventListener('click', () => { ['motosmart_token', 'motosmart_role', 'motosmart_username'].forEach(key => localStorage.removeItem(key)); location.reload(); });
function openMotoModal() {
  $('#moto-form').reset();
  $('#moto-modal').showModal();
}

$('#add-moto').addEventListener('click', () => openMotoModal());
$$('.close').forEach(button => button.addEventListener('click', () => $('#moto-modal').close()));

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
  try {
    const response = await api(id ? `/citas/${id}` : '/citas', { method: id ? 'PUT' : 'POST', body: JSON.stringify(data) });
    $('#cita-modal').close();
    toast(response.mensaje || 'Cita guardada.', 'success');
    loadCitas();
  } catch (error) { toast(error.message); }
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

$('#image').addEventListener('change', event => {
  const file = event.target.files[0];
  const preview = $('#image-preview');
  if (!file) {
    $('#file-name').textContent = '';
    preview.classList.add('hidden');
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    toast('La imagen supera el limite de 10 MB.');
    event.target.value = '';
    preview.classList.add('hidden');
    return;
  }
  $('#file-name').textContent = file.name;
  preview.src = URL.createObjectURL(file);
  preview.classList.remove('hidden');
});
$('#scanner-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!$('#image').files[0]) { toast('Selecciona una imagen antes de procesar.'); return; }
  const submit = $('#scan-submit');
  submit.disabled = true;
  submit.textContent = 'Procesando imagen...';
  try {
    const data = await api('/upload_scanner', { method: 'POST', body: new FormData(event.currentTarget) });
    const detalles = Array.isArray(data.detalles) && data.detalles.length
      ? data.detalles
      : [{ codigo: data.codigo_error || 'SIN_CODIGO', descripcion: data.descripcion || 'Sin descripcion disponible.' }];
    $('#ocr-text').textContent = 'Codigos y descripciones detectados';
    $('#ocr-description').innerHTML = detalles.map(detalle => `<div class="ocr-detail"><strong>${escapeHtml(detalle.codigo)}</strong><span>${escapeHtml(detalle.descripcion)}</span></div>`).join('');
    $('#ocr-result').classList.remove('hidden');
    toast(data.mensaje || 'Diagnostico guardado.', 'success');
    event.currentTarget.reset();
    $('#file-name').textContent = '';
    $('#image-preview').classList.add('hidden');
    loadDiagnostics();
  } catch (error) { toast(error.message); }
  finally {
    submit.disabled = false;
    submit.textContent = 'Procesar diagnostico ->';
  }
});

if (state.token) boot();
