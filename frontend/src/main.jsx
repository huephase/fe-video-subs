import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, AlertTriangle, CheckCircle2, FileVideo, ListPlus, Pause, Play, RefreshCw, Save, Trash2 } from "lucide-react";
import "./styles.css";

const api = {
  async get(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  async send(path, method, body) {
    const options = {
      method,
      headers: { "Content-Type": "application/json" },
    };
    if (body !== undefined) {
      options.body = JSON.stringify(body);
    }
    const res = await fetch(path, options);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
};

function statusTone(status) {
  return {
    completed: "ok",
    failed: "bad",
    running: "live",
    queued: "wait",
    paused: "wait",
    pausing: "wait",
  }[status] || "wait";
}

function App() {
  const [jobs, setJobs] = useState([]);
  const [files, setFiles] = useState([]);
  const [config, setConfig] = useState(null);
  const [selectedJobId, setSelectedJobId] = useState(null);
  const [logs, setLogs] = useState([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const selectedJob = useMemo(() => jobs.find((job) => job.id === selectedJobId) || jobs[0], [jobs, selectedJobId]);

  async function refresh() {
    try {
      const [nextJobs, nextFiles, nextConfig] = await Promise.all([
        api.get("/api/jobs"),
        api.get("/api/watch/files"),
        api.get("/api/config"),
      ]);
      setJobs(nextJobs);
      setFiles(nextFiles);
      setConfig(nextConfig);
      setError("");
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function loadLogs(jobId) {
    if (!jobId) return;
    try {
      setLogs(await api.get(`/api/jobs/${jobId}/logs`));
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function enqueue(path) {
    try {
      const job = await api.send("/api/jobs", "POST", { source_path: path, auto_start: true });
      setSelectedJobId(job.id);
      await refresh();
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function saveConfig() {
    try {
      setSaving(true);
      setConfig(await api.send("/api/config", "PUT", config));
      setError("");
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setSaving(false);
    }
  }

  async function pauseJob(job) {
    if (!job) return;
    try {
      await api.send(`/api/jobs/${job.id}/pause`, "POST", {});
      await refresh();
      await loadLogs(job.id);
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function resumeJob(job) {
    if (!job) return;
    try {
      await api.send(`/api/jobs/${job.id}/resume`, "POST", {});
      await refresh();
      await loadLogs(job.id);
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function clearJob(job) {
    if (!job) return;
    if (!window.confirm(`Clear ${job.original_filename} and delete its working files?`)) return;
    try {
      await api.send(`/api/jobs/${job.id}`, "DELETE");
      setSelectedJobId(null);
      setLogs([]);
      await refresh();
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  useEffect(() => {
    refresh();
    const events = new EventSource("/api/events/stream");
    events.onmessage = (event) => setJobs(JSON.parse(event.data).jobs);
    events.onerror = () => events.close();
    const timer = setInterval(refresh, 10000);
    return () => {
      clearInterval(timer);
      events.close();
    };
  }, []);

  useEffect(() => {
    loadLogs(selectedJob?.id);
    const timer = setInterval(() => loadLogs(selectedJob?.id), 3000);
    return () => clearInterval(timer);
  }, [selectedJob?.id]);

  const active = jobs.find((job) => ["running", "pausing"].includes(job.status));
  const completed = jobs.filter((job) => job.status === "completed").length;
  const failed = jobs.filter((job) => job.status === "failed").length;

  return (
    <main>
      <header className="topbar">
        <div>
          <h1>{config?.ui?.app_name || "Video Subtitle Studio"}</h1>
          <p>{active ? `${active.original_filename} is ${active.stage}` : "Queue is ready"}</p>
        </div>
        <button className="iconButton" title="Refresh" onClick={refresh}>
          <RefreshCw size={18} />
        </button>
      </header>

      {error && <div className="banner"><AlertTriangle size={18} />{error}</div>}

      <section className="metrics">
        <Metric icon={<Activity />} label="Active" value={active ? active.stage : "Idle"} />
        <Metric icon={<ListPlus />} label="Queued" value={jobs.filter((job) => job.status === "queued").length} />
        <Metric icon={<CheckCircle2 />} label="Completed" value={completed} />
        <Metric icon={<AlertTriangle />} label="Failed" value={failed} />
      </section>

      <section className="layout">
        <div className="panel">
          <div className="panelHead">
            <h2>Watch Folder</h2>
            <span>{files.length} files</span>
          </div>
          <div className="fileList">
            {files.map((file) => (
              <div className="fileRow" key={file.path}>
                <FileVideo size={18} />
                <div>
                  <strong>{file.name}</strong>
                  <small>{file.path}</small>
                </div>
                <button title="Enqueue" onClick={() => enqueue(file.path)}>
                  <Play size={16} />
                </button>
              </div>
            ))}
            {!files.length && <p className="empty">No files in the configured watch directory.</p>}
          </div>
        </div>

        <div className="panel wide">
          <div className="panelHead">
            <h2>Queue</h2>
            <span>{jobs.length} jobs</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Status</th>
                <th>Stage</th>
                <th>Progress</th>
                <th>Output</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id} onClick={() => setSelectedJobId(job.id)} className={selectedJob?.id === job.id ? "selected" : ""}>
                  <td>{job.original_filename}</td>
                  <td><span className={`badge ${statusTone(job.status)}`}>{job.status}</span></td>
                  <td>{job.stage}</td>
                  <td><Progress value={job.progress} /></td>
                  <td>{job.output_path || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="layout lower">
        <div className="panel">
          <div className="panelHead">
            <h2>Job Details</h2>
            <span>{selectedJob?.id?.slice(0, 8) || "none"}</span>
          </div>
          {selectedJob ? (
            <div className="details">
              <div className="actions">
                {["paused", "pausing"].includes(selectedJob.status) ? (
                  <button title="Resume job" onClick={() => resumeJob(selectedJob)}><Play size={16} /></button>
                ) : (
                  <button title="Pause job" disabled={!["queued", "running"].includes(selectedJob.status)} onClick={() => pauseJob(selectedJob)}><Pause size={16} /></button>
                )}
                <button className="danger" title="Clear job and files" disabled={["running", "pausing"].includes(selectedJob.status)} onClick={() => clearJob(selectedJob)}><Trash2 size={16} /></button>
              </div>
              <Field label="Source" value={selectedJob.processing_path || selectedJob.source_path} />
              <Field label="Target language" value={selectedJob.target_language} />
              <Field label="Output" value={selectedJob.output_path || "Pending"} />
              {selectedJob.error_summary && <pre className="errorText">{selectedJob.error_detail || selectedJob.error_summary}</pre>}
            </div>
          ) : <p className="empty">Select a job to inspect it.</p>}
        </div>

        <div className="panel">
          <div className="panelHead">
            <h2>Logs</h2>
            <span>{logs.length}</span>
          </div>
          <div className="logs">
            {logs.map((log) => (
              <div className={log.level === "error" ? "log error" : "log"} key={log.id}>
                <time>{new Date(log.created_at).toLocaleTimeString()}</time>
                <strong>{log.stage || log.level}</strong>
                <span>{log.message}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panelHead">
            <h2>Settings</h2>
            <button className="save" onClick={saveConfig} disabled={!config || saving} title="Save settings">
              <Save size={16} />
            </button>
          </div>
          {config && (
            <div className="settings">
              <label>Target language<input value={config.translation.target_language} onChange={(e) => setConfig({ ...config, translation: { ...config.translation, target_language: e.target.value } })} /></label>
              <label>Whisper model<input value={config.whisper.model} onChange={(e) => setConfig({ ...config, whisper: { ...config.whisper, model: e.target.value } })} /></label>
              <label>Font<input value={config.subtitles.font_name} onChange={(e) => setConfig({ ...config, subtitles: { ...config.subtitles, font_name: e.target.value } })} /></label>
              <label>Font size<input type="number" value={config.subtitles.font_size} onChange={(e) => setConfig({ ...config, subtitles: { ...config.subtitles, font_size: Number(e.target.value) } })} /></label>
              <label>CRF<input type="number" value={config.burn.crf} onChange={(e) => setConfig({ ...config, burn: { ...config.burn, crf: Number(e.target.value) } })} /></label>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

function Metric({ icon, label, value }) {
  return <div className="metric">{React.cloneElement(icon, { size: 20 })}<span>{label}</span><strong>{value}</strong></div>;
}

function Progress({ value }) {
  return <div className="progress"><div style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /><span>{Math.round(value)}%</span></div>;
}

function Field({ label, value }) {
  return <div className="field"><span>{label}</span><p>{value}</p></div>;
}

createRoot(document.getElementById("root")).render(<App />);
