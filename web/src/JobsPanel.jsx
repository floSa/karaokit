import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

const ACTIVE = new Set(["queued", "running"]);
const ICON = { queued: "⏳", running: "⚙️", done: "✅", skipped: "↺", error: "❌", cancelled: "✕" };

// File de traitement : progression en direct des morceaux envoyés depuis l'app.
// Interroge le serveur toutes les 1,5 s tant qu'un traitement est en cours.
export default function JobsPanel({ refreshKey, onSongReady, onOpen }) {
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState(null);
  const seen = useRef(new Set());

  useEffect(() => {
    let timer = 0;
    let stopped = false;
    const poll = async () => {
      try {
        const { jobs: list } = await api("/api/jobs");
        if (stopped) return;
        setJobs(list);
        setError(null);
        // Un morceau vient d'être prêt : la bibliothèque doit se recharger.
        const fresh = list.filter((j) => j.status === "done" && !seen.current.has(j.id));
        fresh.forEach((j) => seen.current.add(j.id));
        if (fresh.length) onSongReady?.();
        if (list.some((j) => ACTIVE.has(j.status))) timer = setTimeout(poll, 1500);
      } catch (e) {
        if (!stopped) setError("Serveur injoignable — lance : uv run karaoke serve");
      }
    };
    poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [refreshKey, onSongReady]);

  if (error) return <p className="hint">{error}</p>;
  if (!jobs.length) return null;

  const active = jobs.filter((j) => ACTIVE.has(j.status)).length;
  const cancel = async (id) => { await api(`/api/jobs/${id}`, { method: "DELETE" }).catch(() => {}); setJobs((js) => js.map((j) => (j.id === id ? { ...j, status: "cancelled", stage_label: "annulé" } : j))); };
  const clear = async () => { await api("/api/jobs/clear", { method: "POST" }).catch(() => {}); setJobs((js) => js.filter((j) => ACTIVE.has(j.status))); };

  return (
    <section className="jobs">
      <div className="jobs-head">
        <h2>Traitement {active ? `— ${active} en cours / en attente` : "terminé"}</h2>
        {jobs.length > active && <button className="linkbtn" onClick={clear}>Effacer les terminés</button>}
      </div>
      <ul>
        {jobs.map((j) => (
          <li key={j.id} className={`job ${j.status}`}>
            <span className="job-icon">{ICON[j.status]}</span>
            <span className="job-name">
              {j.title ? <>{j.title}{j.artist && <span className="song-artist"> — {j.artist}</span>}</> : j.name}
            </span>
            <span className="job-stage">
              {j.status === "running" && <span className="spinner" aria-hidden />}
              {j.status === "error" ? j.error : j.stage_label}
              {j.status === "running" && j.started && <Elapsed since={j.started} />}
              {j.status === "done" && j.finished && j.started && ` en ${Math.round(j.finished - j.started)} s`}
            </span>
            {j.status === "queued" && <button className="linkbtn" onClick={() => cancel(j.id)}>retirer</button>}
            {(j.status === "done" || j.status === "skipped") && j.slug && (
              <button className="linkbtn" onClick={() => onOpen(j.slug)}>▶ chanter</button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Elapsed({ since }) {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, []);
  return <span className="elapsed"> · {Math.max(0, Math.round(now - since))} s</span>;
}
