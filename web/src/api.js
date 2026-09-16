// En dev (Vite:5173) l'API tourne sur le serveur Python (8765) ; servi par
// `karaoke serve`, c'est la même origine.
export const apiBase =
  typeof window !== "undefined" && window.location.port === "5173"
    ? `http://${window.location.hostname}:8765`
    : "";

export async function api(path, options = {}) {
  const r = await fetch(`${apiBase}${path}`, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json", ...options.headers } : options.headers,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}
