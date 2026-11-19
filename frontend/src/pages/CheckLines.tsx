// Tab 2 · Check lines: type players and PrizePicks lines, get the model's take on each.
// For a past date it also shows what actually happened and whether the model's pick was right;
// for a game in progress, its live box score and the model's chance from here.
import { useState } from "react";
import { messageOf, post } from "../api";
import { LessTestedBadge, RoleBadge } from "../components/Badges";
import { Injuries, Projection, ReasonList, RecentGames } from "../components/LineDetails";
import { LiveBox, useLiveLines } from "../components/Live";
import { useApp } from "../context/AppContext";
import { useSlip } from "../context/SlipContext";
import { pct, shortDay } from "../format";
import { useKept } from "../kept";
import { chanceTitle, LEAN_AT } from "../labels";
import type { LineResult, LiveState, Side } from "../types";

interface Row { id: number; player: string; stat: string; line: string }

let nextRowId = 1;
const emptyRow = (): Row => ({ id: nextRowId++, player: "", stat: "Points", line: "" });

export default function CheckLines() {
  const { meta, gameDate, setGameDate, gamesInfo, toast } = useApp();
  const [rows, setRows] = useKept<Row[]>("check.rows", () => [emptyRow(), emptyRow(), emptyRow(), emptyRow()]);
  const [results, setResults] = useKept<LineResult[] | null>("check.results", null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const be = meta.break_even;

  const change = (id: number, field: keyof Row, value: string) =>
    setRows(rows.map((r) => (r.id === id ? { ...r, [field]: value } : r)));

  async function analyze() {
    const filled = rows.map((r) => ({ player: r.player.trim(), stat: r.stat, line: r.line }))
      .filter((r) => r.player && r.line !== "");
    if (!filled.length) return toast("Type at least one player and line.");
    setBusy(true);
    try {
      const r = await post<{ results: LineResult[] }>("/api/analyze", { date: gameDate, rows: filled });
      setResults(r.results);
      setError("");
    } catch (e) {
      setResults(null);
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <div className="card">
        <div className="row between wrap">
          <h2>Type the PrizePicks lines</h2>
          <label className="inline">Game date <input type="date" value={gameDate} onChange={(e) => setGameDate(e.target.value)} /></label>
        </div>
        <p className="muted">{gamesInfo}</p>
        {rows.map((r) => (
          <div className="line-row" key={r.id}>
            <input className="player" list="playerList" placeholder="Player name" autoComplete="off"
              value={r.player} onChange={(e) => change(r.id, "player", e.target.value)} />
            <select className="stat" value={r.stat} onChange={(e) => change(r.id, "stat", e.target.value)}>
              {meta.stats.map((s) => <option key={s}>{s}</option>)}
            </select>
            <input className="line" type="number" step="0.5" placeholder="Line" value={r.line}
              onChange={(e) => change(r.id, "line", e.target.value)} onKeyDown={(e) => e.key === "Enter" && analyze()} />
            <button className="remove ghost" title="Remove row" aria-label="Remove row"
              onClick={() => setRows(rows.filter((x) => x.id !== r.id))}>✕</button>
          </div>
        ))}
        <div className="row gap">
          <button className="ghost" onClick={() => setRows([...rows, emptyRow()])}>+ Add row</button>
          <button className="primary" disabled={busy} onClick={analyze}>{busy ? "Running the model…" : "Analyze"}</button>
          <span className="muted">{busy ? "about 10 seconds" : ""}</span>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {results && <ResultCards results={results} />}
      <p className="muted small">
        Per-pick win rate needed to break even: Power 2-pick {pct(be.power["2"])}, 3-pick {pct(be.power["3"])},
        6-pick {pct(be.power["6"])} · Flex 5/6-pick {pct(be.flex["6"])}. "Lean" means the model is at least {pct(LEAN_AT)} on one side.
      </p>
    </section>
  );
}

/** Every result, with live box scores for games that are on (followed every 15 seconds). */
function ResultCards({ results }: { results: LineResult[] }) {
  const started = results.map((r, i) => ({ id: String(i), r })).filter(({ r }) => r.started && !r.final && !r.error);
  const live = useLiveLines(started);
  return <>{results.map((r, i) => <ResultCard key={i} r={r} live={r.started && !r.final ? live[String(i)] ?? null : undefined} />)}</>;
}

/** One line: the model's chance of each side, the live game or the final result, who's out, his last
 *  games, the model's reasons, and + More / + Less to put it on the slip. `live` is null for a started
 *  game whose live box score hasn't come in yet. */
function ResultCard({ r, live }: { r: LineResult; live?: LiveState | null }) {
  const { pickFor, togglePick } = useSlip();
  if (r.error) {
    return <div className="res"><div className="name">{r.player} · {r.stat} {r.line}</div><div className="error">{r.error}</div></div>;
  }
  const pick = pickFor(r);
  const addButton = (side: Side) => {
    const on = pick?.side === side;
    return (
      <button className={`${side}${on ? " on" : ""}`} title={on ? "On your entry slip. Click to take it off." : ""}
        onClick={() => togglePick(r, side)}>
        {on ? "✓" : "+"} {side === "more" ? "More" : "Less"}
      </button>
    );
  };
  return (
    <div className={`res${pick ? " added" : ""}`}>
      <div className="head">
        <div><span className="name">{r.player}</span>{" "}
          <span className="meta">{r.team} {r.home ? "vs" : "@"} {r.opp} · {r.tip_local}</span></div>
        <span className="tag">{r.stat} {r.line}</span>
      </div>
      {r.modeled ? <ModelSection r={r} /> : <HistoryOnly r={r} />}
      {live !== undefined && <LiveBox r={r} x={live ?? undefined} />}
      <FinalResult r={r} />
      <Injuries r={r} />
      <RecentGames r={r} />
      {!!r.reasons?.length && <details><summary>Why the model thinks this</summary><ReasonList r={r} /></details>}
      <div className="add">{addButton("more")}{addButton("less")}</div>
    </div>
  );
}

/** The More/Less bar, the lean, and the projection. */
function ModelSection({ r }: { r: LineResult }) {
  const pMore = r.p_over ?? 0;
  const pLess = Math.round((1 - pMore) * 1000) / 1000;   // so the two sides add up to 100%
  return (
    <>
      <div className="split" title={chanceTitle(r, "Model's chance of each side")}>
        <div className="m" style={{ width: `${Math.max(pMore * 100, 14)}%` }}>MORE {pct(pMore)}</div>
        <div className="l" style={{ width: `${Math.max(pLess * 100, 14)}%` }}>LESS {pct(pLess)}</div>
      </div>
      <div className="row between wrap">
        <div>
          {pMore >= LEAN_AT ? <span className="lean more">Lean MORE</span>
            : pLess >= LEAN_AT ? <span className="lean less">Lean LESS</span>
            : <span className="muted">No clear edge</span>}
          {!r.reliable && <> <LessTestedBadge lowMinutes={r.low_minutes} /></>}
          {" "}<RoleBadge r={r} />
        </div>
        <div className="meta"><Projection r={r} /></div>
      </div>
    </>
  );
}

function HistoryOnly({ r }: { r: LineResult }) {
  const h = r.history!;
  return (
    <div className="notes">No model for {r.stat} yet. History only: averaging <b>{h.avg10 ?? "—"}</b> over the
      last {h.n10} games, above {r.line} in <b>{h.over10} of {h.n10}</b>.</div>
  );
}

/** A game that's over: what the model would have said before tip-off vs. what happened. */
function FinalResult({ r }: { r: LineResult }) {
  if (!r.final) return null;
  const how = <div className="small muted">The model only used games before {shortDay(r.game_date!)}, so this is what it would have said before tip-off.</div>;
  if (r.outcome === "dnp") {
    return <div className="final">Final: <b>{r.player} didn't play</b>. On PrizePicks the pick is removed and the entry drops a size.{how}</div>;
  }
  const went = r.outcome === "push" ? "landed exactly on the line (push)" : <>went <b>{r.outcome === "over" ? "MORE" : "LESS"}</b></>;
  if (r.p_over == null) return <div className="final">Final: <b>{r.actual}</b> {r.stat} · {went}.</div>;

  const side = r.p_over >= 0.5 ? "more" : "less";
  const chance = side === "more" ? r.p_over : 1 - r.p_over;
  const right = r.outcome === "push" ? null : (r.outcome === "over") === (side === "more");
  return (
    <div className={`final ${right == null ? "" : right ? "ok" : "bad"}`}>
      Final: <b>{r.actual}</b> {r.stat} · {went} (line {r.line}).{" "}
      Model's pick: <b>{side.toUpperCase()}</b> {pct(chance)}{chance < LEAN_AT ? " (no clear edge)" : ""} ·{" "}
      <b>{right == null ? "push" : right ? "✓ right" : "✗ wrong"}</b>{how}
    </div>
  );
}
