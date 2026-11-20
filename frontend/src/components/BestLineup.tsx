// Best lines › Best lineup: the entry to play from a pasted board (nbaline/pickem/lineup.py). Copy gives
// a plain list to follow while building the entry on PrizePicks; "Put on my slip" loads it onto the
// entry slip, so it can be saved in My entries once it's played. Each pick shows how its stat's lines
// like these have done against PrizePicks (calibration.stat_records).
import { useApp } from "../context/AppContext";
import { useSlip } from "../context/SlipContext";
import { dayName, pct, plural } from "../format";
import { tipProps } from "../labels";
import type { BoardResult, LineRecord, LineResult, Lineup } from "../types";

type Records = BoardResult["stat_records"];

const sideWord = (x: LineResult) => (x.side === "more" ? "MORE" : "LESS");
const entryName = (l: Lineup) => `${l.size}-pick ${l.kind === "power" ? "Power" : "Flex"}`;

/** The lineup as plain text, one pick per line: "1. Jalen Brunson (NYK) · Assists · MORE 6.5". */
export function lineupText(l: Lineup, date: string): string {
  return [`${entryName(l)} · ${dayName(date)}`,
    ...l.picks.map((x, i) => `${i + 1}. ${x.player} (${x.team}) · ${x.stat} · ${sideWord(x)} ${x.line}`)].join("\n");
}

/** Copy to the clipboard, falling back to a hidden text box where the clipboard API isn't allowed. */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const box = document.createElement("textarea");
    box.value = text;
    box.style.cssText = "position: fixed; opacity: 0";
    document.body.appendChild(box);
    box.select();
    const copied = document.execCommand("copy");
    box.remove();
    return copied;
  }
}

const VERDICT_TEXT: Record<LineRecord["verdict"], string> = {
  winning: "even its low end is above the break-even",
  losing: "even its high end is below the break-even",
  unclear: "not clearly above or below the break-even yet",
  few: "too few lines to tell yet",
};

/** Hover text for a stat's record: what was counted, how it went, and what that says. */
const recordTip = (stat: string, r: LineRecord, atLeast: number) =>
  `${stat} lines the page showed at ${pct(atLeast)} or more, once graded: ${r.right} of ${r.lines} right (${pct(r.rate)}).`
  + ` Likely range ${pct(r.low)} to ${pct(r.high)}: ${VERDICT_TEXT[r.verdict]}.`;

/** "⚠ Losing record" on a line whose stat has clearly lost on lines like it (Best lines' ranked list). */
export function LosingBadge({ stat, r, atLeast }: { stat: string; r: LineRecord; atLeast: number }) {
  return <span className="badge bad" {...tipProps(`${recordTip(stat, r, atLeast)} Left out of the Best lineup.`)}>⚠ Losing record</span>;
}

export default function BestLineup({ lineup: l, date, records }: { lineup: Lineup; date: string; records: Records }) {
  const { meta, toast } = useApp();
  const { loadLineup } = useSlip();
  const qualify = `${plural(l.candidates, "standard line")} clear ${pct(l.break_even)} (${plural(l.players, "player")})`;
  const losing = Object.entries(l.losing || {});
  const leftOut = losing.length > 0 && (
    <p className="small warn-text">⚠ Left out for a losing record on lines like these:{" "}
      {losing.map(([stat, n]) => `${stat} (${plural(n, "line")} tonight)`).join(", ")}.</p>
  );

  if (!l.size) {
    return (
      <div className="card lineup">
        <div className="row between wrap"><h2>Best lineup</h2><span className="muted small">{qualify}</span></div>
        <p className="small">Not enough for a 6- or 5-pick Flex tonight: a weaker pick would pull the whole entry below
          the {pct(l.break_even)} break-even.{l.picks.length > 0 && " The ones that clear it:"}</p>
        {l.picks.length > 0 && <LineupPicks picks={l.picks} records={records} />}
        {leftOut}
      </div>
    );
  }

  const table = meta.payouts[l.kind]?.[String(l.size)] || {};
  const paysAt = Object.entries(table).sort(([a], [b]) => Number(b) - Number(a)).map(([, m]) => `${m}x`).join(" / ");
  async function copy() {
    toast(await copyText(lineupText(l, date)) ? "Copied the lineup" : "Couldn't copy here: select the picks and copy them instead");
  }

  return (
    <div className="card lineup">
      <div className="row between wrap">
        <h2>Best lineup · {entryName(l)}</h2>
        <span className="muted small">{l.title} · {qualify}</span>
      </div>
      <LineupPicks picks={l.picks} records={records} />
      <div className="row between wrap gap lineup-sum">
        <span className="small">
          Average <b>{pct(l.avg_chance)}</b> per pick · returns <b>${l.ev!.toFixed(2)}</b> per $1 at the standard
          payouts ({paysAt}) · chance of a profit {pct(l.p_profit)} · all {l.size} hit {pct(l.p_all)}
        </span>
        <span className="row gap">
          <button className="primary" onClick={copy}>Copy</button>
          <button className="ghost" title="Replace your entry slip with this lineup" onClick={() => loadLineup(l.picks, l.kind)}>
            Put on my slip
          </button>
        </span>
      </div>
      {leftOut}
      <p className="muted small">Standard lines only, best chance first, each at or above the {pct(l.break_even)} break-even, from
        well-tested stats: one pick per player and at most 2 from one game. Players inactive or questionable tonight are left out,
        and so are stats whose lines like these have clearly lost. Under each pick: how its stat's lines shown at{" "}
        {pct(records?.at_least)} or more have done. Check that nobody's been ruled out before you enter it, and save it in
        My entries once it's played.</p>
    </div>
  );
}

function LineupPicks({ picks, records }: { picks: LineResult[]; records: Records }) {
  return (
    <ol className="lineup-picks">
      {picks.map((x) => (
        <li key={`${x.player}|${x.stat}|${x.line}`}>
          <span className="lp-who"><b>{x.player}</b>{" "}
            <span className="muted small">{x.team} {x.home ? "vs" : "@"} {x.opp} · {x.tip_local}</span>
            {records && <RecordNote stat={x.stat} r={records.stats[x.stat]} atLeast={records.at_least} />}
          </span>
          <span className="lp-stat">{x.stat}</span>
          <span className={`bpick ${x.side}`}>{sideWord(x)}</span>
          <b className="lp-line">{x.line}</b>
          <b className="lp-chance" title="Chance this pick hits (as on the list below)">{pct(x.p_best)}</b>
        </li>
      ))}
    </ol>
  );
}

/** "Points so far: 60.6% right of 71", coloured by what the record says (hover for its likely range). */
function RecordNote({ stat, r, atLeast }: { stat: string; r?: LineRecord; atLeast: number }) {
  if (!r) return <span className="lp-record muted small">{stat}: no graded lines like this yet</span>;
  const look = r.verdict === "winning" ? "pos" : r.verdict === "losing" ? "bad-text" : "muted";
  return (
    <span className={`lp-record small ${look}`} {...tipProps(recordTip(stat, r, atLeast))}>
      {stat} so far: {pct(r.rate)} right of {r.lines}{r.verdict === "few" ? " (too few to tell)" : ""}
    </span>
  );
}
