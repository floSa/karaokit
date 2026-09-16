import { useEffect, useState } from "react";
import { api } from "./api.js";
import Icon from "./Icon.jsx";

// Explorateur des dossiers de musique de l'ordinateur. Cocher des fichiers ou
// « + album » puis les ajouter à la playlist (ils seront préparés en karaoké).
export default function Browser({ selected, toggle, onAdd }) {
  const [path, setPath] = useState(null);
  const [dir, setDir] = useState(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    setFilter("");
    api(`/api/music${path ? `?path=${encodeURIComponent(path)}` : ""}`)
      .then((d) => { setDir(d); setError(null); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [path]);

  const f = filter.trim().toLowerCase();
  const dirs = dir ? dir.dirs.filter((d) => !f || d.name.toLowerCase().includes(f)) : [];
  const files = dir ? dir.files.filter((d) => !f || d.name.toLowerCase().includes(f)) : [];
  const isRoots = dir && dir.path === null;

  return (
    <div className="browser">
      <div className="crumbs">
        <button className="linkbtn" disabled={!dir?.path} onClick={() => setPath(dir.parent)}><Icon name="back" size={14} /> Dossier parent</button>
        <span className="crumb-path" title={dir?.path || ""}><bdi>{dir?.path || "Dossiers de musique"}</bdi></span>
      </div>
      <input className="filter" placeholder="Filtrer ce dossier…" value={filter} onChange={(e) => setFilter(e.target.value)} />
      {error && <p className="hint">{error}</p>}
      {loading && <p className="hint">Chargement…</p>}
      {dir && !loading && (
        <ul className="rows">
          {isRoots && !dirs.length && <li className="hint">Aucun dossier de musique — lance le serveur avec --music DOSSIER.</li>}
          {dirs.map((d) => (
            <li key={d.path} className="row">
              <button className="row-main" onClick={() => setPath(d.path)}><span className="row-title">{d.name}</span><Icon name="chevron" size={14} className="dim" /></button>
              {!isRoots && (
                <button className="add-btn" onClick={() => onAdd({ paths: [d.path] })} title="Ajouter tout le dossier à la playlist">+ Album</button>
              )}
            </li>
          ))}
          {files.map((file) => (
            <li key={file.path} className={`row${selected.has(file.path) ? " picked" : ""}`}>
              <label className="row-main">
                <input type="checkbox" checked={selected.has(file.path)} onChange={() => toggle(file.path)} />
                <span className="row-title">{file.name}</span>
              </label>
              <button className="add-btn" onClick={() => onAdd({ paths: [file.path] })} aria-label={`Ajouter ${file.name}`}>+</button>
            </li>
          ))}
          {!isRoots && !dirs.length && !files.length && <li className="hint">Dossier vide.</li>}
        </ul>
      )}
    </div>
  );
}
