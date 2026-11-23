// Tab 4 · Results: your record and profit, and how the model's probabilities did against PrizePicks'
// lines: by stat, by how sure it was, and Goblins and Demons on their own (they aren't meant to be 50/50).
import { useEffect, useState, type ReactNode } from "react";
import { api, messageOf, post } from "../api";
import EntryCard from "../components/EntryCard";
import Seg from "../components/Seg";
import ShowInSteps from "../components/ShowInSteps";
import { useApp } from "../context/AppContext";
import { money, pct, plural } from "../format";
import { useKept } from "../kept";
import { tipProps } from "../labels";
import { loadSectionOpen, loadStatSort, loadStatView, saveSectionOpen, saveStatSort, saveStatView, type StatSort } from "../storage";
import type { Calibration, MoreOnlyKind, ResultsResponse, StatRecord, Summary, SureBand } from "../types";

const BREAK_EVEN = 0.542;   // per pick, 5/6-pick Flex: the bars' marker
const ENOUGH = 20;          // fewer graded lines than this: shown grey, too few to tell anything
const TRUST_NIGHTS = 10;    // graded nights before a stat can be "trusted"

export default function Results() {
  const { dataVersion, toast } = useApp();
  // kept between tab switches: coming back shows the last results at once, and fresh ones replace them quietly
  const [data, setData] = useKept<ResultsResponse | null>("results.data", null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState("Downloads last night's box scores and grades everything (about a minute).");

  const load = () => api<ResultsResponse>("/api/results").then((r) => { setData(r); setError(""); })
    .catch((e) => setError(messageOf(e)));
  useEffect(() => { load(); }, [dataVersion]);   // each visit (in the background), and after an update downloads new games

  async function downloadAndGrade() {
    setBusy(true);
    try {
      const r = await post<{ graded: { picks: number; entries: number } }>("/api/refresh", {});
      toast(`Graded ${plural(r.graded.picks, "pick")}, ${plural(r.graded.entries, "entry", "entries")}`);
      await load();
    } catch (e) {
      setRefreshMsg(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  /** Save what PrizePicks really paid for an entry (null: the app's own amount), then reload, so the
   *  record and profit above follow it. Errors are thrown back to the entry's form. */
  async function setPaid(id: number, amount: number | null) {
    await post(`/api/entries/${id}/paid`, { paid: amount });
    await load();
    toast(amount == null ? "Back to the app's amount." : `Saved: PrizePicks paid ${money(amount)}.`);
  }

  const graded = data?.entries.filter((e) => e.status !== "open") ?? [];   // newest first
  return (
    <section>
      <div className="card">
        <div className="row between wrap">
          <h2>Results</h2>
          <div className="row gap">
            <button className="primary" disabled={busy} onClick={downloadAndGrade}>{busy ? "Updating…" : "Update results"}</button>
            <span className="muted small">{refreshMsg}</span>
          </div>
        </div>
        {error && <div className="error">{error}</div>}
        {data ? <ResultsSummary s={data.summary} calibration={data.calibration} />
          : !error && <p className="muted">Loading results…</p>}
      </div>
      <h3>Graded entries</h3>
      {graded.length > 0 && <p className="muted small">PrizePicks paid a different amount than shown? Press Edit on that
        entry and type in what it paid. Your record and profit above use it.</p>}
      {graded.length ? <ShowInSteps key={data ? graded.length : 0} items={graded} keyOf={(e) => e.id}
          render={(e) => <EntryCard e={e} onPaid={(amount) => setPaid(e.id, amount)} />} />
        : data && <div className="empty">Nothing graded yet.</div>}
    </section>
  );
}

function ResultsSummary({ s, calibration }: { s: Summary; calibration?: Calibration }) {
  const { entries, picks, model } = s;
  return (
    <>
      <div className="stats">
        <Tile label="Entries" value={`${entries.won}-${entries.partial}-${entries.lost}`}
          detail={`won-partial-lost · ${entries.open} open · ${entries.refund} refunded`} />
        <Tile label="Profit" value={money(entries.profit)} detail={`${money(entries.staked)} played · ROI ${roi(entries.roi)}`
          + (entries.protected_losses ? ` · ${plural(entries.protected_losses, "protected loss", "protected losses")} left out` : "")} />
        <Tile label="Your picks" value={pct(picks.hit_rate)} detail={`${picks.hits} of ${picks.graded} hit`} />
        <Tile label="Model vs. PrizePicks" value={model.brier_model == null ? "—" : model.brier_model.toFixed(3)}
          detail={model.brier_model == null ? "graded once games finish"
            : `Brier score (coin flip = 0.250, lower is better) on ${model.graded} standard lines · Goblins and Demons are scored below`} />
        <Tile label="Model's leans" value={pct(model.lean_hit_rate)}
          detail={model.lean_n ? `${model.lean_n} lines where it was 54%+ sure` : "no graded leans yet"} />
        <Tile label="Projection miss" value={model.mae == null ? "—" : `${model.mae.toFixed(1)} pts`} detail="average, Points lines" />
        {calibration && <AdjustmentTile cal={calibration} />}
      </div>
      {model.by_stat && Object.keys(model.by_stat).length > 0
        && <ByStat byStat={model.by_stat} shown={model.by_stat_shown} adjusted={!!calibration?.on} />}
      {model.by_sure && <BySure bands={model.by_sure} />}
      <GoblinsAndDemons s={s} />
      <SavedLines saved={s.saved} />
    </>
  );
}

/** A labelled number: big value, small description underneath. */
function Tile({ label, value, detail }: { label: ReactNode; value: ReactNode; detail?: ReactNode }) {
  return <div className="stat"><div className="k">{label}</div><div className="v">{value}</div><div className="d">{detail}</div></div>;
}

const roi = (x: number | null) => (x == null ? "—" : `${(x * 100).toFixed(1)}%`);

/** A collapsible section whose open/closed state is remembered in this browser. */
function Fold({ name, title, headline, children }: { name: string; title: string; headline: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(() => loadSectionOpen(name));
  return (
    <details className="by-stat" open={open} onToggle={(e) => {
      const now = e.currentTarget.open;
      setOpen(now);
      saveSectionOpen(name, now);
    }}>
      <summary><h3>{title}</h3><span className="muted small">{headline}</span></summary>
      {children}
    </details>
  );
}

// ------------------------------------------------------------- hit rates against the break-even
/** How sure we can be of a hit rate p over n lines: the ± of its likely range (95%). */
const margin = (p: number, n: number) => 1.96 * Math.sqrt(Math.max(p * (1 - p), 0.0025) / n);

/** A hit rate's row colour (vs. break-even) and hover text (its likely range). */
function rateLook(p: number, n: number) {
  if (n < ENOUGH) return { look: "few", hint: `Only ${n} lines: too few to tell` };
  const m = margin(p, n);
  return { look: p >= BREAK_EVEN ? "good" : p < 0.5 ? "bad" : "close",
           hint: `Probably between ${pct(Math.max(p - m, 0))} and ${pct(Math.min(p + m, 1))}` };
}

const RateCell = ({ p, n }: { p: number; n: number }) =>
  <td className="num"><b className="rate">{pct(p)}</b> <span className="pm">±{Math.round(margin(p, n) * 100)}</span></td>;

const RateLegend = () => (
  <p className="muted small legend keys">
    <span className="li"><span className="key good" />at or above break-even</span>
    <span className="li"><span className="key close" />50–54%</span>
    <span className="li"><span className="key bad" />under 50%</span>
    <span className="li"><span className="key few" />under {ENOUGH} lines, too few to tell</span>
    <span className="li"><span className="db-key be" />{pct(BREAK_EVEN)} break-even</span>
    <span className="li"><span className="key range" />where the true rate probably is (±)</span>
  </p>
);

/** A hit rate's likely range (±, 95%) drawn on a chart: a vertical line at its low end and one at its
 *  high end. When they sit on both sides of the break-even line, the rate isn't clearly above (or
 *  below) it yet. `at` turns a rate into a position on that chart. */
function RangeBand({ p, n, at }: { p: number; n: number; at: (x: number) => string }) {
  const m = margin(p, n), lo = Math.max(p - m, 0), hi = Math.min(p + m, 1);
  const title = `Probably between ${pct(lo)} and ${pct(hi)}`;
  return (
    <>
      <div className="range" title={title} style={{ left: at(lo) }} />
      <div className="range" title={title} style={{ left: at(hi) }} />
    </>
  );
}

/** How far the model's chance was from what happened: "4.4 pts too high" (amber), or "about right". */
function Gap({ said, happened }: { said: number; happened: number }) {
  const points = (said - happened) * 100;
  if (Math.abs(points) < 2) return <>about right</>;
  return <b className={`gap ${points > 0 ? "high" : "low"}`}>{Math.abs(points).toFixed(1)} pts too {points > 0 ? "high" : "low"}</b>;
}

// ------------------------------------------------------------- Model's pick by stat
// One row per stat: lines graded, how often the model's side (whichever it favoured) was right with
// its likely range, and a bar with a marker at the break-even. Click a header to sort by it.
type StatRow = [stat: string, record: StatRecord];

const STAT_COLUMNS: [StatSort["by"], string, string][] = [["stat", "Stat", ""], ["lines", "Lines", "num"], ["right", "Right", "num"],
  ["breakeven", `vs. break-even (${pct(BREAK_EVEN)})`, ""]];   // "Right" and "vs. break-even" both sort by hit rate

/** The rows in the chosen order; ties go to the stat with more lines. Sorted by hit rate, stats with
 *  too few lines to tell (grey) come after the rest, so a lucky 12 of 15 doesn't top the list. */
function sortStats(rows: StatRow[], { by, desc }: StatSort) {
  const value = (r: StatRow) => (by === "stat" ? r[0] : by === "lines" ? r[1].n : r[1].hit_rate);
  const fewLast = by === "right" || by === "breakeven";
  return [...rows].sort((a, b) => {
    const fewA = a[1].n < ENOUGH, fewB = b[1].n < ENOUGH;
    if (fewLast && fewA !== fewB) return fewA ? 1 : -1;
    const x = value(a), y = value(b);
    const order = typeof x === "string" ? x.localeCompare(y as string) : x - (y as number);
    return (desc ? -order : order) || b[1].n - a[1].n;
  });
}

/** A stat is trusted once it has TRUST_NIGHTS graded nights and even the low end of its likely range
 *  is at or above break-even: right often enough, over enough lines and nights, that luck is an
 *  unlikely explanation. (Same-night lines move together, so lines alone aren't enough.) */
const lowEnd = (v: StatRecord) => v.hit_rate - margin(v.hit_rate, v.n);
const isTrusted = (v: StatRecord) => v.nights >= TRUST_NIGHTS && lowEnd(v) >= BREAK_EVEN;

/** The table counts every graded standard line, or (Shown picks) only the ones the page would show as
 *  picks today, with today's chance adjustment on every night. */
function ByStat({ byStat, shown, adjusted }: { byStat: Record<string, StatRecord>; shown?: Record<string, StatRecord>;
                                              adjusted: boolean }) {
  const [sort, setSort] = useState(loadStatSort);
  const [view, setView] = useState(loadStatView);
  const showing = view === "shown" && shown ? "shown" : "all";
  const rows = Object.entries(showing === "shown" ? shown! : byStat);

  /** A header click: sort by that column, or flip the order if it's already sorted by it. A new column
   *  starts with its natural order: most lines / highest rate first, stats A to Z. */
  function sortBy(by: StatSort["by"]) {
    const next = { by, desc: sort.by === by ? !sort.desc : by !== "stat" };
    setSort(next);
    saveStatSort(next);
  }

  // the closed section still says the headline: how many stats have enough lines, how many of those win, and trust
  const enough = rows.filter(([, v]) => v.n >= ENOUGH);
  const winning = enough.filter(([, v]) => v.hit_rate >= BREAK_EVEN).length;
  const trusted = rows.filter(([, v]) => isTrusted(v)).length;
  const nights = Math.max(0, ...rows.map(([, v]) => v.nights ?? 0));
  const headline = <>
    {showing === "shown" && "Shown picks · "}
    {enough.length ? `${enough.length} of ${rows.length} stats have ${ENOUGH}+ lines · ${winning} of those at or above break-even`
      : `${rows.length} stats · none has ${ENOUGH} graded lines yet`}
    {trusted ? <> · <b>{trusted} trusted</b></>
      : nights < TRUST_NIGHTS ? ` · trusted needs ${TRUST_NIGHTS} nights (${nights} so far)` : " · none trusted yet"}
  </>;

  return (
    <Fold name="byStat" title="Model's pick by stat" headline={headline}>
      <div className="row between wrap gap stat-view">
        <p className="muted small">{showing === "shown"
          ? `Only the lines the page would show as picks today: ${pct(BREAK_EVEN)}+ for one side`
            + (adjusted ? " after today's chance adjustment, on every night (also the ones before it switched on)." : ".")
          : "How often the side the model favoured was right, on every graded standard line."} Click a column to sort by it.</p>
        {shown && <Seg small label="Which lines the table counts" value={showing} onChange={(v) => { setView(v); saveStatView(v); }}
          options={[{ value: "all", label: "All lines", title: "Every graded standard line, however slight the model's lean" },
                    { value: "shown", label: "Shown picks", title: `Only the lines it would show as picks today (${pct(BREAK_EVEN)}+)` }]} />}
      </div>
      {!rows.length && <p className="muted small">No graded lines at {pct(BREAK_EVEN)}+ yet.</p>}
      <table className="stat-table">
        <thead><tr>
          {STAT_COLUMNS.map(([by, label, cls]) => {
            const on = sort.by === by;
            return (
              <th key={by} className={cls} aria-sort={on ? (sort.desc ? "descending" : "ascending") : undefined}>
                <button className={`sort${on ? " on" : ""}`} onClick={() => sortBy(by)}>
                  {label}<span className="arrow" aria-hidden="true">{on && !sort.desc ? "▲" : "▼"}</span>
                </button>
              </th>
            );
          })}
        </tr></thead>
        <tbody>
          {sortStats(rows, sort).map(([stat, v]) => {
            const { look, hint } = rateLook(v.hit_rate, v.n);
            return (
              <tr key={stat} className={look} title={hint}>
                <td>{stat}{isTrusted(v) && <> <TrustedBadge v={v} /></>}</td>
                <td className="num">{v.n}</td>
                <RateCell p={v.hit_rate} n={v.n} />
                <td className="bar-cell"><div className="hit-bar">
                  <div className="fill" style={{ width: `${v.hit_rate * 100}%` }} />
                  <RangeBand p={v.hit_rate} n={v.n} at={(x) => `${x * 100}%`} />
                  <div className="be" style={{ left: `${BREAK_EVEN * 100}%` }} />
                </div></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <RateLegend />
      <p className="muted small legend"><span className="badge trusted">trusted</span> {TRUST_NIGHTS}+ graded nights, and even the
        low end of its ± is above break-even</p>
    </Fold>
  );
}

function TrustedBadge({ v }: { v: StatRecord }) {
  const tip = `Right on ${pct(v.hit_rate)} of ${v.n} lines over ${v.nights} nights. `
    + `Even the low end of its likely range, ${pct(lowEnd(v))}, is above the ${pct(BREAK_EVEN)} break-even.`;
  return <span className="badge trusted" {...tipProps(tip)}>trusted</span>;
}

// ------------------------------------------------------------- the chance adjustment
/** The chance adjustment (nbaline/pickem/calibration.py): it pulls the model's chances toward 50%
 *  by what its record against PrizePicks says, and switches itself on only after enough nights and a
 *  win when tested on nights it wasn't learned from. */
function AdjustmentTile({ cal }: { cal: Calibration }) {
  const example = cal.keep == null ? "" : `70% → ${pct(0.5 + cal.keep * 0.2)}`;
  const test = cal.test && `Brier ${cal.test.brier_adjusted.toFixed(3)} vs ${cal.test.brier_model.toFixed(3)} unadjusted, `
    + `better on ${cal.test.nights_better} of ${plural(cal.test.nights, "later night")}`;
  const detail = cal.on ? `Every standard line's chance is pulled toward 50%: ${example} · ${test}`
    : cal.nights < cal.min_nights
      ? `Switches on by itself after ${cal.min_nights} graded nights (${cal.nights} so far) if it beats the model's own chances `
        + `on later nights${example ? ` · today it would make ${example}` : ""}`
      : `Didn't beat the model's own chances on later nights: ${test}`;
  return <Tile label="Chance adjustment" value={cal.on ? "On" : "Off"} detail={detail} />;
}

// ------------------------------------------------------------- Model's pick by how sure it was
/** "54–60%", or "70%+" for the top group. */
const sureLabel = (b: SureBand) => (b.high >= 1 ? `${Math.round(b.low * 100)}%+` : `${Math.round(b.low * 100)}–${Math.round(b.high * 100)}%`);

const rightRate = (b: SureBand) => b.right / b.n;

/** Is the model right more often when it's surer, and as often as it says? Standard lines grouped by
 *  its chance for the side it favoured. Each row: what it said, how often it was right, a small chart
 *  of the two, and how much too sure it was. A plain-words summary sits on top. */
function BySure({ bands: all }: { bands: SureBand[] }) {
  const bands = all.filter((b) => b.n);
  if (!bands.length) return null;
  // the closed section still says the headline: its weakest picks against its strongest (with enough lines)
  const picks = bands.filter((b) => b.low > 0.5), weak = picks[0];
  const strong = picks.filter((b) => b.n >= ENOUGH).at(-1);
  const rate = (b: SureBand) => `${sureLabel(b)} sure: right ${pct(rightRate(b))}`;
  const headline = weak && strong && strong !== weak ? `${rate(weak)} · ${rate(strong)}` : "is it right more often when it's surer?";
  return (
    <Fold name="bySure" title="Model's pick by how sure it was" headline={headline}>
      <SureTakeaway picks={picks} />
      <table className="stat-table sure-table">
        <thead><tr>
          <th>Model's chance</th><th className="num">Lines</th><th className="num">Said → right</th>
          <th className="db-cell"><div className="db-scale"><span>{pct0(SCALE[0])}</span>
            <span className="db-scale-be" style={{ left: at(BREAK_EVEN) }} title={`${pct(BREAK_EVEN)} break-even`}>{pct0(BREAK_EVEN)}</span>
            <span>{pct0(SCALE[1])}</span></div></th>
          <th className="num">Too sure by</th>
        </tr></thead>
        <tbody>
          {bands.map((b) => {
            const right = rightRate(b), { look, hint } = rateLook(right, b.n);
            return (
              <tr key={b.low} className={look} title={`Said ${pct(b.model_said)} on average, right ${pct(right)}. ${hint}.`}>
                <td>{b.low > 0.5 ? sureLabel(b) : <>Under {pct0(BREAK_EVEN)}<div className="muted small">no pick</div></>}</td>
                <td className="num">{b.n}</td>
                <td className="num">{pct(b.model_said)} → <b className="rate">{pct(right)}</b> <span className="pm">±{Math.round(margin(right, b.n) * 100)}</span></td>
                <td className="db-cell"><SaidVsRight said={b.model_said} right={right} n={b.n} look={look} /></td>
                <td className="num"><TooSure said={b.model_said} right={right} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="muted small legend keys chart-legend">
        <span className="li"><span className="db-key said" />what the model said</span>
        <span className="li"><span className="db-key right" />how often it was right</span>
        <span className="li"><span className="key whisker" />where the true rate probably is (±)</span>
        <span className="li"><span className="db-key be" />{pct(BREAK_EVEN)} break-even</span>
      </p>
      <p className="muted small legend keys chart-legend">
        <span className="li">Dot colour:</span>
        <span className="li"><span className="key good" />above break-even</span>
        <span className="li"><span className="key close" />50–54%</span>
        <span className="li"><span className="key bad" />under 50%</span>
        <span className="li"><span className="key few" />under {ENOUGH} lines</span>
      </p>
    </Fold>
  );
}

/** The table in plain words: is it right more often when it's surer, is it as right as it says, and
 *  which groups clear the break-even (and whether that's proven yet). */
function SureTakeaway({ picks }: { picks: SureBand[] }) {
  const enough = picks.filter((b) => b.n >= ENOUGH);
  if (!enough.length) return <p className="takeaway">Not enough graded picks yet to tell how the model does when it's surer.</p>;
  const weak = enough[0], strong = enough.at(-1)!;
  const climb = rightRate(strong) - rightRate(weak);
  const n = enough.reduce((sum, b) => sum + b.n, 0);
  const tooSure = enough.reduce((sum, b) => sum + b.n * (b.model_said - rightRate(b)), 0) / n;   // weighted by lines
  const clear = enough.filter((b) => rightRate(b) >= BREAK_EVEN);
  const proven = clear.filter((b) => rightRate(b) - margin(rightRate(b), b.n) >= BREAK_EVEN);

  const surer = strong === weak ? null
    : climb >= 0.03 ? <>The surer the model is, the more often it's right: <b>{pct(rightRate(weak))}</b> of its {sureLabel(weak)} picks,
        {" "}<b>{pct(rightRate(strong))}</b> of its {sureLabel(strong)} picks. </>
    : <>Being surer hasn't made it right more often yet ({pct(rightRate(weak))} at {sureLabel(weak)}, {pct(rightRate(strong))} at {sureLabel(strong)}). </>;
  const honest = tooSure >= 0.02 ? <>But it's right less often than it says: about <b>{Math.round(tooSure * 100)} points</b> less on average. </>
    : tooSure <= -0.02 ? <>It's right a little more often than it says. </> : <>It's about as right as it says. </>;
  const which = clear.length === enough.length ? "All its picks are" : `Only its ${andList(clear.map(sureLabel))} picks are`;
  const beats = !clear.length ? <>None of its picks are above the {pct(BREAK_EVEN)} break-even yet.</>
    : <>{which} above the {pct(BREAK_EVEN)} break-even{proven.length === clear.length ? "."
        : `, and even ${clear.length === 1 ? "that isn't" : "those aren't"} proven yet: the ± still reaches below it.`}</>;
  return <p className="takeaway">{surer}{honest}{beats}</p>;
}

const andList = (items: string[]) => (items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`);
const pct0 = (p: number) => `${Math.round(p * 100)}%`;

// The said-vs-right chart runs from 40% to 80% (where these numbers live): the break-even dashed, a
// bracket ├──┤ over the range the true rate is probably in, a dot at how often it was right (in the
// middle of it), and a ring at what the model said. A ring outside the bracket: it was too sure.
const SCALE = [0.4, 0.8];
const at = (p: number) => `${Math.min(Math.max((p - SCALE[0]) / (SCALE[1] - SCALE[0]), 0), 1) * 100}%`;

function SaidVsRight({ said, right, n, look }: { said: number; right: number; n: number; look: string }) {
  const m = margin(right, n), lo = Math.max(right - m, 0), hi = Math.min(right + m, 1);
  return (
    <div className={`dumbbell ${look}`} aria-hidden="true">
      <div className="db-track" />
      <div className="db-be" style={{ left: at(BREAK_EVEN) }} />
      <div className="db-range" title={`Probably between ${pct(lo)} and ${pct(hi)}`}
        style={{ left: at(lo), width: `calc(${at(hi)} - ${at(lo)})` }} />
      <div className="db-said" style={{ left: at(said) }} />
      <div className={`db-right ${look}`} style={{ left: at(right) }} />
    </div>
  );
}

/** How much too sure the model was: "4.7 pts" (amber), "about right", or "too cautious by 3.1". */
function TooSure({ said, right }: { said: number; right: number }) {
  const points = (said - right) * 100;
  if (Math.abs(points) < 2) return <>about right</>;
  return points > 0 ? <b className="gap high">{points.toFixed(1)} pts</b>
    : <b className="gap low">too cautious by {(-points).toFixed(1)}</b>;
}

// ------------------------------------------------------------- Goblins & Demons
// More-only lines aren't meant to be 50/50: Goblins are easy lines, Demons hard ones. So each kind is
// scored on whether the model's chance matched how often its lines went over.
const KINDS = { goblin: "Goblins", demon: "Demons" } as const;
type Kind = keyof typeof KINDS;

function GoblinsAndDemons({ s }: { s: Summary }) {
  const kinds = s.more_only, entries = s.entries_more_only;
  const seen = (Object.keys(KINDS) as Kind[]).some((k) => kinds[k].lines.n || kinds[k].picks.n);
  if (!seen && !entries.graded && !entries.open) return null;
  return (
    <>
      <h3 style={{ margin: "18px 0 8px" }}>Goblins &amp; Demons</h3>
      <div className="stats">
        <KindTile kind="goblin" k={kinds.goblin} />
        <KindTile kind="demon" k={kinds.demon} />
        <Tile label="Entries with them" value={entries.graded ? money(entries.profit) : "—"} detail={entries.graded
          ? `${entries.won} won of ${entries.graded} · ROI ${roi(entries.roi)}${entries.open ? ` · ${entries.open} open` : ""}`
          : `${entries.open} open`} />
      </div>
      <ByChance kinds={kinds} />
    </>
  );
}

/** One kind's headline: how often its lines went over, what the model said, and your picks. */
function KindTile({ kind, k: { lines, picks } }: { kind: Kind; k: MoreOnlyKind }) {
  const name = <span className={`badge ${kind}`}>{KINDS[kind]}</span>;
  if (!lines.n && !picks.n) return <Tile label={name} value="—" detail="none graded yet" />;
  return (
    <Tile label={name} value={pct(lines.went_over)} detail={<>
      went over, in {lines.n} lines · model said {pct(lines.model_said)},{" "}
      {lines.model_said != null && lines.went_over != null && <Gap said={lines.model_said} happened={lines.went_over} />}
      {picks.n > 0 && <><br />Your picks: {picks.hits} of {picks.n} hit (model expected {pct(picks.model_expected)})</>}
    </>} />
  );
}

/** Is "the model said 30%" really about 30%? Each kind's lines grouped by the model's chance. */
function ByChance({ kinds }: { kinds: Summary["more_only"] }) {
  const groups = (Object.keys(KINDS) as Kind[]).filter((k) => kinds[k].lines.n);
  if (!groups.length) return null;
  return (
    <Fold name="byChance" title="By the model's chance" headline={`is "the model said 30%" really about 30%?`}>
      <table className="stat-table chance-table">
        <thead><tr><th>Model's chance</th><th className="num">Lines</th><th className="num">Model said</th>
          <th className="num">Went over</th><th className="num">Model was</th></tr></thead>
        <tbody>
          {groups.flatMap((k) => [
            <tr key={k} className="group"><td colSpan={5}><span className={`badge ${k}`}>{KINDS[k]}</span></td></tr>,
            ...kinds[k].lines.bands.map((b) => (
              <tr key={`${k}-${b.low}`} className={b.n < ENOUGH ? "few" : ""} title={b.n < ENOUGH ? `Only ${b.n} lines: too few to tell` : undefined}>
                <td>{Math.round(b.low * 100)}–{Math.round(b.high * 100)}%</td><td className="num">{b.n}</td>
                <td className="num">{pct(b.model_said)}</td><td className="num"><b>{pct(b.went_over)}</b></td>
                <td className="num"><Gap said={b.model_said} happened={b.went_over} /></td>
              </tr>
            )),
          ])}
        </tbody>
      </table>
      <p className="muted small legend"><span className="key few" />under {ENOUGH} lines, too few to tell</p>
    </Fold>
  );
}

/** How many PrizePicks lines have been saved from your pastes and checks, and where each one went:
 *  graded and counted, or why not. The rows add up to the saved total. */
function SavedLines({ saved: s }: { saved: Summary["saved"] }) {
  const n = (x: number) => x.toLocaleString();
  const notCounted: [number, string, string][] = [
    [s.waiting_lines, `Waiting for games to finish${s.waiting ? ` (${plural(s.waiting, "day")})` : ""}`,
      "Graded once the games are over and Update results downloads the box scores."],
    [s.void, "Player didn't play", "PrizePicks removes the pick."],
    [s.push, "Push: landed exactly on the line", "PrizePicks removes the pick."],
    [s.moved, "Line moved later that day", "Only the last line you saw before tip-off counts for each player and stat."],
    [s.no_model, "No model chance", "The model had no prediction for it."],
  ];
  const headline = `${n(s.lines)} lines over ${plural(s.days, "day")} (${plural(s.boards, "pasted board")}) · ${n(s.graded)} graded`
    + (s.waiting_lines ? ` · ${n(s.waiting_lines)} waiting for games` : "");
  return (
    <Fold name="savedLines" title="PrizePicks lines saved" headline={headline}>
      <table className="stat-table saved-table">
        <tbody>
          <tr><td><b>Saved</b><div className="muted small">Every line you pasted or checked: player, day, stat and line.</div></td>
            <td className="num"><b>{n(s.lines)}</b></td></tr>
          {notCounted.filter(([count]) => count > 0).map(([count, label, why]) => (
            <tr key={label}><td>{label}<div className="muted small">{why}</div></td><td className="num">−{n(count)}</td></tr>
          ))}
          <tr><td><b>Graded and counted</b><div className="muted small">What the model is scored on above.</div></td>
            <td className="num"><b>{n(s.graded)}</b></td></tr>
        </tbody>
      </table>
      <p className="muted small">A push or a player who didn't play is neither a win nor a loss for either side, so it can't
        score the model. Goblins and Demons count once per line, standard lines once per player and stat a day.</p>
    </Fold>
  );
}
