import { useEffect, useState } from "react";
import KaraokePlayer from "./KaraokePlayer.jsx";

// Le morceau choisi est dans l'URL (#/slug) : rechargement et lien direct
// (téléphone, TV) ouvrent directement le lecteur.
const slugFromHash = () => decodeURIComponent(window.location.hash.replace(/^#\/?/, ""));

// Écran d'accueil : liste la bibliothèque (library/index.json) puis, une fois
// un morceau choisi, affiche le lecteur karaoké.
export default function App() {
  const [songs, setSongs] = useState(null);
  const [selected, setSelected] = useState(slugFromHash);
  const [error, setError] = useState(null);

  useEffect(() => {
    const onHash = () => setSelected(slugFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    fetch("/library/index.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("index.json absent"))))
      .then(setSongs)
      .catch(() => {
        setSongs([]);
        setError(
          "Bibliothèque vide. Traite un morceau avec :  uv run karaoke build \"morceau.flac\""
        );
      });
  }, []);

  const open = (slug) => { window.location.hash = `/${encodeURIComponent(slug)}`; };
  const back = () => { window.location.hash = ""; };

  if (selected) {
    return <KaraokePlayer key={selected} slug={selected} onBack={back} />;
  }

  return (
    <div className="home">
      <h1>🎤 Karaokit</h1>
      {error && <p className="hint">{error}</p>}
      {songs === null && <p className="hint">Chargement…</p>}
      {songs && songs.length > 0 && (
        <ul className="songlist">
          {songs.map((s) => (
            <li key={s.slug}>
              <button onClick={() => open(s.slug)}>
                <span className="badge">{s.hasLyrics ? "🎤" : "🎹"}</span>
                <span className="song-title">{s.title || s.slug}</span>
                {s.artist && <span className="song-artist">{s.artist}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
