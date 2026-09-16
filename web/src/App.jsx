import { useCallback, useEffect, useRef, useState } from "react";
import Home from "./Home.jsx";
import KaraokePlayer from "./KaraokePlayer.jsx";
import Playlist from "./Playlist.jsx";
import usePlaylist from "./usePlaylist.js";

// Mise en page : playlist à gauche (toujours là), et au centre soit la
// recherche / bibliothèque, soit le lecteur. URL : #/<slug> = lecteur,
// #/:parcourir = explorateur (« : » ne peut pas apparaître dans un slug).
const BROWSE = ":parcourir";
const routeFromHash = () => decodeURIComponent(window.location.hash.replace(/^#\/?/, ""));
const go = (route) => { window.location.hash = route ? `/${encodeURIComponent(route)}` : ""; };

export default function App() {
  const [route, setRoute] = useState(routeFromHash);
  const [library, setLibrary] = useState([]);
  const [currentId, setCurrentId] = useState(null); // élément de playlist en lecture
  const [autoNext, setAutoNext] = useState(true);
  const [sideOpen, setSideOpen] = useState(true);
  const playlist = usePlaylist();

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // La bibliothèque se recharge quand le nombre de titres prêts change.
  const readyCount = playlist.items.filter((it) => it.state === "ready").length;
  useEffect(() => {
    fetch("/library/index.json", { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : []))
      .then(setLibrary)
      .catch(() => setLibrary([]));
  }, [readyCount]);

  const slug = route && route !== BROWSE ? route : null;

  // Lecture lancée hors playlist (lien direct, bibliothèque) : plus d'élément courant.
  const itemsRef = useRef(playlist.items);
  itemsRef.current = playlist.items;
  useEffect(() => {
    const cur = itemsRef.current.find((it) => it.id === currentId);
    if (!slug || (cur && cur.slug !== slug)) setCurrentId(null);
  }, [slug]); // eslint-disable-line react-hooks/exhaustive-deps

  const playItem = useCallback((it) => {
    setCurrentId(it.id);
    go(it.slug);
  }, []);

  // Fin de chanson : prochain titre PRÊT après le courant (les titres encore en
  // préparation sont sautés).
  const onEnded = useCallback(() => {
    if (!autoNext) return;
    const items = itemsRef.current;
    const idx = items.findIndex((it) => it.id === currentId);
    if (idx < 0) return;
    const next = items.slice(idx + 1).find((it) => it.state === "ready");
    if (next) playItem(next);
  }, [autoNext, currentId, playItem]);

  const current = playlist.items.find((it) => it.id === currentId);
  const upNext = current
    ? playlist.items.slice(playlist.items.indexOf(current) + 1).find((it) => it.state === "ready")
    : null;

  return (
    <div className={`app${sideOpen ? "" : " side-closed"}`}>
      {sideOpen && (
        <Playlist playlist={playlist} currentId={currentId} onPlay={playItem} autoNext={autoNext} setAutoNext={setAutoNext} />
      )}
      <main className="main">
        <button className="side-toggle" onClick={() => setSideOpen((o) => !o)} title={sideOpen ? "Masquer la playlist" : "Afficher la playlist"}>
          {sideOpen ? "⟨" : "☰"}
        </button>
        {slug ? (
          <KaraokePlayer
            key={`${slug}-${currentId ?? "x"}`}
            slug={slug}
            autoPlay={currentId !== null}
            onBack={() => go("")}
            onEnded={onEnded}
            upNext={autoNext && upNext ? upNext.title : null}
          />
        ) : (
          <>
            <header className="brand">
              <h1>🎤 Karaokit</h1>
            </header>
            <Home
              library={library}
              onAdd={playlist.add}
              onPlaySlug={(s) => go(s)}
              initialTab={route === BROWSE ? "browse" : "library"}
            />
          </>
        )}
      </main>
    </div>
  );
}
