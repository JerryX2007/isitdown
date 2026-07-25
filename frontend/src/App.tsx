import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import {
  Link,
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";


const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
const EXAMPLE_SITES = ["github.com", "spotify.com", "discord.com"];

type SiteStatus = "up" | "issues" | "down";
type HistoryRange = "24h" | "7d";

type CheckResult = {
  target: string;
  status: SiteStatus;
  latency: number | null;
  status_code: number | null;
  checked_at: string;
  error: string | null;
};

type HistoryData = {
  target: string;
  range: HistoryRange;
  points: Array<{ key: string; count: number }>;
  summary: {
    reports_in_range: number;
    reports_last_hour: number;
    reports_last_15_minutes: number;
    last_reported_at: string | null;
  };
  latest_check: CheckResult | null;
};

const STATUS_COPY = {
  up: {
    title: "is up",
    detail: "The website responded normally to a fresh availability check.",
  },
  issues: {
    title: "may be having issues",
    detail: "The website responded, but its server returned an error.",
  },
  down: {
    title: "appears to be down",
    detail: "We could not get a response from the website.",
  },
};

function normalizeWebsite(rawValue: string) {
  const value = rawValue.trim();
  if (!value) throw new Error("Enter a website to check.");

  let parsed: URL;
  try {
    parsed = new URL(value.includes("://") ? value : `https://${value}`);
  } catch {
    throw new Error("Enter a valid website, such as example.com.");
  }

  const target = parsed.hostname.toLowerCase().replace(/\.$/, "");
  if (!target || target === "localhost" || !target.includes(".")) {
    throw new Error("Enter a public website address.");
  }

  return target;
}

function displayTarget(target: string) {
  return target.replace(/^www\./, "");
}

function relativeTime(value: string | null) {
  if (!value) return "No reports yet";

  const elapsed = Date.now() - new Date(value).getTime();
  const minutes = Math.max(0, Math.floor(elapsed / 60_000));

  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes} min ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;

  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function getReporterId() {
  const storageKey = "website-outage-reporter-id";
  let reporterId = localStorage.getItem(storageKey);

  if (!reporterId) {
    reporterId = `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random()
      .toString(36)
      .slice(2)}`;
    localStorage.setItem(storageKey, reporterId);
  }

  return reporterId;
}

function Brand({ small = false }: { small?: boolean }) {
  return (
    <Link className={`brand${small ? " brand-small" : ""}`} to="/">
      <span className="brand-mark" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span>
        isit<span>down</span>
      </span>
    </Link>
  );
}

function SearchIcon() {
  return <span className="search-icon" aria-hidden="true" />;
}

function HomePage() {
  const navigate = useNavigate();
  const [website, setWebsite] = useState("");
  const [error, setError] = useState("");

  function submitWebsite(event: FormEvent) {
    event.preventDefault();
    setError("");

    try {
      const target = normalizeWebsite(website);
      navigate(`/status/${encodeURIComponent(target)}`);
    } catch (inputError) {
      setError(
        inputError instanceof Error
          ? inputError.message
          : "Enter a valid website.",
      );
    }
  }

  return (
    <main className="page-shell">
      <header className="site-header">
        <Brand />
        <span className="header-note">No account required</span>
      </header>

      <section className="home-hero">
        <p className="eyebrow">
          <span className="live-dot" />
          Live website status
        </p>
        <h1>
          Is it down for everyone
          <br />
          <span>or just you?</span>
        </h1>
        <p className="hero-copy">
          Check any website in seconds, see recent outage reports, and find out
          if other people are having the same problem.
        </p>

        <form className="domain-form" onSubmit={submitWebsite}>
          <label className="domain-input">
            <SearchIcon />
            <input
              aria-label="Website address"
              autoCapitalize="none"
              autoComplete="url"
              autoCorrect="off"
              onChange={(event) => {
                setWebsite(event.target.value);
                setError("");
              }}
              placeholder="Enter a website, e.g. google.com"
              spellCheck={false}
              value={website}
            />
          </label>
          <button className="primary-button" type="submit">
            Check status <span aria-hidden="true">→</span>
          </button>
        </form>

        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : (
          <div className="examples">
            <span>Try a popular site:</span>
            {EXAMPLE_SITES.map((site) => (
              <button
                key={site}
                onClick={() => navigate(`/status/${site}`)}
                type="button"
              >
                {site}
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="feature-strip">
        <article>
          <span className="feature-icon">↗</span>
          <div>
            <h2>Fresh availability check</h2>
            <p>A new request is made every time you check.</p>
          </div>
        </article>
        <article>
          <span className="feature-icon">▥</span>
          <div>
            <h2>Community outage history</h2>
            <p>See when other visitors reported a problem.</p>
          </div>
        </article>
        <article>
          <span className="feature-icon">✓</span>
          <div>
            <h2>Private by default</h2>
            <p>No login, tracking profile, or saved account.</p>
          </div>
        </article>
      </section>

      <Footer />
    </main>
  );
}

function OutageChart({
  history,
  range,
}: {
  history: HistoryData | null;
  range: HistoryRange;
}) {
  const points = history?.range === range ? history.points : [];
  const fallbackLength = range === "24h" ? 24 : 7;
  const visiblePoints =
    points.length > 0
      ? points
      : Array.from({ length: fallbackLength }, (_, index) => ({
          key: String(index),
          count: 0,
        }));
  const maximum = Math.max(1, ...visiblePoints.map((point) => point.count));

  function formatLabel(key: string, index: number) {
    if (!points.length) return "";

    if (range === "7d") {
      return new Intl.DateTimeFormat("en", {
        weekday: "short",
        timeZone: "UTC",
      }).format(new Date(`${key}T00:00:00Z`));
    }

    if (![0, 6, 12, 18, 23].includes(index)) return "";
    return new Intl.DateTimeFormat("en", {
      hour: "numeric",
      timeZone: "UTC",
    }).format(new Date(key));
  }

  return (
    <div
      aria-label={`Outage reports over the last ${range === "24h" ? "24 hours" : "7 days"}`}
      className="outage-chart"
      role="img"
    >
      <div className="chart-lines">
        <i />
        <i />
        <i />
      </div>
      <div className="bars">
        {visiblePoints.map((point, index) => (
          <div className="bar-column" key={point.key}>
            <div className="bar-track">
              <span
                className={`bar${point.count > 0 ? " has-reports" : ""}`}
                style={{
                  height:
                    point.count > 0
                      ? `${Math.max(12, (point.count / maximum) * 100)}%`
                      : "3px",
                }}
                title={`${point.count} outage report${point.count === 1 ? "" : "s"}`}
              />
            </div>
            <span className="bar-label">
              {formatLabel(point.key, index)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatusPage() {
  const navigate = useNavigate();
  const params = useParams();
  const target = useMemo(() => {
    try {
      return normalizeWebsite(decodeURIComponent(params.target ?? ""));
    } catch {
      return "";
    }
  }, [params.target]);

  const [searchValue, setSearchValue] = useState(target);
  const [check, setCheck] = useState<CheckResult | null>(null);
  const [history, setHistory] = useState<HistoryData | null>(null);
  const [range, setRange] = useState<HistoryRange>("24h");
  const [isChecking, setIsChecking] = useState(true);
  const [isReporting, setIsReporting] = useState(false);
  const [error, setError] = useState(target ? "" : "Invalid website address.");
  const [reportMessage, setReportMessage] = useState("");

  const loadHistory = useCallback(
    async (selectedRange: HistoryRange) => {
      if (!target) return;
      const response = await fetch(
        `${API_BASE}/api/status/${encodeURIComponent(target)}/history?range=${selectedRange}`,
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail ?? "Could not load outage history.");
      }

      setHistory(data);
    },
    [target],
  );

  const checkWebsite = useCallback(async () => {
    if (!target) return;
    setIsChecking(true);
    setError("");

    try {
      const response = await fetch(`${API_BASE}/api/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ website: target }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail ?? "Could not check this website.");
      }

      setCheck(data);
      await loadHistory(range);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not check this website.",
      );
    } finally {
      setIsChecking(false);
    }
  }, [loadHistory, range, target]);

  useEffect(() => {
    const task = window.setTimeout(() => void checkWebsite(), 0);
    return () => window.clearTimeout(task);
    // Run once when the route changes, not every time the chart range changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  async function changeRange(selectedRange: HistoryRange) {
    setRange(selectedRange);
    try {
      await loadHistory(selectedRange);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not load outage history.",
      );
    }
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    try {
      navigate(`/status/${encodeURIComponent(normalizeWebsite(searchValue))}`);
    } catch (inputError) {
      setError(
        inputError instanceof Error
          ? inputError.message
          : "Enter a valid website.",
      );
    }
  }

  async function reportOutage() {
    setIsReporting(true);
    setReportMessage("");

    try {
      const response = await fetch(
        `${API_BASE}/api/status/${encodeURIComponent(target)}/report`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reporter_id: getReporterId() }),
        },
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail ?? "Could not submit your report.");
      }

      setReportMessage("Thanks — your outage report has been added.");
      await loadHistory(range);
    } catch (requestError) {
      setReportMessage(
        requestError instanceof Error
          ? requestError.message
          : "Could not submit your report.",
      );
    } finally {
      setIsReporting(false);
    }
  }

  const status = check?.status ?? "up";
  const statusCopy = STATUS_COPY[status];
  const reportsLast15Minutes =
    history?.summary.reports_last_15_minutes ?? 0;

  return (
    <main className="page-shell status-page">
      <header className="site-header status-header">
        <Brand />
        <form className="header-search" onSubmit={submitSearch}>
          <SearchIcon />
          <input
            aria-label="Check another website"
            onChange={(event) => setSearchValue(event.target.value)}
            spellCheck={false}
            value={searchValue}
          />
          <button type="submit">Check</button>
        </form>
      </header>

      <Link className="back-link" to="/">
        ← Check another site
      </Link>

      <section className={`status-hero status-${status}`}>
        <div className={`status-orb${isChecking ? " loading" : ""}`}>
          {!isChecking && (status === "up" ? "✓" : "!")}
        </div>
        <div className="status-heading">
          <p className="panel-eyebrow">Current status</p>
          <h1>
            {displayTarget(target || "Website")}{" "}
            <span>
              {isChecking ? "is being checked" : statusCopy.title}
            </span>
          </h1>
          <p>
            {isChecking
              ? "Testing the website from a fresh connection."
              : statusCopy.detail}
          </p>
        </div>
        <div className="check-meta">
          <span className="freshness-dot" />
          <div>
            <strong>
              {isChecking
                ? "Running a fresh check…"
                : `Checked ${relativeTime(check?.checked_at ?? null)}`}
            </strong>
            <span>
              {check?.latency ? `${check.latency} ms response` : "Live request"}
            </span>
          </div>
        </div>
        <button
          className="secondary-button"
          disabled={isChecking}
          onClick={() => void checkWebsite()}
          type="button"
        >
          ↻ {isChecking ? "Checking…" : "Check again"}
        </button>
      </section>

      {error && (
        <p className="inline-alert" role="alert">
          {error}
        </p>
      )}

      <section className="content-grid">
        <article className="panel chart-card">
          <div className="panel-header">
            <div>
              <p className="panel-eyebrow">Community signal</p>
              <h2>Outage reports</h2>
              <p>Reports submitted by visitors during this period.</p>
            </div>
            <div className="range-switch">
              <button
                className={range === "24h" ? "active" : ""}
                onClick={() => void changeRange("24h")}
                type="button"
              >
                24 hours
              </button>
              <button
                className={range === "7d" ? "active" : ""}
                onClick={() => void changeRange("7d")}
                type="button"
              >
                7 days
              </button>
            </div>
          </div>

          <div className="chart-summary">
            <div>
              <strong>{history?.summary.reports_in_range ?? 0}</strong>
              <span>total reports</span>
            </div>
            <p>
              <span
                className={
                  reportsLast15Minutes >= 4 ? "signal high" : "signal"
                }
              />
              {reportsLast15Minutes === 0
                ? "No unusual report spike"
                : reportsLast15Minutes < 4
                  ? "A few recent reports"
                  : "Elevated outage reports"}
            </p>
          </div>

          <OutageChart history={history} range={range} />
          <div className="chart-caption">
            <span>{range === "24h" ? "24 hours ago" : "7 days ago"}</span>
            <span>Now</span>
          </div>
        </article>

        <aside className="panel report-card">
          <span className="report-icon">!</span>
          <p className="panel-eyebrow">Community report</p>
          <h2>Having trouble too?</h2>
          <p>
            If {displayTarget(target)} is not working for you, add your report
            to the graph. No account is needed.
          </p>
          <button
            className="report-button"
            disabled={isReporting}
            onClick={() => void reportOutage()}
            type="button"
          >
            {isReporting ? "Submitting…" : "Report an outage"}
          </button>
          {reportMessage && (
            <p className="report-message" role="status">
              {reportMessage}
            </p>
          )}
          <small>One report per website, per hour.</small>
        </aside>
      </section>

      <section className="summary-row">
        <article>
          <span className="summary-icon green">✓</span>
          <div>
            <p>Latest check</p>
            <strong>{check ? STATUS_COPY[check.status].title : "Checking…"}</strong>
          </div>
        </article>
        <article>
          <span className="summary-icon blue">≋</span>
          <div>
            <p>Reports in the last hour</p>
            <strong>{history?.summary.reports_last_hour ?? 0}</strong>
          </div>
        </article>
        <article>
          <span className="summary-icon neutral">◷</span>
          <div>
            <p>Last community report</p>
            <strong>
              {relativeTime(history?.summary.last_reported_at ?? null)}
            </strong>
          </div>
        </article>
      </section>

      <p className="disclaimer">
        ⓘ A successful check means the website responded from the checker. Your
        local connection, DNS, or account may still experience a separate issue.
      </p>

      <Footer />
    </main>
  );
}

function Footer() {
  return (
    <footer>
      <Brand small />
      <p>Independent status checks and community reports.</p>
    </footer>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/status/:target" element={<StatusPage />} />
      <Route path="*" element={<Navigate replace to="/" />} />
    </Routes>
  );
}
