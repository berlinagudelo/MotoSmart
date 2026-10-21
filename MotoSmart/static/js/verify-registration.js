const form = document.querySelector('#verify-registration-form');
const status = document.querySelector('#verification-status');
const hash = window.location.hash.slice(1);
const isEmailChange = hash.startsWith('email=');
const isClaim = hash.startsWith('claim=');
const token = isEmailChange
  ? hash.slice('email='.length)
  : isClaim
    ? hash.slice('claim='.length)
    : hash;
window.history.replaceState(null, '', window.location.pathname);

if (isEmailChange) {
  document.querySelector('.form-heading h1').textContent = 'Confirma tu nuevo correo';
  document.querySelector('.form-heading p').textContent = 'Confirma que controlas esta dirección para aplicar el cambio.';
  form.querySelectorAll('label').forEach(label => { label.hidden = true; });
  form.querySelectorAll('input').forEach(input => { input.disabled = true; });
  form.querySelector('button').textContent = 'Confirmar cambio de correo';
}

if (isClaim) {
  document.querySelector('.form-heading h1').textContent = 'Conecta tus datos del taller';
  document.querySelector('.form-heading p').textContent = 'La contraseña que elegiste al registrarte se conservará.';
  form.querySelectorAll('label').forEach(label => { label.hidden = true; });
  form.querySelectorAll('input').forEach(input => { input.disabled = true; });
  form.querySelector('button').textContent = 'Verificar correo y conectar datos';
}

if (!token) {
  status.textContent = 'El enlace no es válido. Solicita uno nuevo desde MotoSmart.';
  form.hidden = true;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (isEmailChange) {
    const button = form.querySelector('button');
    button.disabled = true;
    status.textContent = 'Verificando correo...';
    try {
      const response = await fetch('/mi-cuenta/verificar-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.mensaje || 'No fue posible verificar el correo.');
      form.hidden = true;
      status.textContent = `${data.mensaje} Inicia sesión de nuevo para actualizar la aplicación.`;
    } catch (error) {
      status.textContent = error.message;
      button.disabled = false;
    }
    return;
  }

  if (!token) {
    status.textContent = 'El enlace no es válido. Solicita uno nuevo desde MotoSmart.';
    form.hidden = true;
    return;
  }

  const button = form.querySelector('button');
  button.disabled = true;
  status.textContent = 'Verificando correo...';
  try {
    const password = form.elements.password.value;
    if (!isClaim && password !== form.elements.password_confirm.value) {
      throw new Error('Las contraseñas no coinciden.');
    }
    const response = await fetch('/register/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, password })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.mensaje || 'No fue posible verificar el correo.');
    form.hidden = true;
    status.textContent = `${data.mensaje} Inicia sesión desde la página principal.`;
  } catch (error) {
    status.textContent = error.message;
    button.disabled = false;
  }
});
