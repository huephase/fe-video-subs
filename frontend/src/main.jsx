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

function activeTitle(appName, job) {
  if (!job) return appName;
  const percent = Math.round(Number(job.progress || 0));
  return `${percent}% ${job.stage} - ${appName}`;
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

  function updateConfig(section, key, value) {
    setConfig({ ...config, [section]: { ...config[section], [key]: value } });
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
  const appName = config?.ui?.app_name || "Video Subtitle Studio";

  useEffect(() => {
    document.title = activeTitle(appName, active);
  }, [appName, active?.id, active?.progress, active?.stage]);

  return (
    <main>
      <header className="topbar">
        <div>
          <h1>{appName}</h1>
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
              <Setting label="Target language" tip="Subtitle translation target, such as ar, fa, ur, he, or es.">
                <input value={config.translation.target_language} onChange={(e) => updateConfig("translation", "target_language", e.target.value)} />
              </Setting>
              <Setting label="Whisper model" tip="Larger models are usually more accurate but slower and heavier.">
                <input value={config.whisper.model} onChange={(e) => updateConfig("whisper", "model", e.target.value)} />
              </Setting>
              <Setting label="Font" tip="Use a font installed in the backend image. Noto fonts are included.">
                <input value={config.subtitles.font_name} onChange={(e) => updateConfig("subtitles", "font_name", e.target.value)} />
              </Setting>
              <div className="settingsGrid">
                <Setting label="Font size" tip="Subtitle text size in ASS points.">
                  <input type="number" min="6" max="96" value={config.subtitles.font_size} onChange={(e) => updateConfig("subtitles", "font_size", Number(e.target.value))} />
                </Setting>
                <Setting label="Alignment" tip="ASS keypad alignment. 2 is bottom center, 8 is top center.">
                  <select value={config.subtitles.alignment} onChange={(e) => updateConfig("subtitles", "alignment", Number(e.target.value))}>
                    <option value="1">Bottom left</option>
                    <option value="2">Bottom center</option>
                    <option value="3">Bottom right</option>
                    <option value="5">Middle center</option>
                    <option value="7">Top left</option>
                    <option value="8">Top center</option>
                    <option value="9">Top right</option>
                  </select>
                </Setting>
                <Setting label="Bottom margin" tip="Vertical distance from the bottom when using bottom alignment.">
                  <input type="number" min="0" value={config.subtitles.margin_v} onChange={(e) => updateConfig("subtitles", "margin_v", Number(e.target.value))} />
                </Setting>
                <Setting label="Left margin" tip="Horizontal padding from the left edge.">
                  <input type="number" min="0" value={config.subtitles.margin_l} onChange={(e) => updateConfig("subtitles", "margin_l", Number(e.target.value))} />
                </Setting>
                <Setting label="Right margin" tip="Horizontal padding from the right edge.">
                  <input type="number" min="0" value={config.subtitles.margin_r} onChange={(e) => updateConfig("subtitles", "margin_r", Number(e.target.value))} />
                </Setting>
                <Setting label="Outline" tip="Black stroke thickness around text. Higher improves contrast.">
                  <input type="number" min="0" step="0.1" value={config.subtitles.outline} onChange={(e) => updateConfig("subtitles", "outline", Number(e.target.value))} />
                </Setting>
                <Setting label="Shadow" tip="Drop shadow offset. Keep subtle for clean subtitles.">
                  <input type="number" min="0" step="0.1" value={config.subtitles.shadow} onChange={(e) => updateConfig("subtitles", "shadow", Number(e.target.value))} />
                </Setting>
                <Setting label="Video CRF" tip="Lower is higher quality and larger output. 18-23 is common.">
                  <input type="number" min="0" max="51" value={config.burn.crf} onChange={(e) => updateConfig("burn", "crf", Number(e.target.value))} />
                </Setting>
              </div>
              <div className="settingsGrid">
                <Setting label="Text color" tip="ASS color format: &HAABBGGRR. White is &H00FFFFFF.">
                  <input value={config.subtitles.primary_color} onChange={(e) => updateConfig("subtitles", "primary_color", e.target.value)} />
                </Setting>
                <Setting label="Outline color" tip="ASS color format. Black is &H00000000.">
                  <input value={config.subtitles.outline_color} onChange={(e) => updateConfig("subtitles", "outline_color", e.target.value)} />
                </Setting>
                <Setting label="Back color" tip="ASS color format for subtitle box/background alpha.">
                  <input value={config.subtitles.back_color} onChange={(e) => updateConfig("subtitles", "back_color", e.target.value)} />
                </Setting>
                <Setting label="RTL mode" tip="Use libass native first. Try preprocess only if letters render reversed or disconnected.">
                  <select value={config.subtitles.rtl_mode} onChange={(e) => updateConfig("subtitles", "rtl_mode", e.target.value)}>
                    <option value="libass_native">libass native</option>
                    <option value="preprocess_bidi">preprocess bidi</option>
                    <option value="auto">auto</option>
                  </select>
                </Setting>
              </div>
              <label className="check" title="Makes subtitle text bold for better readability.">
                <input type="checkbox" checked={config.subtitles.bold} onChange={(e) => updateConfig("subtitles", "bold", e.target.checked)} />
                Bold subtitles
              </label>
              <label className="check" title="Applies Arabic shaping/bidi preprocessing as a fallback. Use only if native libass rendering looks wrong.">
                <input type="checkbox" checked={config.subtitles.rtl_preprocess_fallback} onChange={(e) => updateConfig("subtitles", "rtl_preprocess_fallback", e.target.checked)} />
                RTL preprocess fallback
              </label>
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

function Setting({ label, tip, children }) {
  return (
    <label title={tip}>
      <span className="settingLabel">{label}<small>?</small></span>
      {children}
    </label>
  );
}

createRoot(document.getElementById("root")).render(<App />);
