import { useState } from "react";

const STATE_ICON = { ready: "", queued: "⏳", processing: null, error: "⚠", missing: "⚠", cancelled: "✕" };

// Colonne de gauche : la playlist. Glisser-déposer pour réordonner, ✕ pour
// retirer, clic sur un titre prêt pour le chanter.
export default function Playlist({ playlist, currentId, onPlay, autoNext, setAutoNext }) {
  const { items, error, remove, reorder, clear } = playlist;
  const [dragId, setDragId] = useState(null);
  const [overIndex, setOverIndex] = useState(null);

  const drop = () => {
    if (dragId === null || overIndex === null) return reset();
    const ids = items.map((it) => it.id).filter((id) => id !== dragId);
    const from = items.findIndex((it) => it.id === dragId);
    const target = overIndex > from ? overIndex - 1 : overIndex;
    ids.splice(target, 0, dragId);
    reorder(ids);
    reset();
  };
  const reset = () => { setDragId(null); setOverIndex(null); };

  const ready = items.filter((it) => it.state === "ready").length;
  const busy = items.filter((it) => it.state === "queued" || it.state === "processing").length;

  return (
    <aside className="sidebar">
      <div className="side-head">
        <h2>Playlist</h2>
        <span className="side-count">
          {items.length} titre{items.length > 1 ? "s" : ""}
          {busy > 0 && ` · ${busy} en préparation`}
        </span>
      </div>

      {error && <p className="hint small">{error}</p>}
      {!items.length && !error && (
        <p className="hint small">
          Vide pour l'instant. Cherche un morceau au centre et ajoute-le avec « + ».
        </p>
      )}

      <ol className="pl" onDragOver={(e) => e.preventDefault()} onDrop={drop}>
        {items.map((it, i) => (
          <li
            key={it.id}
            className={[
              "pl-item", it.state,
              it.id === currentId ? "current" : "",
              it.id === dragId ? "dragging" : "",
              overIndex === i && dragId !== null ? "drop-before" : "",
            ].join(" ")}
            draggable
            onDragStart={(e) => { setDragId(it.id); e.dataTransfer.effectAllowed = "move"; }}
            onDragOver={(e) => {
              e.preventDefault();
              const box = e.currentTarget.getBoundingClientRect();
              setOverIndex(e.clientY > box.top + box.height / 2 ? i + 1 : i);
            }}
            onDragEnd={reset}
          >
            <span className="grip" aria-hidden>⋮⋮</span>
            <button
              className="pl-main"
              disabled={it.state !== "ready"}
              onClick={() => onPlay(it)}
              title={it.state === "ready" ? "Chanter" : it.label}
            >
              <span className="pl-title">
                {it.id === currentId && <span className="now-icon">▶ </span>}
                {it.title}
              </span>
              <span className="pl-sub">
                {it.state === "ready" ? (
                  it.artist || "prêt"
                ) : (
                  <>
                    {it.state === "processing" ? <span className="spinner" aria-hidden /> : STATE_ICON[it.state]}{" "}
                    {it.label}
                    {it.elapsed != null && ` · ${it.elapsed} s`}
                  </>
                )}
              </span>
            </button>
            <button className="pl-remove" onClick={() => remove(it.id)} aria-label={`Retirer ${it.title}`}>✕</button>
          </li>
        ))}
        {dragId !== null && overIndex === items.length && <li className="drop-end" />}
      </ol>

      {items.length > 0 && (
        <div className="side-foot">
          <label className="toggle">
            <input type="checkbox" checked={autoNext} onChange={(e) => setAutoNext(e.target.checked)} />
            Enchaîner les titres
          </label>
          <span className="side-count">{ready} prêt{ready > 1 ? "s" : ""}</span>
          <button className="linkbtn" onClick={clear}>Vider</button>
        </div>
      )}
    </aside>
  );
}
