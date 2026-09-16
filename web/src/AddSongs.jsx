import { useEffect, useState } from "react";
import { api } from "./api.js";

// Explorateur de la musique de l'ordinateur : on coche des morceaux (ou des
// albums entiers), ils rejoignent la liste à traiter, puis « Lancer » les envoie
// dans la file de traitement du serveur.
export default function AddSongs({ onSubmitted }) {
  const [dir, setDir] = useState(null); // réponse de /api/music
  const [path, setPath] = useState(null);
  const [filter, setFilter] = useState("");
  const [playlist, setPlaylist] = useState([]); // [{path, name, kind}]
  const [language, setLanguage] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    setLoading(true);
    setFilter("");
    api(`/api/music${path ? `?path=${encodeURIComponent(path)}` : ""}`)
      .then((d) => { setDir(d); setError(null); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [path]);

  const inList = (p) => playlist.some((x) => x.path === p);
  const toggle = (item, kind) =>
    setPlaylist((pl) => (inList(item.path) ? pl.filter((x) => x.path !== item.path) : [...pl, { ...item, kind }]));
  const addAllFiles = () =>
    setPlaylist((pl) => [...pl, ...shown.files.filter((f) => !inList(f.path)).map((f) => ({ ...f, kind: "file" }))]);

  const send = async () => {
    setSending(true);
    try {
      const r = await api("/api/jobs", {
        method: "POST",
        body: JSON.stringify({ paths: playlist.map((x) => x.path), language: language || null }),
      });
      setPlaylist([]);
      onSubmitted?.(r);
    } catch (e) {
      setError(e.message);
    } finally {
      setSending(false);
    }
  };

  const f = filter.trim().toLowerCase();
  const shown = dir && {
    dirs: dir.dirs.filter((d) => !f || d.name.toLowerCase().includes(f)),
    files: dir.files.filter((d) => !f || d.name.toLowerCase().includes(f)),
  };
  const isRoots = dir && dir.path === null;

  return (
    <div className="add">
      <div className="browser">
        <div className="crumbs">
          <button className="linkbtn" disabled={!dir?.path} onClick={() => setPath(dir.parent)}>⬑ dossier parent</button>
          <span className="crumb-path" title={dir?.path || ""}><bdi>{dir?.path || "Dossiers de musique"}</bdi></span>
        </div>
        <input className="filter" placeholder="Filtrer ce dossier…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        {error && <p className="hint">⚠ {error}</p>}
        {loading && <p className="hint">Chargement…</p>}
        {shown && !loading && (
          <ul className="entries">
            {isRoots && !shown.dirs.length && (
              <li className="hint">Aucun dossier de musique trouvé — lance le serveur avec --music DOSSIER.</li>
            )}
            {shown.dirs.map((d) => (
              <li key={d.path} className="entry dir">
                <button className="entry-open" onClick={() => setPath(d.path)}>📁 {d.name}</button>
                {!isRoots && (
                  <button className={`pick${inList(d.path) ? " on" : ""}`} onClick={() => toggle(d, "dir")}
                    title="Ajouter tout le dossier (album)">{inList(d.path) ? "✓ album" : "+ album"}</button>
                )}
              </li>
            ))}
            {shown.files.map((file) => (
              <li key={file.path} className="entry file">
                <label>
                  <input type="checkbox" checked={inList(file.path)} onChange={() => toggle(file, "file")} />
                  🎵 {file.name}
                </label>
              </li>
            ))}
            {!isRoots && !shown.dirs.length && !shown.files.length && <li className="hint">Dossier vide.</li>}
          </ul>
        )}
        {shown?.files.length > 1 && (
          <button className="linkbtn" onClick={addAllFiles}>+ ajouter les {shown.files.length} morceaux affichés</button>
        )}
      </div>

      <aside className="playlist">
        <h2>À traiter ({playlist.length})</h2>
        {!playlist.length && <p className="hint">Coche des morceaux ou ajoute un album entier.</p>}
        <ol>
          {playlist.map((x) => (
            <li key={x.path}>
              <span>{x.kind === "dir" ? "📁" : "🎵"} {x.name}</span>
              <button className="linkbtn" onClick={() => toggle(x, x.kind)} aria-label="Retirer">✕</button>
            </li>
          ))}
        </ol>
        <label className="lang">
          Langue
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="">détection auto</option>
            <option value="fr">français</option>
            <option value="en">anglais</option>
            <option value="de">allemand</option>
            <option value="es">espagnol</option>
            <option value="it">italien</option>
          </select>
        </label>
        <button className="primary" disabled={!playlist.length || sending} onClick={send}>
          {sending ? "Envoi…" : `🎤 Créer ${playlist.length > 1 ? "les karaokés" : "le karaoké"}`}
        </button>
      </aside>
    </div>
  );
}
