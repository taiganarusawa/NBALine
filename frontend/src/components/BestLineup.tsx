// Best lines › Best lineup: the entry to play from a pasted board (nbaline/pickem/lineup.py), in three
// options: standard lines (a Flex), safer (a Power of Goblins) and high risk (a Power of Demons). "Put
// on my slip" loads it onto the entry slip, so it can be saved in My entries once it's played.
// Standard picks show how their stat's lines like these have done (calibration.stat_records); Goblins
// and Demons show how lines of their kind have done (calibration.line_type_record).
import { useState } from "react";
import { useApp } from "../context/AppContext";
import { useSlip } from "../context/SlipContext";
import { pct, plural } from "../format";
import { useKept } from "../kept";
import { tipProps } from "../labels";
import { loadLineupSize, saveLineupSize } from "../storage";
import type { BoardResult, LineRecord, LineResult, LineTypeRecord, Lineup, LineupOption } from "../types";
import { LineTypeBadge } from "./Badges";
import Seg, { type SegOption } from "./Seg";

type Records = BoardResult["stat_records"];

const OPTIONS: SegOption<LineupOption>[] = [
  { value: "standard", label: "Standard", title: "A 6- or 5-pick Flex of standard lines" },
  { value: "goblin", label: "Safer", title: "A 3-pick Power of Goblins: hits more often, pays less" },
  { value: "demon", label: "High risk", title: "A 3-pick Power of Demons: hits less often, pays more" },
];

const SIZES: SegOption<"6" | "5">[] = [
  { value: "6", label: "6 picks", title: "Higher average return, bigger swings: most of it comes from the 25x for 6 of 6" },
  { value: "5", label: "5 picks", title: "Steadier: profits more often and loses less in a bad stretch, for a smaller average return" },
];

const sideWord = (x: LineResult) => (x.side === "more" ? "MORE" : "LESS");
const kindName = (l: Lineup) => (l.kind === "power" ? "Power" : "Flex");
const entryName = (l: Lineup) => `${l.size}-pick ${kindName(l)}`;
const LINE_WORD: Record<LineupOption, string> = { standard: "standard line", goblin: "Goblin", demon: "Demon" };
const kindPlural = (l: Lineup) => `${LINE_WORD[l.option]}s`;

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

/** The Best lineup card: the three options, one shown at a time (the choice is kept), and for standard
 *  lines a 6- or 5-pick Flex (remembered in this browser). The switch shows only when they differ. */
export default function BestLineups({ lineups, records }: { lineups: Lineup[]; records: Records }) {
  const [choice, setChoice] = useKept<LineupOption>("board.lineup", "standard");
  const [size, setSize] = useState(loadLineupSize);
  const six = lineups.find((l) => l.key === "flex6"), five = lineups.find((l) => l.key === "flex5");
  const canSwitch = six?.size === 6 && five?.size === 5;
  const shown = (choice === "standard" ? (canSwitch && size === 5 ? five : six) : lineups.find((l) => l.option === choice))
    || lineups[0];
  const options = OPTIONS.filter((o) => lineups.some((l) => l.option === o.value));
  function pickSize(value: "6" | "5") {
    const n = value === "5" ? 5 : 6;
    setSize(n);
    saveLineupSize(n);
  }
  return (
    <div className="card lineup">
      <div className="row between wrap">
        <h2>Best lineup{shown.size ? ` · ${entryName(shown)}` : ""}{shown.priced ? "" : ` of ${kindPlural(shown)}`}</h2>
        <span className="muted small">
          {plural(shown.candidates, LINE_WORD[shown.option])}{" "}
          {shown.priced ? (shown.candidates === 1 ? "clears" : "clear") : (shown.candidates === 1 ? "has" : "have")} {pct(shown.at_least)}{" "}
          ({plural(shown.players, "player")})
        </span>
      </div>
      <div className="row gap wrap">
        {options.length > 1 && <Seg small label="Which lineup" value={shown.option} onChange={setChoice} options={options} />}
        {shown.option === "standard" && canSwitch && (
          <Seg small label="How many picks" value={String(size) as "6" | "5"} onChange={pickSize} options={SIZES} />
        )}
      </div>
      <LineupBody key={shown.key} l={shown} records={shown.option === "standard" ? records : undefined} />
    </div>
  );
}

function LineupBody({ l, records }: { l: Lineup; records: Records }) {
  const { meta } = useApp();
  const { loadLineup } = useSlip();
  const losing = Object.entries(l.losing || {});
  const leftOut = losing.length > 0 && (
    <p className="small warn-text">⚠ Left out for a losing record on lines like these:{" "}
      {losing.map(([stat, n]) => `${stat} (${plural(n, "line")} tonight)`).join(", ")}.</p>
  );
  const record = l.record !== undefined && <KindRecord l={l} />;

  if (!l.size) {
    return (
      <>
        <p className="small">Not enough for a {l.sizes.join("- or ")}-pick {kindName(l)} tonight.
          {l.picks.length > 0 && ` The ${l.picks.length === 1 ? "one that qualifies" : "ones that qualify"}:`}</p>
        {l.picks.length > 0 && <LineupPicks picks={l.picks} records={records} />}
        {leftOut}
        {record}
      </>
    );
  }

  const table = meta.payouts[l.kind]?.[String(l.size)] || {};
  const standardPay = table[String(l.size)];

  return (
    <>
      <LineupPicks picks={l.picks} records={records} />
      <div className="row between wrap gap lineup-sum">
        {l.priced ? (
          <span className="small">
            Average <b>{pct(l.avg_chance)}</b> per pick · returns <b>${l.ev!.toFixed(2)}</b> per $1 at the standard
            payouts ({Object.entries(table).sort(([a], [b]) => Number(b) - Number(a)).map(([, m]) => `${m}x`).join(" / ")})
            · chance of a profit {pct(l.p_profit)} · all {l.size} hit {pct(l.p_all)}
          </span>
        ) : (
          <span className="small">
            Average <b>{pct(l.avg_chance)}</b> per pick · all {l.size} hit <b>{pct(l.p_all)}</b> · worth playing if PrizePicks
            pays at least <b>{(Math.ceil(l.min_payout! * 100) / 100).toFixed(2)}x</b>
            {standardPay != null && <span className="muted"> (standard {standardPay}x)</span>}
          </span>
        )}
        <button className="primary" title="Replace your entry slip with this lineup" onClick={() => loadLineup(l.picks, l.kind)}>
          Put on my slip
        </button>
      </div>
      {leftOut}
      {record}
    </>
  );
}

/** Added after the record when it says something: the model's chances look off, or it's too early. */
const KIND_VERDICT: Record<LineTypeRecord["verdict"], string> = {
  fair: "",
  cautious: "",
  too_sure: " · hitting less than the model says, so the payout needed is likely higher",
  few: " · too few to tell yet",
};

/** "Goblins at 75.0%+ so far: 182 of 222 hit (82.0%, model said 78.7%)": how lines of this kind have done. */
function KindRecord({ l }: { l: Lineup }) {
  const r = l.record;
  const what = `${kindPlural(l)} at ${pct(l.at_least)}+`;
  if (!r) return <p className="small muted">{what}: none graded yet</p>;
  return (
    <p className={`small ${r.verdict === "too_sure" ? "warn-text" : "muted"}`}
      {...tipProps(`Graded ${kindPlural(l)} from your pasted boards, each player/stat once a night. Likely range `
        + `${pct(r.low)} to ${pct(r.high)}; the model said ${pct(r.said)} on average.`)}>
      {r.verdict === "too_sure" ? "⚠ " : ""}{what} so far: {r.right} of {r.lines} hit ({pct(r.rate)}, model said {pct(r.said)})
      {KIND_VERDICT[r.verdict]}
    </p>
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
          <span className="lp-stat">{x.stat}{x.line_type && <> <LineTypeBadge lineType={x.line_type} hint={x.line_hint} /></>}</span>
          <span className={`bpick ${x.side}`}>{sideWord(x)}</span>
          <b className="lp-line">{x.line}</b>
          <b className="lp-chance" title="Chance this pick hits (as on the lists below)">{pct(x.p_best)}</b>
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
