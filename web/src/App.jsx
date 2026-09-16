import { useCallback, useEffect, useState } from "react";
import AddSongs from "./AddSongs.jsx";
import JobsPanel from "./JobsPanel.jsx";
import KaraokePlayer from "./KaraokePlayer.jsx";

// Routage par l'URL : #/<slug> = lecteur, #/:ajouter = ajout de morceaux
// (« : » ne peut pas apparaître dans un slug). Rechargement et lien direct
// (téléphone, TV) ouvrent le bon écran.
const ADD = ":ajouter";
const routeFromHash = () => decodeURIComponent(window.location.hash.replace(/^#\/?/, ""));
const go = (route) => { window.location.hash = route ? `/${encodeURIComponent(route)}` : ""; };

export default function App() {
  const [songs, setSongs] = useState(null);
  const [route, setRoute] = useState(routeFromHash);
  const [error, setError] = useState(null);
  const [libVersion, setLibVersion] = useState(0);
  const [jobsKey, setJobsKey] = useState(0);

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    fetch("/library/index.json", { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("index.json absent"))))
      .then((list) => { setSongs(list); setError(null); })
      .catch(() => {
        setSongs([]);
        setError("Bibliothèque vide. Ajoute des morceaux avec « ➕ Ajouter des morceaux ».");
      });
  }, [libVersion]);

  const reloadLibrary = useCallback(() => setLibVersion((v) => v + 1), []);

  if (route && route !== ADD) {
    return <KaraokePlayer key={route} slug={route} onBack={() => go("")} />;
  }

  const adding = route === ADD;
  return (
    <div className={`home${adding ? " wide" : ""}`}>
      <header className="home-head">
        <h1>🎤 Karaokit</h1>
        <nav className="tabs">
          <button className={adding ? "" : "on"} onClick={() => go("")}>Bibliothèque</button>
          <button className={adding ? "on" : ""} onClick={() => go(ADD)}>➕ Ajouter des morceaux</button>
        </nav>
      </header>

      <JobsPanel refreshKey={jobsKey} onSongReady={reloadLibrary} onOpen={(slug) => go(slug)} />

      {adding ? (
        <AddSongs onSubmitted={() => setJobsKey((k) => k + 1)} />
      ) : (
        <>
          {error && <p className="hint">{error}</p>}
          {songs === null && <p className="hint">Chargement…</p>}
          {songs && songs.length > 0 && (
            <ul className="songlist">
              {songs.map((s) => (
                <li key={s.slug}>
                  <button onClick={() => go(s.slug)}>
                    <span className="badge">{s.hasLyrics ? "🎤" : "🎹"}</span>
                    <span className="song-title">{s.title || s.slug}</span>
                    {s.artist && <span className="song-artist">{s.artist}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
