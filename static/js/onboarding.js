const landing = document.querySelector('#landing-view');
const authView = document.querySelector('#auth-view');
const workshopView = document.querySelector('#workshop-view');
const workshopSelect = document.querySelector('#register-workshop');
const registerWorkshopMessage = document.querySelector('#register-workshop-message');

function mostrarAcceso(tab) {
  landing.classList.add('hidden');
  workshopView.classList.add('hidden');
  authView.classList.remove('hidden');
  document.querySelector(`[data-tab="${tab}"]`).click();
}

async function cargarTalleresRegistro() {
  try {
    const response = await fetch('/talleres');
    const talleres = await response.json();
    if (!response.ok) throw new Error(talleres.error || 'No fue posible cargar los talleres.');
    workshopSelect.replaceChildren(new Option('Selecciona tu taller', ''));
    talleres.forEach(taller => {
      const option = new Option(`${taller.nombre} · ${taller.ciudad}`, taller.id);
      workshopSelect.add(option);
    });
    if (!talleres.length) {
      registerWorkshopMessage.textContent = 'Aún no hay talleres registrados. Puedes crear uno desde el inicio.';
      workshopSelect.disabled = true;
    }
  } catch (error) {
    workshopSelect.replaceChildren(new Option('No se pudieron cargar los talleres', ''));
    workshopSelect.disabled = true;
    registerWorkshopMessage.textContent = error.message;
  }
}

document.querySelectorAll('[data-open-auth]').forEach(button => {
  button.addEventListener('click', () => mostrarAcceso(button.dataset.openAuth));
});

document.querySelector('[data-open-workshop]').addEventListener('click', () => {
  landing.classList.add('hidden');
  authView.classList.add('hidden');
  workshopView.classList.remove('hidden');
});

document.querySelectorAll('[data-back-landing]').forEach(button => {
  button.addEventListener('click', () => {
    authView.classList.add('hidden');
    workshopView.classList.add('hidden');
    landing.classList.remove('hidden');
  });
});

document.querySelector('#workshop-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const status = document.querySelector('#workshop-status');
  const button = form.querySelector('button[type="submit"], button:not([type])');
  button.disabled = true;
  status.textContent = 'Creando el taller...';
  const values = new FormData(form);
  try {
    const response = await fetch('/talleres', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.fromEntries(values)),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'No fue posible crear el taller.');
    if (response.status === 202) {
      // El taller se crea cuando el titular confirma su correo.
      status.textContent = data.mensaje || 'Revisa tu correo para confirmar la creación del taller.';
      form.reset();
      button.disabled = false;
      return;
    }
    // El servidor deja la sesión en una cookie HttpOnly; nunca se guarda el token.
    location.reload();
  } catch (error) {
    status.textContent = error.message;
    button.disabled = false;
  }
});

cargarTalleresRegistro();
