import { useEffect, useState, type FormEvent } from 'react'
import './App.css'

const API_BASE = "http://127.0.0.1:8000";

type Monitor = {
  id: number;
  name: string;
  target: string;
  port: number;
  timeout: number;
  check_type: string;
  status: string | null;
  latency: number | null;
  last_checked: string | null;
  last_error: string | null;
};

type CheckResult = {
  target: string;
  port: number;
  check_type: string;
  status: string;
  latency: number | null;
  last_error: string | null;
  checked_at: string;
};

type PopularSite = {
  target: string;
  total_checks: number;
  last_checked: string | null;
  last_status: string | null;
  last_latency: number | null;
};

function getGuestId() {
  let guestId = localStorage.getItem("guestId");

  if (!guestId) {
    guestId = crypto.randomUUID();
    localStorage.setItem("guestId", guestId);
  }

  return guestId;
}

function guestHeaders() {
  return {
    "X-Guest-Id": getGuestId(),
  };
}

function statusLabel(status: string | null) {
  if (!status) return "Not checked";
  return status === "online" ? "Online" : "Offline";
}

function App() {
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [popularSites, setPopularSites] = useState<PopularSite[]>([]);
  const [website, setWebsite] = useState("");
  const [monitorName, setMonitorName] = useState("");
  const [result, setResult] = useState<CheckResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState(false);

  async function loadMonitors() {
    const response = await fetch(`${API_BASE}/monitors`, {
      headers: guestHeaders(),
    });

    const data = await response.json();
    setMonitors(data);
  }

  async function loadPopularSites() {
    const response = await fetch(`${API_BASE}/popular`);
    const data = await response.json();
    setPopularSites(data);
  }

  useEffect(() => {
    loadMonitors();
    loadPopularSites();
  }, []);

  async function checkOnce(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setResult(null);
    setIsChecking(true);

    try {
      const response = await fetch(`${API_BASE}/check-once`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          website,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail ?? "Could not check website");
      }

      setResult(data);
      loadPopularSites();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setIsChecking(false);
    }
  }

  async function saveMonitor() {
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/monitors`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...guestHeaders(),
        },
        body: JSON.stringify({
          website,
          name: monitorName || undefined,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail ?? "Could not save monitor");
      }

      setMonitors((prevMonitors) => [data, ...prevMonitors]);
      setMonitorName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    }
  }

  async function checkMonitor(id: number) {
    const response = await fetch(`${API_BASE}/monitors/${id}/check`, {
      method: "POST",
      headers: guestHeaders(),
    });

    const result = await response.json();

    setMonitors((prevMonitors) =>
      prevMonitors.map((monitor) =>
        monitor.id === id
          ? {
              ...monitor,
              status: result.status,
              latency: result.latency,
              last_checked: result.checked_at,
              last_error: result.last_error,
            }
          : monitor
      )
    );

    loadPopularSites();
  }

  async function deleteMonitor(id: number) {
    await fetch(`${API_BASE}/monitors/${id}`, {
      method: "DELETE",
      headers: guestHeaders(),
    });

    setMonitors((prevMonitors) => prevMonitors.filter((monitor) => monitor.id !== id));
  }

  return (
    <main className="app-shell">
      <section className="hero-card">
        <p className="eyebrow">Website status checker</p>
        <h1>Is this website down?</h1>
        <p className="hero-subtitle">
          Enter a domain and I’ll automatically check the right connection for you.
        </p>

        <form className="check-form" onSubmit={checkOnce}>
          <input
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
            placeholder="google.com"
          />
          <button type="submit" disabled={isChecking || website.trim() === ""}>
            {isChecking ? "Checking..." : "Check now"}
          </button>
        </form>

        <div className="save-row">
          <input
            value={monitorName}
            onChange={(e) => setMonitorName(e.target.value)}
            placeholder="Optional tracker name"
          />
          <button type="button" onClick={saveMonitor} disabled={website.trim() === ""}>
            Save tracker
          </button>
        </div>

        {error && <p className="error-message">{error}</p>}

        {result && (
          <div className={`result-card ${result.status}`}>
            <div>
              <p className="result-target">{result.target}</p>
              <p className="result-meta">
                {result.check_type.toUpperCase()} on port {result.port} · Checked {result.checked_at}
              </p>
            </div>
            <div className="result-status">
              <span>{statusLabel(result.status)}</span>
              <strong>{result.latency !== null ? `${result.latency} ms` : "No response"}</strong>
            </div>
            {result.last_error && <p className="error-message">{result.last_error}</p>}
          </div>
        )}
      </section>

      <section className="dashboard-grid">
        <div className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Your saved trackers</p>
              <h2>Guest monitors</h2>
            </div>
            <span className="count-pill">{monitors.length}</span>
          </div>

          {monitors.length === 0 && <p className="empty-text">No monitors saved yet.</p>}

          <div className="monitor-list">
            {monitors.map((monitor) => (
              <article className="monitor-card" key={monitor.id}>
                <div className="monitor-topline">
                  <div>
                    <h3>{monitor.name}</h3>
                    <p>{monitor.target}</p>
                  </div>
                  <span className={`status-badge ${monitor.status ?? "unknown"}`}>
                    {statusLabel(monitor.status)}
                  </span>
                </div>

                <div className="monitor-details">
                  <span>{monitor.check_type.toUpperCase()}</span>
                  <span>Port {monitor.port}</span>
                  <span>{monitor.latency !== null ? `${monitor.latency} ms` : "No latency"}</span>
                </div>

                <p className="muted-text">
                  Last checked: {monitor.last_checked ?? "Never"}
                </p>
                {monitor.last_error && <p className="error-message">{monitor.last_error}</p>}

                <div className="button-row">
                  <button type="button" onClick={() => checkMonitor(monitor.id)}>
                    Check
                  </button>
                  <button className="ghost-button" type="button" onClick={() => deleteMonitor(monitor.id)}>
                    Delete
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Global activity</p>
              <h2>Most checked</h2>
            </div>
          </div>

          {popularSites.length === 0 && <p className="empty-text">Popular sites will appear after checks.</p>}

          <div className="popular-list">
            {popularSites.map((site, index) => (
              <article className="popular-card" key={site.target}>
                <span className="rank">#{index + 1}</span>
                <div>
                  <h3>{site.target}</h3>
                  <p>{site.total_checks} checks</p>
                </div>
                <span className={`status-badge ${site.last_status ?? "unknown"}`}>
                  {statusLabel(site.last_status)}
                </span>
              </article>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}

export default App
