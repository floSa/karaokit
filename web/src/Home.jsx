import { useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import Browser from "./Browser.jsx";

// Zone centrale : recherche (bibliothèque + ordinateur), bibliothèque complète,
// explorateur de dossiers. Chaque résultat s'ajoute à la playlist.
export default function Home({ library, onAdd, onPlaySlug, initialTab = "library" }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [tab, setTab] = useState(initialTab);
  const [selected, setSelected] = useState(() => new Set()); // slugs "lib:<slug>" ou chemins
  const [language, setLanguage] = useState("");
  const [toast, setToast] = useState("");

  useEffect(() => setTab(initialTab), [initialTab]);

  // Recherche avec anti-rebond (250 ms).
  useEffect(() => {
    const q = query.trim();
    if (!q) { setResults(null); return; }
    const t = setTimeout(() => {
      api(`/api/search?q=${encodeURIComponent(q)}`).then(setResults).catch(() => setResults({ library: [], files: [] }));
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  const toggle = (key) => setSelected((s) => {
    const n = new Set(s);
    n.has(key) ? n.delete(key) : n.add(key);
    return n;
  });

  const add = async (payload) => {
    try {
      const n = await onAdd({ ...payload, language: language || null });
      setToast(`${n} titre${n > 1 ? "s" : ""} ajouté${n > 1 ? "s" : ""} à la playlist`);
    } catch (e) {
      setToast(`Échec : ${e.message}`);
    }
    setTimeout(() => setToast(""), 2500);
  };
  const addSelection = async () => {
    const keys = [...selected];
    await add({
      slugs: keys.filter((k) => k.startsWith("lib:")).map((k) => k.slice(4)),
      paths: keys.filter((k) => !k.startsWith("lib:")),
    });
    setSelected(new Set());
  };

  const libraryRows = useMemo(() => (results ? results.library : library), [results, library]);

  return (
    <div className="center">
      <div className="search">
        <input
          autoFocus
          type="search"
          placeholder="Rechercher un titre ou un artiste…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {!results && (
        <nav className="tabs">
          <button className={tab === "library" ? "on" : ""} onClick={() => setTab("library")}>Bibliothèque ({library.length})</button>
          <button className={tab === "browse" ? "on" : ""} onClick={() => setTab("browse")}>Parcourir l'ordinateur</button>
        </nav>
      )}

      {(results || tab === "library") && (
        <section>
          {results && <h3>Prêts à chanter <span className="count">{results.library.length}</span></h3>}
          {!libraryRows.length && (
            <p className="hint">{results ? "Aucun titre de la bibliothèque ne correspond." : "Bibliothèque vide : cherche un morceau sur l'ordinateur."}</p>
          )}
          <ul className="rows">
            {libraryRows.map((s) => (
              <li key={s.slug} className={`row${selected.has(`lib:${s.slug}`) ? " picked" : ""}`}>
                <input type="checkbox" checked={selected.has(`lib:${s.slug}`)} onChange={() => toggle(`lib:${s.slug}`)} aria-label="Sélectionner" />
                <button className="row-main" onClick={() => onPlaySlug(s.slug)} title="Chanter maintenant">
                  <span className="row-title">{s.title || s.slug}</span>
                  {s.artist && <span className="row-sub">{s.artist}</span>}
                </button>
                <button className="add-btn" onClick={() => add({ slugs: [s.slug] })} aria-label={`Ajouter ${s.title}`}>+</button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {results && (
        <section>
          <h3>
            Sur l'ordinateur <span className="count">{results.files.length}{results.files.length >= 60 ? "+" : ""}</span>
            {results.index?.scanning && <span className="hint small"> · indexation en cours…</span>}
          </h3>
          {!results.files.length && <p className="hint">Aucun fichier ne correspond.</p>}
          <ul className="rows">
            {results.files.map((f) => (
              <li key={f.path} className={`row${selected.has(f.path) ? " picked" : ""}`}>
                <input type="checkbox" checked={selected.has(f.path)} onChange={() => toggle(f.path)} aria-label="Sélectionner" />
                <label className="row-main" onClick={() => toggle(f.path)}>
                  <span className="row-title">{f.name.replace(/\.[^.]+$/, "")}</span>
                  <span className="row-sub" title={f.folder}>{f.folder.split(/[\\/]/).slice(-2).join(" › ")}</span>
                </label>
                <button className="add-btn" onClick={() => add({ paths: [f.path] })} aria-label={`Ajouter ${f.name}`}>+</button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!results && tab === "browse" && <Browser selected={selected} toggle={toggle} onAdd={add} />}

      {(selected.size > 0 || toast) && (
        <div className="selbar">
          {selected.size > 0 ? (
            <>
              <span>{selected.size} sélectionné{selected.size > 1 ? "s" : ""}</span>
              <label className="lang">
                langue
                <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                  <option value="">auto</option>
                  <option value="fr">français</option>
                  <option value="en">anglais</option>
                  <option value="de">allemand</option>
                  <option value="es">espagnol</option>
                  <option value="it">italien</option>
                </select>
              </label>
              <button className="linkbtn" onClick={() => setSelected(new Set())}>annuler</button>
              <button className="primary-sm" onClick={addSelection}>+ Ajouter à la playlist</button>
            </>
          ) : (
            <span>{toast}</span>
          )}
        </div>
      )}
    </div>
  );
}
