import { useEffect, useState } from "react";
import KaraokePlayer from "./KaraokePlayer.jsx";

// Écran d'accueil : liste la bibliothèque (library/index.json) puis, une fois
// un morceau choisi, affiche le lecteur karaoké.
export default function App() {
  const [songs, setSongs] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch("/library/index.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("index.json absent"))))
      .then(setSongs)
      .catch(() => {
        setSongs([]);
        setError(
          "Bibliothèque vide. Traite un morceau avec :  python -m karaoke build \"morceau.flac\""
        );
      });
  }, []);

  if (selected) {
    return <KaraokePlayer slug={selected} onBack={() => setSelected(null)} />;
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
              <button onClick={() => setSelected(s.slug)}>
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
