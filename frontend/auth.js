// Código de acesso do operador (definido no servidor). Fica só na sessão da aba (sessionStorage), nunca em arquivo.
// A tela do visitante não usa este módulo para o chat: só as ações do operador passam por authFetch.

const KEY = "senac_operator_token";

function stored() {
  try {
    return window.sessionStorage.getItem(KEY) || "";
  } catch {
    return "";
  }
}

function store(value) {
  try {
    if (value) window.sessionStorage.setItem(KEY, value);
    else window.sessionStorage.removeItem(KEY);
  } catch {
    // sem armazenamento: o código será pedido de novo quando necessário
  }
}

function withToken(options, token) {
  const headers = { ...(options.headers || {}) };
  if (token) headers["X-Operator-Token"] = token;
  return { ...options, headers };
}

// fetch para rotas do operador: envia o código guardado e, se o servidor responder 401, pede o código uma vez e repete.
export async function authFetch(url, options = {}) {
  let response = await fetch(url, withToken(options, stored()));
  if (response.status === 401) {
    const typed = window.prompt("Código de acesso do operador:");
    if (typed) {
      store(typed.trim());
      response = await fetch(url, withToken(options, stored()));
      if (response.status === 401) store("");
    }
  }
  return response;
}
