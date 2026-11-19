// The header: model status, warnings, the "Update data & model" button with its progress bar,
// and a notice when NBALine itself was updated while this page was open.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, messageOf, post } from "../api";
import { useApp } from "../context/AppContext";
import { duration } from "../format";
import type { UpdateStatus } from "../types";

const POLL_PROGRESS_MS = 1500;
const POLL_VERSION_MS = 30000;

export default function Header() {
  const { meta } = useApp();
  const update = useUpdateJob();
  const last = update.status?.last;
  const when = last && new Date(last.run_at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  return (
    <>
      <header className="top">
        <div className="brand">NBALine <span className="sub">PrizePicks helper</span></div>
        <div className="top-right">
          <div className="status">Model {meta.model} · trained {meta.trained_on} · data through {meta.data_through}</div>
          <div className="row gap wrap">
            <span className="status">
              {!update.status ? "" : last ? `Last update ${when} ${last.ok ? "✓" : "⚠"}` : "Never updated from the app"}
            </span>
            <button className="primary" disabled={update.status?.running} onClick={update.start}
              title="Download the latest games, check nothing is missing, grade your entries, and retrain the models">
              {update.status?.running ? "Updating…" : "⟳ Update data & model"}
            </button>
          </div>
        </div>
      </header>
      <UpdatedNotice />
      <div id="warnings">{meta.warnings.map((w) => <div key={w} className="banner bad">{w}</div>)}</div>
      {update.status?.running ? <UpdateProgress s={update.status} />
        : update.finished && update.status ? <UpdateFinished s={update.status} /> : null}
    </>
  );
}

// ------------------------------------------------------------- the one-click update
/** Follows an update while it runs (its progress every 1.5 seconds). When a run this page followed
 *  finishes, the header reloads the model info and tabs showing graded results reload too. */
function useUpdateJob() {
  const { toast, reloadMeta, newData } = useApp();
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [finished, setFinished] = useState(false);
  const watching = useRef(false);   // true while this page follows a run it started (or found running)
  const timer = useRef<number>(undefined);

  const poll = useCallback(async (firstLook = false) => {
    let s: UpdateStatus;
    try { s = await api<UpdateStatus>("/api/update"); } catch { return; }
    setStatus(s);
    if (s.running) {
      watching.current = true;
      clearTimeout(timer.current);
      timer.current = window.setTimeout(() => poll(), POLL_PROGRESS_MS);
      return;
    }
    if (!watching.current || firstLook) return;   // only report on a run this page followed
    watching.current = false;
    setFinished(true);
    reloadMeta();
    newData();
  }, [reloadMeta, newData]);

  useEffect(() => {
    poll(true);
    return () => clearTimeout(timer.current);
  }, [poll]);

  async function start() {
    try {
      await post("/api/update", {});
      watching.current = true;
      setFinished(false);
      poll();
    } catch (e) {
      toast(messageOf(e));
    }
  }
  return { status, finished, start };
}

function UpdateProgress({ s }: { s: UpdateStatus }) {
  const percent = Math.max(1, Math.min(s.percent ?? 0, 99));
  const left = s.seconds_left && s.seconds_left > 0 ? `about ${duration(s.seconds_left)} left` : "almost done";
  return (
    <div id="updateWrap"><div className="banner">
      <div className="row between wrap">
        <span><b>Updating</b> · {s.step_no ? `Step ${s.step_no} of ${s.steps}: ${s.step}` : "Starting"}</span>
        <span className="small">{Math.round(percent)}% · {left} · {duration(s.elapsed)} so far</span>
      </div>
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(percent)}>
        <div className="fill" style={{ width: `${percent}%` }} />
      </div>
      <div className="small muted-on-banner">You can keep using the app while this runs.</div>
    </div></div>
  );
}

function UpdateFinished({ s }: { s: UpdateStatus }) {
  const last = s.last;
  if (s.exit_code === 0) {
    return (
      <div id="updateWrap"><div className="banner ok">
        <b>Update finished in {duration(s.elapsed)}.</b> Data through {last?.data_through}, nothing missing
        {last?.retrained ? ", models retrained" : ""}. Predictions now use the new data.
      </div></div>
    );
  }
  const missing = last?.missing_games?.length ? ` Missing games: ${last.missing_games.slice(0, 6).join(", ")}.` : "";
  return (
    <div id="updateWrap"><div className="banner bad">
      <b>Update finished with a problem.</b>{missing} The models were {last?.retrained ? "" : "not "}retrained.
      {" "}Details are in the logs folder.<pre>{s.output || ""}</pre>
    </div></div>
  );
}

// ------------------------------------------------------------- "NBALine was updated" notices
// NBALine itself can change while this page is open. New page files: the page offers "Refresh now".
// New Python code only runs once the server starts again: the page offers "Restart now" (NBALine.bat
// starts the server again), waits for it to come back, and reloads. Checked now and then, so the page
// never quietly keeps running an old version.
interface Version { page: number; restart: boolean; can_restart?: boolean }

const RESTART_WAIT_MS = 60_000;   // how long to wait for the restarted server before giving up

function UpdatedNotice() {
  const loadedWith = useRef<number | null>(null);
  const [pageChanged, setPageChanged] = useState(false);
  const [server, setServer] = useState<Version | null>(null);
  const [restart, setRestart] = useState<"" | "waiting" | "failed">("");
  const [error, setError] = useState("");

  useEffect(() => {
    async function check() {
      let v: Version;
      try { v = await api<Version>("/api/version"); } catch { return; }   // server restarting: try again later
      if (loadedWith.current == null) loadedWith.current = v.page;
      else if (v.page !== loadedWith.current) setPageChanged(true);
      setServer(v);
    }
    check();
    const timer = setInterval(check, POLL_VERSION_MS);
    window.addEventListener("focus", check);
    return () => { clearInterval(timer); window.removeEventListener("focus", check); };
  }, []);

  async function restartNow() {
    setError("");
    try {
      await post("/api/restart", {});
    } catch (e) {
      setError(messageOf(e));   // e.g. an update is running
      return;
    }
    setRestart("waiting");
    if (await serverBack()) location.reload();   // the new code is running: show it
    else setRestart("failed");
  }

  if (server?.restart) {
    return (
      <div id="pageNoticeWrap"><div className="banner">
        <b>NBALine was updated.</b>{" "}
        {restart === "waiting" ? "Restarting… the page reloads by itself in a few seconds."
          : restart === "failed" ? "NBALine didn't come back. Close the black NBALine window and double-click NBALine.bat."
          : server.can_restart ? <>Restart it to use the new version.{" "}
              <button className="primary small" onClick={restartNow}>Restart now</button>{" "}
              <span className="small">Takes a few seconds. Your slip and pasted board are kept.</span></>
          : "Close the black NBALine window and double-click NBALine.bat to finish updating."}
        {error && <div className="small">{error}</div>}
      </div></div>
    );
  }
  if (!pageChanged) return null;
  return (
    <div id="pageNoticeWrap"><div className="banner">
      This page has been updated. <button className="primary small" onClick={() => location.reload()}>Refresh now</button>
      {" "}<span className="small">Your slip and pasted board are kept.</span>
    </div></div>
  );
}

/** After a restart: true once the server answers again with the new code running. */
async function serverBack(): Promise<boolean> {
  const wait = (ms: number) => new Promise((done) => setTimeout(done, ms));
  await wait(1500);   // the old server stops half a second after answering
  for (const end = Date.now() + RESTART_WAIT_MS; Date.now() < end; await wait(1000)) {
    try {
      if (!(await api<Version>("/api/version")).restart) return true;
    } catch { /* not back yet */ }
  }
  return false;
}
