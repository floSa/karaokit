import { useEffect, useRef, useState } from "react";

// Lecteur karaoké : joue l'instrumental (+ voix-guide optionnelle) et surligne
// les paroles mot-à-mot en fonction du temps de lecture.
export default function KaraokePlayer({ slug, onBack }) {
  const [data, setData] = useState(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [guideVol, setGuideVol] = useState(0); // volume de la voix-guide (0 = off)
  const [editing, setEditing] = useState(false);
  const [editLines, setEditLines] = useState(null);
  const [selIdx, setSelIdx] = useState(-1);
  const [saveMsg, setSaveMsg] = useState("");

  // En dev (Vite:5173) l'API de sauvegarde tourne sur le serveur Python (8765) ;
  // servi par `karaoke serve`, c'est la même origine.
  const apiBase =
    typeof window !== "undefined" && window.location.port === "5173"
      ? `http://${window.location.hostname}:8765`
      : "";

  const instruRef = useRef(null);
  const vocalsRef = useRef(null);
  const rafRef = useRef(0);
  const activeLineRef = useRef(null);

  const base = `/library/${slug}`;

  useEffect(() => {
    fetch(`${base}/karaoke.json`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => setData({ error: true }));
  }, [base]);

  // Boucle d'animation : suit le temps de l'instrumental (le maître).
  useEffect(() => {
    const tick = () => {
      const instru = instruRef.current;
      const vocals = vocalsRef.current;
      if (instru) {
        setTime(instru.currentTime);
        // Garde la voix-guide synchronisée avec l'instrumental.
        if (vocals && Math.abs(vocals.currentTime - instru.currentTime) > 0.25) {
          vocals.currentTime = instru.currentTime;
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  // Applique le volume de la voix-guide.
  useEffect(() => {
    if (vocalsRef.current) vocalsRef.current.volume = guideVol;
  }, [guideVol]);

  // Raccourcis clavier : espace = play/pause, flèches = ±5 s, Début = retour.
  useEffect(() => {
    const onKey = (e) => {
      const instru = instruRef.current;
      const vocals = vocalsRef.current;
      if (!instru) return;
      const syncSeek = (t) => {
        instru.currentTime = t;
        if (vocals) vocals.currentTime = t;
        setTime(t);
      };
      if (e.code === "Space") {
        e.preventDefault();
        if (instru.paused) {
          instru.play();
          if (vocals) { vocals.currentTime = instru.currentTime; vocals.play(); }
          setPlaying(true);
        } else {
          instru.pause();
          if (vocals) vocals.pause();
          setPlaying(false);
        }
      } else if (e.code === "ArrowRight") {
        syncSeek(Math.min(instru.duration || 1e9, instru.currentTime + 5));
      } else if (e.code === "ArrowLeft") {
        syncSeek(Math.max(0, instru.currentTime - 5));
      } else if (e.code === "Home") {
        syncSeek(0);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const lines = editing && editLines ? editLines : data?.lines ?? [];
  const activeIndex = findActiveLine(lines, time);
  const preroll = editing ? null : computePreroll(lines, activeIndex, time, playing);

  // --- Édition de la synchro ---
  const enterEdit = () => {
    setEditLines(JSON.parse(JSON.stringify(data.lines || [])));
    setSelIdx(-1);
    setSaveMsg("");
    setEditing(true);
  };
  const cancelEdit = () => { setEditing(false); setEditLines(null); };
  const shiftAll = (delta) => setEditLines((ls) => ls.map((l) => shiftLine(l, delta)));
  const setLineHere = () => {
    if (selIdx < 0) return;
    setEditLines((ls) => ls.map((l, i) => (i === selIdx ? shiftLine(l, time - l.start) : l)));
  };
  const save = async () => {
    try {
      const r = await fetch(`${apiBase}/api/save/${slug}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lines: editLines }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      setData((d) => ({ ...d, lines: editLines }));
      setEditing(false);
      setEditLines(null);
      setSaveMsg("Enregistré ✓");
    } catch (e) {
      setSaveMsg("Échec : " + e.message + " — lance le serveur : python -m karaoke serve");
    }
  };

  // Auto-scroll de la ligne active au centre.
  useEffect(() => {
    if (activeLineRef.current) {
      activeLineRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [activeIndex]);

  const togglePlay = () => {
    const instru = instruRef.current;
    const vocals = vocalsRef.current;
    if (!instru) return;
    if (instru.paused) {
      instru.play();
      if (vocals) {
        vocals.currentTime = instru.currentTime;
        vocals.play();
      }
      setPlaying(true);
    } else {
      instru.pause();
      if (vocals) vocals.pause();
      setPlaying(false);
    }
  };

  const seek = (e) => {
    const t = Number(e.target.value);
    if (instruRef.current) instruRef.current.currentTime = t;
    if (vocalsRef.current) vocalsRef.current.currentTime = t;
    setTime(t);
  };

  if (!data) return <div className="player"><p className="hint">Chargement…</p></div>;
  if (data.error) return <div className="player"><p className="hint">Morceau introuvable.</p></div>;

  return (
    <div className="player">
      <header className="player-head">
        <button className="back" onClick={onBack}>← Retour</button>
        <div className="now">
          <strong>{data.title}</strong>
          {data.artist && <span> — {data.artist}</span>}
        </div>
        <div className="src">{data.lyrics_source}</div>
        {saveMsg && <span className="savemsg">{saveMsg}</span>}
        {data.video && !editing && (
          <a className="dl" href={`${base}/${data.video}`} download>⬇︎ vidéo</a>
        )}
        <button className="back" onClick={editing ? cancelEdit : enterEdit}>
          {editing ? "✕ Annuler" : "✎ Éditer"}
        </button>
      </header>

      {editing && (
        <div className="edittools">
          <span>Décalage global :</span>
          <button onClick={() => shiftAll(-0.1)}>−0,1 s</button>
          <button onClick={() => shiftAll(0.1)}>+0,1 s</button>
          <span className="sep">|</span>
          <button disabled={selIdx < 0} onClick={setLineHere}>
            ⇩ Caler la ligne ici ({fmt(time)})
          </button>
          <span className="hint2">
            {selIdx >= 0 ? `ligne ${selIdx + 1} sélectionnée` : "clique une ligne pour la sélectionner"}
          </span>
          <span className="sep">|</span>
          <button className="save" onClick={save}>💾 Enregistrer</button>
        </div>
      )}

      <div className="lyrics">
        {lines.length === 0 && <p className="hint">Pas de paroles (karaoké instrumental).</p>}
        {lines.map((line, i) => (
          <Line
            key={i}
            line={line}
            time={time}
            state={i === activeIndex ? "active" : i < activeIndex ? "past" : "future"}
            innerRef={i === activeIndex ? activeLineRef : null}
            selected={editing && i === selIdx}
            onClick={editing ? () => setSelIdx(i) : undefined}
          />
        ))}
      </div>

      {preroll !== null && <PreRoll progress={preroll} />}

      <div className="controls">
        <button className="play" onClick={togglePlay}>{playing ? "⏸" : "▶"}</button>
        <span className="tc">{fmt(time)}</span>
        <input
          className="scrub"
          type="range"
          min={0}
          max={duration || 0}
          step={0.01}
          value={time}
          onChange={seek}
        />
        <span className="tc">{fmt(duration)}</span>
        <label className="guide">
          🎙 guide
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={guideVol}
            onChange={(e) => setGuideVol(Number(e.target.value))}
          />
        </label>
      </div>

      <audio
        ref={instruRef}
        src={`${base}/${data.instrumental}`}
        onLoadedMetadata={(e) => setDuration(e.target.duration)}
        onEnded={() => setPlaying(false)}
        preload="auto"
      />
      <audio ref={vocalsRef} src={`${base}/${data.vocals}`} preload="auto" />
    </div>
  );
}

// Décale une ligne (et ses mots) de `d` secondes.
function shiftLine(l, d) {
  const clamp = (x) => Math.max(0, x + d);
  return {
    ...l,
    start: clamp(l.start),
    end: clamp(l.end),
    words: l.words.map((w) => ({ ...w, start: clamp(w.start), end: clamp(w.end) })),
  };
}

function Line({ line, time, state, innerRef, selected, onClick }) {
  return (
    <p
      ref={innerRef}
      className={`line ${state}${selected ? " selected" : ""}`}
      onClick={onClick}
      style={onClick ? { cursor: "pointer" } : undefined}
    >
      {line.words.map((w, i) => {
        let cls = "word";
        if (time >= w.end) cls += " sung";
        else if (time >= w.start) cls += " singing";
        return (
          <span key={i} className={cls}>
            {w.text}{" "}
          </span>
        );
      })}
    </p>
  );
}

// Trois pastilles qui se remplissent à l'approche de la prochaine ligne.
function PreRoll({ progress }) {
  const filled = Math.min(3, Math.floor(progress * 3) + 1);
  return (
    <div className="preroll" aria-hidden>
      {[0, 1, 2].map((i) => (
        <span key={i} className={"dot" + (i < filled ? " on" : "")} />
      ))}
    </div>
  );
}

// Renvoie un ratio 0→1 pendant un « trou » instrumental avant la prochaine
// ligne (intro, interlude), ou null s'il n'y a pas lieu d'afficher de compte à rebours.
function computePreroll(lines, activeIndex, t, playing) {
  if (!playing) return null;
  const next = lines[activeIndex + 1];
  if (!next) return null;
  const gapStart = activeIndex >= 0 ? lines[activeIndex].end : 0;
  const gap = next.start - gapStart;
  if (gap < 2.5) return null; // trou trop court, inutile
  if (t < gapStart || t >= next.start) return null;
  return (t - gapStart) / (next.start - gapStart);
}

function findActiveLine(lines, t) {
  let idx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].start <= t) idx = i;
    else break;
  }
  return idx;
}

function fmt(s) {
  if (!s || Number.isNaN(s)) return "0:00";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}
