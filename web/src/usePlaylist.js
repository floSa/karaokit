import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";

// État de la playlist partagé avec le serveur. Interroge /api/playlist toutes les
// 1,5 s tant qu'un titre est en préparation, sinon toutes les 15 s.
export default function usePlaylist() {
  const [items, setItems] = useState([]);
  const [error, setError] = useState(null);
  const timer = useRef(0);

  const apply = useCallback((data) => {
    if (data?.items) setItems(data.items);
    setError(null);
  }, []);

  const refresh = useCallback(async () => {
    clearTimeout(timer.current);
    let busy = false;
    try {
      const data = await api("/api/playlist");
      apply(data);
      busy = data.items.some((it) => it.state === "queued" || it.state === "processing");
    } catch (e) {
      setError("Serveur injoignable — lance : uv run karaoke serve");
    }
    timer.current = setTimeout(refresh, busy ? 1500 : 15000);
  }, [apply]);

  useEffect(() => {
    refresh();
    return () => clearTimeout(timer.current);
  }, [refresh]);

  const add = useCallback(async ({ slugs = [], paths = [], language = null }) => {
    const data = await api("/api/playlist", { method: "POST", body: JSON.stringify({ slugs, paths, language }) });
    apply(data);
    refresh();
    return data.added;
  }, [apply, refresh]);

  const remove = useCallback(async (id) => {
    setItems((its) => its.filter((it) => it.id !== id));
    apply(await api(`/api/playlist/${id}`, { method: "DELETE" }).catch(() => null));
  }, [apply]);

  const reorder = useCallback(async (ids) => {
    setItems((its) => ids.map((id) => its.find((it) => it.id === id)).filter(Boolean));
    apply(await api("/api/playlist", { method: "PUT", body: JSON.stringify({ ids }) }).catch(() => null));
  }, [apply]);

  const clear = useCallback(async () => {
    setItems([]);
    apply(await api("/api/playlist", { method: "DELETE" }).catch(() => null));
  }, [apply]);

  return { items, error, add, remove, reorder, clear, refresh };
}
