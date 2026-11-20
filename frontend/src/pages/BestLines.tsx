// Tab 1 · Best lines: paste a PrizePicks board, get the best picks for the entry you plan to play.
// On top, the lineup to play, in three options (BestLineup). Standard lines are ranked by the model's chance of hitting;
// More-only lines (Goblins and Demons) get their own list, because they pay differently. Lines whose
// game has started are followed live.
import { useEffect, useRef, useState } from "react";
import { api, messageOf, post } from "../api";
import { LessTestedBadge, LineTypeBadge, RoleBadge, StatusBadge } from "../components/Badges";
import BestLineups, { LosingBadge } from "../components/BestLineup";
import { Injuries, ReasonList, RecentGames, TypicalRange } from "../components/LineDetails";
import { LiveBox, useLiveLines } from "../components/Live";
import Seg from "../components/Seg";
import ShowInSteps from "../components/ShowInSteps";
import { useApp } from "../context/AppContext";
import { slipKey, useSlip } from "../context/SlipContext";
import { money, pct, plural } from "../format";
import { useKept } from "../kept";
import { chanceTitle, TIPS, tipProps } from "../labels";
import { forgetBoardText, loadBoardText, saveBoardText } from "../storage";
import type { BoardResult, Entry, LineResult, LiveState, Side } from "../types";

const SHOW_FIRST = 10;

/** Lines you already played in an open entry for the board's day: slipKey -> [{ side, entry }]. */
type Entered = Map<string, { side: Side; entry: Entry }[]>;

export default function BestLines() {
  const { meta, gameDate, setGameDate, toast } = useApp();
  const [text, setText] = useKept("board.text", () => loadBoardText()?.text || "");   // a refresh keeps the pasted board
  const [target, setTarget] = useKept("board.target", () => {
    const saved = loadBoardText()?.target;
    return saved && saved in meta.targets ? saved : "flex6";
  });
  const [wellTestedOnly, setWellTestedOnly] = useKept("board.wellTestedOnly", true);
  const [ranked, setRanked] = useKept<{ board: BoardResult; at: number } | null>("board.result", null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);

  async function rank() {
    if (!text.trim()) return toast("Paste some PrizePicks lines first.");
    saveBoardText(text, target);
    setBusy(true);
    try {
      const board = await post<BoardResult>("/api/board", { date: gameDate, text: text.trim(), target });
      if (board.date && board.date !== gameDate) setGameDate(board.date);   // the board's weekday set the date
      setRanked({ board, at: Date.now() });
      setError("");
    } catch (e) {
      setRanked(null);
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  function clear() {
    setText("");
    setRanked(null);
    setError("");
    forgetBoardText();
    box.current?.focus();
  }

  return (
    <section>
      <div className="card">
        <div className="row between wrap">
          <h2>Paste the PrizePicks board</h2>
          <label className="inline">Game date <input type="date" value={gameDate} onChange={(e) => setGameDate(e.target.value)} /></label>
        </div>
        <p className="muted small">On the PrizePicks website press <b>Ctrl+A</b> then <b>Ctrl+C</b> and paste the whole page here,
          or type lines one per line (like <b>Stephen Curry 28.5 Points</b>). Every line goes through the models and the best ones come out on top.</p>
        <textarea ref={box} rows={9} spellCheck={false} value={text} onChange={(e) => setText(e.target.value)}
          placeholder={"Paste the whole PrizePicks page (Ctrl+A, Ctrl+C), or type:\nStephen Curry 28.5 Points\nJayson Tatum 8.5 Rebounds\nTyrese Maxey 6.5 Assists"} />
        <div className="row gap wrap controls">
          <label className="inline">Rank for{" "}
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              {Object.entries(meta.targets).map(([key, t]) => (
                <option key={key} value={key}>{t.label} (need {pct(t.break_even)} per pick)</option>
              ))}
            </select>
          </label>
          <label className="inline check">
            <input type="checkbox" checked={wellTestedOnly} onChange={(e) => setWellTestedOnly(e.target.checked)} /> Only well-tested stats
          </label>
          <button className="primary" disabled={busy} onClick={rank}>{busy ? "Running every line…" : "Find the best lines"}</button>
          <button className="ghost" title="Empty the box and clear the results" onClick={clear}>Clear</button>
          <span className="muted small">{busy ? "about 10-30 seconds for a full board" : ""}</span>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {ranked && <Board key={`${ranked.at}-${wellTestedOnly}`} board={ranked.board} wellTestedOnly={wellTestedOnly} />}
    </section>
  );
}

function Board({ board, wellTestedOnly }: { board: BoardResult; wellTestedOnly: boolean }) {
  const keep = (x: LineResult) => !wellTestedOnly || x.reliable;
  const ranked = board.ranked.filter(keep);
  const moreOnly = (board.more_only || []).filter(keep);
  const started = (board.live || []).filter(keep);
  const hidden = board.ranked.length - ranked.length;
  const beats = ranked.filter((x) => (x.edge ?? 0) > 0).length;
  const entered = useEnteredLines(board.date);

  return (
    <>
      {board.date_note && <div className="note">{board.date_note}</div>}
      {board.lineups?.length ? <BestLineups lineups={board.lineups} date={board.date} records={board.stat_records} /> : null}
      <div className="card">
        <div className="row between wrap">
          <h2>Top {SHOW_FIRST} for a {board.target}</h2>
          <span className="muted small">
            Read {board.parsed} lines · {beats} beat the {pct(board.break_even)} break-even{hidden ? ` · ${hidden} less-tested hidden` : ""}
          </span>
        </div>
        {ranked.length
          ? <ShowInSteps items={ranked} step={SHOW_FIRST}
              render={(x, i) => <BoardRow x={x} rank={i + 1} entered={entered} records={board.stat_records} />} />
          : <div className="empty">No lines could be ranked.</div>}
        <p className="muted small">Model % is its chance the pick hits. Only picks above the break-even help you long-term,
          and two picks from the same game tend to move together.</p>
      </div>
      {moreOnly.length > 0 && <MoreOnlyLines lines={moreOnly} entered={entered} />}
      {started.length > 0 && <GamesInProgress lines={started} />}
      {board.unread?.length > 0 && (
        <div className="card"><b>Couldn't use ({board.unread.length})</b>{" "}
          <span className="muted small">(unknown or ambiguous player, a stat or part of the game that isn't modeled, or another day's game)</span>
          <ul className="small">{board.unread.map((u, i) => <li key={i}>{u}</li>)}</ul></div>
      )}
      {board.other.length > 0 && (
        <details className="card"><summary>Not ranked ({board.other.length})</summary>
          <ul className="small">
            {board.other.map((x, i) => <li key={i}>{x.player} · {x.stat || ""} {x.line ?? ""}: {x.reason || x.error || "not ranked"}</li>)}
          </ul>
        </details>
      )}
    </>
  );
}

type MoreOnlyKind = "all" | "goblin" | "demon";

/** A More-only line's kind, counting a guess ("likely Goblin") as that kind. null when there's no guess. */
const kindOf = (x: LineResult) => (x.line_type === "more_only" ? x.line_hint : x.line_type) ?? null;

/** Goblins and Demons get their own list, with buttons to show just one kind. A line with no guess at
 *  its kind (badge "More only") shows only under All. */
function MoreOnlyLines({ lines, entered }: { lines: LineResult[]; entered: Entered }) {
  const [kind, setKind] = useKept<MoreOnlyKind>("board.moreOnlyKind", "all");
  const shown = kind === "all" ? lines : lines.filter((x) => kindOf(x) === kind);
  const guesses = "Includes the \"likely\" ones: a guess when his standard line wasn't on the pasted board";

  return (
    <div className="card">
      <div className="row between wrap"><h2>More-only lines (Goblins &amp; Demons)</h2>
        <span className="muted small">ranked by the model's chance of More</span></div>
      <p className="muted small">PrizePicks only offers More on these. <b>Goblins</b> are easier lines that pay less, <b>Demons</b> are
        harder lines that pay more, and PrizePicks shows the exact payout when you build the entry, so there's no fixed
        break-even. Type that payout on your slip. These picks are tracked separately on the Results tab.</p>
      <div className="row wrap gap">
        <Seg small label="Which More-only lines" value={kind} onChange={setKind} options={[
          { value: "all", label: "All" },
          { value: "demon", label: "Demons", title: guesses },
          { value: "goblin", label: "Goblins", title: guesses },
        ]} />
        <span className="muted small">{shown.length === lines.length ? plural(lines.length, "line") : `${shown.length} of ${lines.length} lines`}</span>
      </div>
      {shown.length
        ? <ShowInSteps key={kind} items={shown} step={SHOW_FIRST} render={(x, i) => <BoardRow x={x} rank={i + 1} entered={entered} />} />
        : <div className="empty">No {kind === "demon" ? "Demons" : "Goblins"} on this board.</div>}
    </div>
  );
}

/** Your open entries' lines for the board's day, read again whenever the tab is opened or a board
 *  is ranked (an entry may have been saved or deleted since). Only a label: the board works without it. */
function useEnteredLines(date: string): Entered {
  const [entered, setEntered] = useState<Entered>(new Map());
  useEffect(() => {
    let current = true;
    api<{ entries: Entry[] }>("/api/entries").then(({ entries }) => {
      const found: Entered = new Map();
      for (const entry of entries) {
        if (entry.status !== "open") continue;
        for (const p of entry.picks) {
          if (p.game_date !== date) continue;
          const key = slipKey(p.player, p.stat, p.line);
          found.set(key, [...(found.get(key) || []), { side: p.side, entry }]);
        }
      }
      if (current) setEntered(found);
    }).catch(() => {});
    return () => { current = false; };
  }, [date]);
  return entered;
}

/** One ranked line: who, the line, the model's pick and chance, and the + Add button. Clicking the row
 *  opens the same details a Check lines card shows (built the first time it's opened: a full board has
 *  hundreds of rows). `records`: each stat's record on lines like the lineup's, for the losing-record badge. */
function BoardRow({ x, rank, entered, records }: {
  x: LineResult; rank: number; entered: Entered; records?: BoardResult["stat_records"];
}) {
  const record = records?.stats[x.stat];
  const { pickFor, togglePick } = useSlip();
  const [open, setOpen] = useState(false);
  const pick = pickFor(x);
  const side = x.side!;
  const moreOnly = x.sides && x.sides !== "both";
  const edge = x.edge ?? 0;

  return (
    <details className="bline" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className={`brow${pick ? " added" : ""}`}>
        <div className="rank">{rank}</div>
        <div className="bwho"><b>{x.player}</b><span className="chev" aria-hidden="true" />
          <span className="muted small">{x.team} {x.home ? "vs" : "@"} {x.opp} · {x.tip_local}</span>
          <div className="small">{x.stat} <b>{x.line}</b> ·{" "}
            {x.yes_no ? `chance it happens ${pct(x.p_over)}`
              : <span className="hint" {...tipProps(TIPS.median)}>average {x.proj}, median {x.q50}</span>}{" "}
            <LineTypeBadge lineType={x.line_type} hint={x.line_hint} />{" "}
            {!x.reliable && <><LessTestedBadge lowMinutes={x.low_minutes} />{" "}</>}
            {x.self_status && <><StatusBadge status={x.self_status} />{" "}</>}
            {record?.verdict === "losing" && <><LosingBadge stat={x.stat} r={record} atLeast={records!.at_least} />{" "}</>}
            <RoleBadge r={x} />{" "}
            {!x.injury_report && <span className="badge w" {...tipProps(TIPS.injuriesGuessed)}>injuries guessed</span>}
          </div>
        </div>
        <div className={`bpick ${side}`}>{side === "more" ? "MORE" : "LESS"}</div>
        <div className="bprob" title={chanceTitle(x, "Model's chance of this side")}>
          <b>{pct(x.p_best)}</b>
          {moreOnly
            ? <div className="small muted">last 10: {x.history?.over10 ?? "?"} of {x.history?.n10 ?? "?"} over</div>
            : <div className={`small ${edge >= 0 ? "pos" : "neg"}`}>{edge >= 0 ? "+" : ""}{(edge * 100).toFixed(1)} vs break-even</div>}
        </div>
        <div className="badd">
          <button className={`ghost small${pick ? " on" : ""}`}
            title={pick ? "On your entry slip. Click to take it off." : "Put this pick on your entry slip"}
            onClick={(e) => {
              e.preventDefault();   // the button sits in the row that opens the details: adding shouldn't open them
              togglePick(x, side);
            }}>
            {pick ? `✓ Added ${pick.side.toUpperCase()}` : "+ Add"}
          </button>
          <InEntryTag uses={entered.get(slipKey(x.player, x.stat, x.line))} side={side} />
        </div>
      </summary>
      {open && (
        <div className="bdetail">
          {x.modeled && !x.yes_no && <div className="small muted">Typical range <TypicalRange r={x} /></div>}
          <Injuries r={x} />
          <RecentGames r={x} />
          {!!x.reasons?.length && <><div className="label">Why the model thinks this</div><ReasonList r={x} /></>}
        </div>
      )}
    </details>
  );
}

/** "In 1 entry · MORE" under a line's + Add button, amber when the model now favours the other side.
 *  Hovering lists the entries. */
function InEntryTag({ uses, side }: { uses?: { side: Side; entry: Entry }[]; side: Side }) {
  if (!uses?.length) return null;
  const sides = [...new Set(uses.map((u) => u.side.toUpperCase()))];
  const against = uses.some((u) => u.side !== side);
  const list = uses.map(({ side: s, entry: e }) =>
    `${e.picks.length}-pick ${e.kind === "power" ? "Power" : "Flex"}, ${money(e.stake)}: ${s.toUpperCase()}`);
  const tip = `Already in your open ${uses.length === 1 ? "entry" : "entries"}: ${list.join(" · ")}.`
    + (against ? ` The model now favours ${side.toUpperCase()}.` : "");
  return (
    <span className={`in-entry${against ? " against" : ""}`} {...tipProps(tip)}>
      In {plural(uses.length, "entry", "entries")} · {sides.join("/")}
    </span>
  );
}

// ------------------------------------------------------------- lines whose game has started
// Followed live: his stat so far, the clock, his pace, and the model's chance from here, every 15
// seconds while this tab is open.
function GamesInProgress({ lines }: { lines: LineResult[] }) {
  const now = useLiveLines(lines.map((r, i) => ({ id: String(i), r })));
  return (
    <div className="card">
      <div className="row between wrap"><h2>Games in progress</h2>
        <span className="muted small">{plural(lines.length, "line")} · live box scores every 15 seconds</span></div>
      <p className="muted small">These games have started. Each line is followed live, with the model's chance from here:
        its pre-game projection updated with his stats so far, his minutes and the time left.</p>
      <ShowInSteps items={lines} step={SHOW_FIRST} render={(x, i) => <StartedRow x={x} live={now[String(i)]} />} />
    </div>
  );
}

function StartedRow({ x, live }: { x: LineResult; live?: LiveState }) {
  return (
    <div className="started-line">
      <div><b>{x.player}</b> <span className="muted small">{x.team} {x.home ? "vs" : "@"} {x.opp}</span>{" "}
        <span className="small">· {x.stat} <b>{x.line}</b> <LineTypeBadge lineType={x.line_type} hint={x.line_hint} /></span></div>
      <LiveBox r={x} x={live} />
    </div>
  );
}
