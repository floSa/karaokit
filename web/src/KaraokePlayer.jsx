import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiBase } from "./api.js";

// Lecteur karaoké : joue l'instrumental (+ voix-guide optionnelle) et surligne
// les paroles mot-à-mot en fonction du temps de lecture.
//
// Performance : la boucle d'animation lit l'horloge audio à chaque image mais
// React ne se re-rend que lorsqu'un MOT change (~3 fois/s), plus 4 fois/s pour
// le compteur et la barre. Le remplissage progressif du mot en cours est une
// animation CSS (durée = durée du mot, délai négatif = déjà écoulé) : zéro JS
// par image. Seule la ligne active se re-rend ; les autres sont mémoïsées.
export default function KaraokePlayer({ slug, onBack, autoPlay = false, onEnded, upNext }) {
  const [data, setData] = useState(null);
  const [time, setTime] = useState(0); // horloge « lente » (4 Hz) : compteur, barre, pré-roll
  const [cursor, setCursor] = useState({ line: -1, word: -1, seek: 0 }); // position fine
  const [playing, setPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [buffering, setBuffering] = useState(false);
  const [guideVol, setGuideVol] = useState(0); // volume de la voix-guide (0 = off)
  const [editing, setEditing] = useState(false);
  const [editLines, setEditLines] = useState(null);
  const [selIdx, setSelIdx] = useState(-1);
  const [saveMsg, setSaveMsg] = useState("");

  const instruRef = useRef(null);
  const vocalsRef = useRef(null);
  const activeLineRef = useRef(null);
  const lyricsRef = useRef(null);

  const base = `/library/${encodeURIComponent(slug)}`;
  // La voix-guide n'est téléchargée que si on s'en sert (la moitié des octets en moins).
  const guideOn = guideVol > 0;

  useEffect(() => {
    setData(null);
    fetch(`${base}/karaoke.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then(setData)
      .catch(() => setData({ error: true }));
  }, [base]);

  const baseLines = useMemo(() => withWordTimings(data?.lines ?? []), [data]);
  const lines = editing && editLines ? editLines : baseLines;
  const linesRef = useRef(lines);
  linesRef.current = lines;
  const seekGen = useRef(0);

  // Boucle d'animation : suit l'horloge de l'instrumental (le maître).
  useEffect(() => {
    let raf = 0;
    let lastSlow = -1;
    const tick = () => {
      const instru = instruRef.current;
      const vocals = vocalsRef.current;
      if (instru) {
        const t = instru.currentTime;
        const ls = linesRef.current;
        const li = findActiveLine(ls, t);
        const wi = li >= 0 ? findActiveWord(ls[li].words, t) : -1;
        const gen = seekGen.current;
        setCursor((c) => (c.line === li && c.word === wi && c.seek === gen ? c : { line: li, word: wi, seek: gen }));
        if (Math.abs(t - lastSlow) >= 0.25) {
          lastSlow = t;
          setTime(t);
        }
        // Garde la voix-guide synchronisée avec l'instrumental.
        if (vocals && !instru.paused && Math.abs(vocals.currentTime - t) > 0.12) {
          vocals.currentTime = t;
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // Voix-guide : volume + calage au montage (elle peut apparaître en pleine lecture).
  useEffect(() => {
    const vocals = vocalsRef.current;
    const instru = instruRef.current;
    if (!vocals || !instru) return;
    vocals.volume = guideVol;
    if (Math.abs(vocals.currentTime - instru.currentTime) > 0.12) {
      vocals.currentTime = instru.currentTime;
    }
    if (!instru.paused && vocals.paused) vocals.play().catch(() => {});
  }, [guideVol, guideOn]);

  const seekTo = useCallback((t) => {
    const instru = instruRef.current;
    if (!instru) return;
    const max = Number.isFinite(instru.duration) ? instru.duration : Infinity;
    const clamped = Math.max(0, Math.min(max, t));
    instru.currentTime = clamped;
    if (vocalsRef.current) vocalsRef.current.currentTime = clamped;
    seekGen.current += 1; // relance l'animation du mot en cours à la bonne position
    setTime(clamped);
  }, []);

  const togglePlay = useCallback(() => {
    const instru = instruRef.current;
    if (!instru) return;
    if (instru.paused) instru.play().catch(() => {});
    else instru.pause();
  }, []);

  // La voix-guide suit l'état de l'instrumental (source de vérité : l'élément audio).
  const onInstruPlay = () => {
    setPlaying(true);
    const vocals = vocalsRef.current;
    if (vocals) {
      vocals.currentTime = instruRef.current.currentTime;
      vocals.play().catch(() => {});
    }
  };
  const onInstruPause = () => {
    setPlaying(false);
    vocalsRef.current?.pause();
  };

  // Raccourcis clavier : espace = play/pause, flèches = ±5 s, Début = retour.
  useEffect(() => {
    const onKey = (e) => {
      const instru = instruRef.current;
      if (!instru || e.target.closest?.("input, textarea")) return;
      if (e.code === "Space") {
        e.preventDefault();
        togglePlay();
      } else if (e.code === "ArrowRight") {
        seekTo(instru.currentTime + 5);
      } else if (e.code === "ArrowLeft") {
        seekTo(instru.currentTime - 5);
      } else if (e.code === "Home") {
        seekTo(0);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [seekTo, togglePlay]);

  const activeIndex = cursor.line;
  const preroll = editing ? null : computePreroll(lines, activeIndex, time, playing);

  // --- Édition de la synchro ---
  const enterEdit = () => {
    setEditLines(structuredClone(baseLines));
    setSelIdx(-1);
    setSaveMsg("");
    setEditing(true);
  };
  const cancelEdit = () => { setEditing(false); setEditLines(null); };
  const shiftAll = (delta) => setEditLines((ls) => ls.map((l) => shiftLine(l, delta)));
  const setLineHere = () => {
    if (selIdx < 0) return;
    const now = instruRef.current?.currentTime ?? time;
    setEditLines((ls) => ls.map((l, i) => (i === selIdx ? shiftLine(l, now - l.start) : l)));
  };
  const save = async () => {
    try {
      const r = await fetch(`${apiBase}/api/save/${encodeURIComponent(slug)}`, {
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
      setSaveMsg("Échec : " + e.message + " — lance le serveur : uv run karaoke serve");
    }
  };
  const onSelect = useCallback((i) => setSelIdx(i), []);

  // Auto-scroll de la ligne active au centre (sans animation après un grand saut).
  const prevActive = useRef(-1);
  useEffect(() => {
    const el = activeLineRef.current;
    if (el) {
      const jump = Math.abs(activeIndex - prevActive.current) > 1;
      el.scrollIntoView({ behavior: jump ? "auto" : "smooth", block: "center" });
    }
    prevActive.current = activeIndex;
  }, [activeIndex]);

  if (!data) return <div className="player"><p className="hint">Chargement…</p></div>;
  if (data.error) {
    return (
      <div className="player">
        <p className="hint">Morceau introuvable.</p>
        <button className="back" onClick={onBack}>← Retour</button>
      </div>
    );
  }

  return (
    <div className={`player${playing ? "" : " paused"}`}>
      <header className="player-head">
        <button className="back" onClick={onBack}>← Retour</button>
        <div className="now">
          <strong>{data.title}</strong>
          {data.artist && <span> — {data.artist}</span>}
        </div>
        <div className="src">{upNext ? `ensuite : ${upNext}` : data.lyrics_source}</div>
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

      <div className="lyrics" ref={lyricsRef}>
        {lines.length === 0 && <p className="hint">Pas de paroles (karaoké instrumental).</p>}
        {lines.map((line, i) => (
          <LyricLine
            key={i}
            index={i}
            line={line}
            // Seule la ligne active dépend du curseur : les autres ne se re-rendent pas.
            cursor={i === activeIndex ? cursor : null}
            clock={i === activeIndex ? instruRef : null}
            state={i === activeIndex ? "active" : i < activeIndex ? "past" : "future"}
            innerRef={i === activeIndex ? activeLineRef : null}
            selected={editing && i === selIdx}
            onSelect={editing ? onSelect : null}
          />
        ))}
      </div>

      {preroll !== null && <PreRoll progress={preroll} />}

      <div className="controls">
        <button className="play" onClick={togglePlay} aria-label={playing ? "Pause" : "Lecture"}>
          {buffering && playing ? "…" : playing ? "⏸" : "▶"}
        </button>
        <span className="tc">{fmt(time)}</span>
        <input
          className="scrub"
          type="range"
          min={0}
          max={duration || 0}
          step={0.01}
          value={time}
          onChange={(e) => seekTo(Number(e.target.value))}
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
        onPlay={onInstruPlay}
        onPause={onInstruPause}
        onEnded={() => { onInstruPause(); onEnded?.(); }}
        autoPlay={autoPlay}
        onWaiting={() => setBuffering(true)}
        onPlaying={() => setBuffering(false)}
        onSeeking={() => vocalsRef.current && (vocalsRef.current.currentTime = instruRef.current.currentTime)}
        preload="auto"
      />
      {guideOn && data.vocals && (
        <audio ref={vocalsRef} src={`${base}/${data.vocals}`} preload="auto" />
      )}
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

const LyricLine = memo(function LyricLine({ index, line, cursor, clock, state, innerRef, selected, onSelect }) {
  return (
    <p
      ref={innerRef}
      className={`line ${state}${selected ? " selected" : ""}`}
      onClick={onSelect ? () => onSelect(index) : undefined}
      style={onSelect ? { cursor: "pointer" } : undefined}
    >
      {line.words.map((w, i) => {
        if (!cursor) return <span key={i} className="word">{w.text} </span>;
        if (i < cursor.word) return <span key={i} className="word sung">{w.text} </span>;
        if (i > cursor.word) return <span key={i} className="word">{w.text} </span>;
        // Mot en cours : animation CSS calée sur l'horloge audio au moment du rendu.
        const t = clock?.current?.currentTime ?? w.start;
        const dur = Math.max(0.05, w.end - w.start);
        const style = { animationDuration: `${dur}s`, animationDelay: `${-(t - w.start)}s` };
        return (
          <span key={`${i}-${cursor.seek}`} className="word singing" style={style}>
            {w.text}{" "}
          </span>
        );
      })}
    </p>
  );
});

// Anciennes bibliothèques (LRC ligne-à-ligne sans mot-à-mot) : un seul « mot »
// = toute la ligne, sans durée. On le découpe en mots répartis sur la ligne pour
// que le surlignage progresse quand même (même logique que align.interpolate_words).
export function withWordTimings(lines) {
  return lines.map((l, i) => {
    const single = l.words.length === 1 && l.words[0].end <= l.words[0].start && /\s/.test(l.words[0].text.trim());
    if (!single) return l;
    const tokens = l.words[0].text.trim().split(/\s+/);
    const next = lines[i + 1]?.start ?? l.start + 0.3 * tokens.length + 0.5;
    const span = Math.max(0.3, Math.min(next - l.start, 0.3 * tokens.length + 0.5));
    const total = tokens.reduce((s, t) => s + Math.max(1, t.length), 0);
    let t = l.start;
    const words = tokens.map((text) => {
      const d = (span * Math.max(1, text.length)) / total;
      const w = { text, start: t, end: t + d };
      t += d;
      return w;
    });
    return { ...l, end: t, words };
  });
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

// Recherche dichotomique de la dernière ligne commencée (O(log n) par image).
function findActiveLine(lines, t) {
  let lo = 0;
  let hi = lines.length - 1;
  let idx = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (lines[mid].start <= t) {
      idx = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return idx;
}

// Dernier mot commencé de la ligne (-1 avant le premier) : ceux d'avant sont chantés.
function findActiveWord(words, t) {
  let idx = -1;
  for (let i = 0; i < words.length && words[i].start <= t; i++) idx = i;
  if (idx >= 0 && t >= words[idx].end && idx === words.length - 1) return words.length;
  return idx;
}

function fmt(s) {
  if (!s || Number.isNaN(s)) return "0:00";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}
