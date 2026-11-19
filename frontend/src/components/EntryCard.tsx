// One saved entry with its picks: open ones (My entries) follow their games live and show how each
// pick's chance moved since you saved it; graded ones (Results) show each pick's real number and result,
// and what the entry paid, which you can change when PrizePicks paid something else.
import { useRef, useState, type FormEvent } from "react";
import { messageOf } from "../api";
import { money, pct } from "../format";
import { TIPS, tipProps } from "../labels";
import { loadSectionOpen, saveSectionOpen } from "../storage";
import type { Entry, EntriesLive, EntryLive, EntryPayouts, LiveState, OutcomeTier, Pick } from "../types";
import { LineTypeBadge } from "./Badges";
import { clockText, CourtTag, GameLine, PacePill, ProgressBar } from "./Live";
import { boostPercent, PayoutsEditor } from "./Payouts";

/** Chances re-checked with the latest data, model and injury report (/api/entries/now). */
export interface ChancesNow {
  picks: Record<string, number | null>;
  entries: Record<string, number | null>;
}

interface Props {
  e: Entry;
  live?: EntriesLive | null;
  now?: ChancesNow | null;
  onDelete?: () => void;
  /** Open entries: mark it as a protected play, or not. */
  onProtect?: (isProtected: boolean) => void;
  /** Open entries: save its payouts and profit boost (what PrizePicks shows). */
  onPayouts?: (payouts: EntryPayouts) => Promise<void>;
  /** Graded entries: save what PrizePicks really paid (null: back to the app's own amount). */
  onPaid?: (amount: number | null) => Promise<void>;
}

const RESULT_TEXT: Record<string, string> = { hit: "✓ hit", miss: "✗ miss", void: "void (DNP)", push: "push" };
const MOVED = 0.005;   // smaller changes than half a point count as "unchanged"

export default function EntryCard({ e, live, now, onDelete, onProtect, onPayouts, onPaid }: Props) {
  const [editingPayouts, setEditingPayouts] = useState(false);
  const open = e.status === "open";
  const summary = open ? live?.entries[e.id] : undefined;
  const paid = !!summary && summary.done && summary.locked > 0;   // decided and paying: a green card
  const evNow = open ? now?.entries[e.id] : null;
  const isProtected = !!e.protected;
  return (
    <div className={`entry${paid ? " paid" : ""}`}>
      <div className="eh">
        <span>
          {e.game_date} · {e.picks.length}-pick {e.kind === "power" ? "Power Play" : "Flex Play"} · {money(e.stake)}
          {isProtected && <> <span className="badge protected" {...tipProps(TIPS.protectedPlay)}>Protected</span></>}
          {!!e.payouts?.boost && <> <span className="badge boost" {...tipProps(TIPS.boost)}>+{boostPercent(e.payouts.boost)}% boost</span></>}
          {e.ev != null && <> · model expected {e.ev.toFixed(2)}x{evNow != null && <> → <Moved saved={e.ev} now={evNow} text={`${evNow.toFixed(2)}x`} /></>}</>}
        </span>
        {open ? <span className="muted">{summary ? <EntryLiveSummary s={summary} next={nextTip(e, live)} /> : "open"}</span>
          : <WhatItPaid e={e} onPaid={onPaid} />}
      </div>
      {open
        ? <div className="picks">{e.picks.map((p) => <OpenPick key={p.id} p={p} x={live?.picks[p.id]} now={now?.picks[p.id]} />)}</div>
        : <div className="gpicks">{e.picks.map((p) => <GradedPick key={p.id} p={p} />)}</div>}
      {summary && !summary.done && <EntryChances s={summary} stake={e.stake} />}
      {!open && <WhyItWent e={e} />}
      {editingPayouts && onPayouts && (
        <PayoutsEditor e={e} removed={summary?.other ?? 0} onSave={onPayouts} onClose={() => setEditingPayouts(false)} />
      )}
      {(onDelete || onProtect || onPayouts) && (
        <div className="row gap entry-actions">
          {onPayouts && (
            <button className="ghost small" aria-expanded={editingPayouts} onClick={() => setEditingPayouts(!editingPayouts)}
              title="Change what this entry pays, or add a profit boost, to match PrizePicks">Payouts</button>
          )}
          {onProtect && (
            <label className="inline check small" {...tipProps(TIPS.protectedPlay)}>
              <input type="checkbox" checked={isProtected} onChange={(ev) => onProtect(ev.target.checked)} /> Protected play
            </label>
          )}
          {onDelete && <button className="ghost small" onClick={onDelete}>Delete</button>}
        </div>
      )}
    </div>
  );
}

/** A graded entry's result and what it paid ("WON · paid $25.00"). With onPaid (the Results tab) the
 *  amount can be changed to what PrizePicks really paid, since its payouts change; your profit follows it. */
function WhatItPaid({ e, onPaid }: { e: Entry; onPaid?: Props["onPaid"] }) {
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const typedIn = e.paid_set != null;
  const notCounted = !!e.protected && !e.payout;   // a protected play that lost outright

  async function save(value: number | null) {
    setSaving(true);
    try {
      await onPaid!(value);
      setEditing(false);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSaving(false);
    }
  }

  function submit(ev: FormEvent) {
    ev.preventDefault();
    const value = parseFloat(amount);
    if (isNaN(value) || value < 0) return setError("Type the amount PrizePicks paid (0 if it paid nothing).");
    save(Math.round(value * 100) / 100);
  }

  if (editing) {
    return (
      <form className="paid-edit row gap wrap" onSubmit={submit}>
        <label className="inline">PrizePicks paid $
          <input type="number" inputMode="decimal" min="0" step="0.01" aria-label="Amount PrizePicks paid" autoFocus
            value={amount} onChange={(ev) => { setAmount(ev.target.value); setError(""); }} />
        </label>
        <button className="primary small" disabled={saving}>Save</button>
        {typedIn && e.calculated != null && (
          <button type="button" className="ghost small" disabled={saving} onClick={() => save(null)}>
            Use the app's {money(e.calculated)}
          </button>
        )}
        <button type="button" className="ghost small" disabled={saving} onClick={() => { setEditing(false); setError(""); }}>Cancel</button>
        {error && <span className="error-text small">{error}</span>}
      </form>
    );
  }
  return (
    <span className="row gap wrap paid-view">
      {notCounted ? <span className="muted" title="Protected: not counted in your profit or ROI">LOST · protected, not counted</span>
        : <span className={`status-${e.status}`}>{e.status.toUpperCase()} · paid {money(e.payout ?? 0)}</span>}
      {typedIn && e.calculated != null && (
        <span className="muted small typed-in" title="You typed in what PrizePicks paid; the app's payout table gave a different amount">
          your amount · the app had {money(e.calculated)}
        </span>
      )}
      {onPaid && (
        <button className="ghost small edit-paid" title="PrizePicks paid a different amount? Type in what it paid"
          onClick={() => { setAmount(String(e.payout ?? 0)); setEditing(true); }}>Edit</button>
      )}
    </span>
  );
}

/** When the entry's next game that hasn't started tips off ("4:00 PM"), if the schedule says. */
function nextTip(e: Entry, live?: EntriesLive | null) {
  const waiting = e.picks.map((p) => live?.picks[p.id]).filter((x) => x?.state === "pending" && x.tip_utc);
  return waiting.sort((a, b) => a!.tip_utc!.localeCompare(b!.tip_utc!))[0]?.tip;
}

/** "3 ✓ · 1 ✗ · 2 in play · $0.40 locked in, up to $2.00", or before any game: "open · first game 4:00 PM" */
function EntryLiveSummary({ s, next }: { s: EntryLive; next?: string }) {
  if (!s.hit && !s.lost && !s.live && !s.other) {
    return <span className="muted">open · {next ? `first game ${next}` : "not started"}</span>;
  }
  const parts = [
    s.hit > 0 && <span className="r-hit">{s.hit} ✓</span>, s.lost > 0 && <span className="r-miss">{s.lost} ✗</span>,
    s.live > 0 && `${s.live} in play`, s.pending > 0 && `${s.pending} not started${next ? ` (next ${next})` : ""}`,
    s.other > 0 && `${s.other} push/void`,
  ].filter(Boolean);
  // money that's already guaranteed, whatever the picks still in play do, in green
  const locked = (amount: number) => amount > 0
    ? <b className="locked" title="Guaranteed, whatever the picks still in play do">{money(amount)}</b> : money(amount);
  const pay = s.done ? <>pays {locked(s.locked)} · grade it with Update results</>
    : s.best === s.locked ? <>pays {locked(s.best)}</> : <>{locked(s.locked)} locked in, up to {money(s.best)}</>;
  return <>{parts.map((part, i) => <span key={i}>{part} · </span>)}{pay}</>;
}

/** An open entry's chances now, like the slip's view before you saved it, kept up to date: chance of a
 *  profit, of any payout, the average payout, and every amount it can still pay with its chance. Each
 *  pick counts with its chance now (live during its game), and picks already decided as they ended, so
 *  after a miss "6 of 6" is crossed out and the rest show what's still in reach. A pick on a
 *  whole-number line can also push and revert, which pays the lineup on fewer picks ("4 of 4 · +1 push"). */
function EntryChances({ s, stake }: { s: EntryLive; stake: number }) {
  // a dropdown: closed, its title row still gives the chance of a profit and the average payout.
  // It slides open (styles.css .chances-body) and scrolls the page just enough to show all of it.
  const [open, setOpen] = useState(() => loadSectionOpen("entryChances"));
  const box = useRef<HTMLDivElement>(null);
  const odds = s.odds;
  if (odds === undefined) return null;   // a server from before this existed (restart NBALine)
  const live = s.live > 0;

  function toggle() {
    setOpen(!open);
    saveSectionOpen("entryChances", !open);   // remembered in this browser for every entry
    if (!open) revealWhole(box.current);
  }

  return (
    <div className={`chances${open ? " open" : ""}`} ref={box}>
      <button className="chances-head" aria-expanded={open} onClick={toggle}>
        <b>Chances now</b>
        {odds && <span className="chances-brief" aria-hidden={open}><b className={odds.p_profit >= 0.5 ? "up" : ""}>{pct(odds.p_profit)}</b> chance of
          profit · average <b>{money(odds.expected)}</b></span>}
        <span className="muted small chances-when">{live ? <><span className="live-dot" />live</>
          : s.hit || s.lost || s.other ? "picks still to play" : "before tip-off"}</span>
      </button>
      <div className="chances-body" inert={!open}><div className="chances-clip"><div className="chances-content">
      {!odds ? <div className="muted small">Needs the model's chance for every pick still to play.</div> : <>
        <div className="chances-stats">
          <div><span className="k">Chance of profit</span><b className={odds.p_profit >= 0.5 ? "up" : ""}>{pct(odds.p_profit)}</b></div>
          <div><span className="k">Pays anything</span><b>{pct(odds.p_cash)}</b></div>
          <div><span className="k">Average payout</span><b>{money(odds.expected)}</b>
            <span className="muted small"> on {money(stake)}</span></div>
        </div>
        <div className="tiers">
          {odds.tiers.map((t) => {
            const out = t.hits != null && t.chance === 0;   // a miss has already ruled it out
            const look = t.pays > stake ? "profit" : t.pays > 0 ? "back" : "none";
            return (
              <div key={`${t.hits}-${t.of}-${t.refund ?? ""}`} className={`tier ${look}${out ? " out" : ""}`}>
                <span className="t-hits">{t.refund ? <span title="Too few picks left to pay on: you get your money back">Refunded</span>
                  : t.hits == null ? fewer(odds.tiers) : <>{t.hits} of {t.of}{!!t.pushes && <PushNote n={t.pushes} />}</>}</span>
                <span className="t-pays">{t.pays > 0 ? money(t.pays) : "$0"}</span>
                <span className="t-bar"><span style={{ width: `${Math.max(t.chance * 100, t.chance > 0 ? 1 : 0)}%` }} /></span>
                <span className="t-chance">{out ? "out" : pct(t.chance)}</span>
              </div>
            );
          })}
        </div>
      </>}
      </div></div></div>
    </div>
  );
}

const OPEN_MS = 300;   // how long it takes to slide open (styles.css .chances-body)

/** Keep the whole box on screen while it slides open: every frame, the page scrolls down by however
 *  far its bottom has grown past the screen (never so far that its top goes off it). So the page moves
 *  with the box, just as smoothly, and doesn't move at all if the box fits. */
function revealWhole(box: HTMLElement | null) {
  if (!box) return;
  const until = performance.now() + OPEN_MS + 100, margin = 16;
  const follow = () => {
    const r = box.getBoundingClientRect();
    const down = Math.min(r.bottom + margin - window.innerHeight, r.top - margin);
    if (down > 0.5) window.scrollBy({ top: down, behavior: "instant" });
    if (performance.now() < until) requestAnimationFrame(follow);
  };
  requestAnimationFrame(follow);
}

/** The "pays nothing" row's name: every number of hits under the lowest that pays with no more pushes
 *  ("3 or fewer"). */
function fewer(tiers: OutcomeTier[]) {
  const nothing = tiers[tiers.length - 1];
  const lowest = Math.min(...tiers.filter((t) => t.hits != null && !t.pushes).map((t) => t.hits!));
  return !isFinite(lowest) ? "Any miss" : lowest === 1 ? `0 of ${nothing.of}` : `${lowest - 1} or fewer`;
}

/** Under a tier only pushes lead to: how many more picks have to land exactly on the line. */
const PushNote = ({ n }: { n: number }) => (
  <span className="t-push" title={`If ${n} more pick${n > 1 ? "s land" : " lands"} exactly on the line: a push, so ` +
    `${n > 1 ? "they revert" : "it reverts"} and the lineup is paid on fewer picks`}>+{n} push{n > 1 ? "es" : ""}</span>
);

/** A changed number: green when it went up since you saved the entry, red when down. */
function Moved({ saved, now, text, threshold = MOVED }: { saved: number; now: number; text: string; threshold?: number }) {
  const direction = now - saved > threshold ? "up" : saved - now > threshold ? "down" : "same";
  const hint = direction === "same" ? "About the same as when you saved it" : `${direction === "up" ? "Up" : "Down"} since you saved it`;
  return <b className={`chg ${direction}`} title={hint}>{text}</b>;
}

// drawn arrows for the line box (a text ↑ / ↓ is only as thick as the font makes it)
const ArrowUp = () => <svg className="arrow" viewBox="0 0 16 16" role="img" aria-label="More"><path d="M8 13.5V3M3.5 7.5 8 3l4.5 4.5" /></svg>;
const ArrowDown = () => <svg className="arrow" viewBox="0 0 16 16" role="img" aria-label="Less"><path d="M8 2.5V13M3.5 8.5 8 13l4.5-4.5" /></svg>;

// Shorter names for the longest stats, so every line box fits its stat on one line and all the boxes
// are the same size (the full name shows on hover).
const BOX_NAMES: Record<string, string> = {
  "Free Throws Made": "FT Made", "Free Throws Attempted": "FT Attempted",
  "Two Pointers Made": "2-PT Made", "Two Pointers Attempted": "2-PT Attempted",
  "Offensive Rebounds": "Off. Rebounds", "Defensive Rebounds": "Def. Rebounds",
};

/** An open pick, laid out like the PrizePicks app: the player and how it's going on the left, the line
 *  on the right (↑ More, ↓ Less), the progress bar below. `x` is its live state, `now` its chance now. */
function OpenPick({ p, x, now: rechecked }: { p: Pick; x?: LiveState; now?: number | null }) {
  const more = p.side === "more";
  const clock = x?.state === "live" ? clockText(x) : "";
  // its chance now: live during the game (ingame.py), before it the latest re-check
  const liveChance = x?.state === "live" && x.live_more != null ? (more ? x.live_more : 1 - x.live_more) : null;
  const now = liveChance ?? rechecked;
  const push = x?.state === "live" ? x.live_push ?? 0 : 0;   // on a whole-number line he can still land on it
  return (
    <div className={`pick${x?.on_court ? " oncourt" : ""}`}>
      <div className="who">
        <span className="live-dot" hidden={!x?.game_live} title="Game in progress" /><b>{p.player}</b>{" "}
        {p.jersey && <><span className="jersey" title="Jersey number">#{p.jersey}</span>{" "}</>}
        <span className="muted small game"><GameLine team={p.team} opp={p.opp} x={x} /></span>{" "}
        <CourtTag x={x} />
      </div>
      <div className="how">
        <LineTypeBadge lineType={p.line_type} />
        <span className="muted" title={`Model's chance this pick hits: when saved → now${liveChance != null ? " (live, from his game so far)" : ""}`}>
          {p.model_p == null ? "—" : now == null ? pct(p.model_p) : <>{pct(p.model_p)} → <Moved saved={p.model_p} now={now} text={pct(now)} /></>}
        </span>
        {push >= 0.005 && (
          <span className="muted small" title={`Chance he finishes exactly on ${p.line}: a push, so the pick reverts ` +
            "and the entry is paid on one pick fewer. The chance before it leaves pushes out."}>push {pct(push)}</span>
        )}
        {x && <span className={`r-${x.state}`}>{x.text}{clock && <span className="muted"> · {clock}</span>}</span>}
        <PacePill x={x} side={p.side} />
      </div>
      <div className={`line-box ${p.side}`} title={`${more ? "More" : "Less"} than ${p.line} ${p.stat}`}>
        {more ? <ArrowUp /> : <ArrowDown />}<b>{p.line}</b>
        <span className="stat-name">{BOX_NAMES[p.stat] || p.stat}</span>
      </div>
      <ProgressBar x={x} line={p.line} />
    </div>
  );
}

const WHY_TITLE: Record<string, string> = { won: "Why it won", lost: "Why it lost", partial: "Why it paid part", refund: "Why it was refunded" };
const DECIDED_IT = { miss: 0, push: 1, void: 1, hit: 2 };   // misses first: they're what decided the entry
/** A pick's two groups of reasons: what pushed his number the way it went, and what pushed it the other way. */
const WHY_GROUPS: Record<string, [string, string]> = {
  hit: ["Why it hit", "Worked against it"],
  miss: ["Why it missed", "Helped, but not enough"],
};

/** A graded entry's dropdown: why each pick hit or missed, from the box scores (nbaline/pickem/explain.py). */
function WhyItWent({ e }: { e: Entry }) {
  if (!e.why) return null;   // a server started before explanations existed (restart NBALine)
  const picks = [...e.picks].sort((a, b) => DECIDED_IT[a.result ?? "hit"] - DECIDED_IT[b.result ?? "hit"]);
  // the amount you typed in can make it won/partial/lost differently than its picks did: then a neutral title
  const kindOf = (pay: number) => (pay > e.stake ? "won" : pay > 0 ? "partial" : "lost");
  const outcomeChanged = e.paid_set != null && e.calculated != null && kindOf(e.calculated) !== kindOf(e.payout ?? 0);
  return (
    <details className="why">
      <summary>{outcomeChanged ? "How the picks went" : WHY_TITLE[e.status] ?? "Why"} <span className="muted">· {e.why}</span></summary>
      {!!e.together?.length && (
        <div className="together">
          {e.together.map((note) => <div key={note}>{note}</div>)}
          <div className="muted small">The entry's odds treated every pick as independent. Picks on one player or
            in one game tend to win or lose together.</div>
        </div>
      )}
      <ul className="why-list">
        {picks.map((p) => (
          <li key={p.id}>
            <span className={`r-${p.result || ""}`}>{p.result ? RESULT_TEXT[p.result] : ""}</span>{" "}
            <b>{p.player}</b> {p.side === "more" ? "MORE" : "LESS"} {p.line} {p.stat}: <b>{p.actual ?? "—"}</b>
            <PickWhyText p={p} />
          </li>
        ))}
      </ul>
    </details>
  );
}

/** A graded pick's reasons: why it hit or missed, what pushed the other way, then how close it was. */
function PickWhyText({ p }: { p: Pick }) {
  const why = p.why;
  if (!why?.because) return null;   // none, or a server started before reasons were sorted (restart NBALine)
  const [because, despite] = WHY_GROUPS[p.result ?? ""] ?? ["", ""];
  return (
    <div className="why-text">
      {!!why.because.length && <div><b>{because}:</b> {why.because.join(" ")}</div>}
      {!!why.despite.length && <div><b>{despite}:</b> {why.despite.join(" ")}</div>}
      {why.context && <div>{why.context}</div>}
    </div>
  );
}

/** A graded pick in the Results tab: the line, the model's chance, the real number and the result.
 *  Every entry uses the same columns (styles.css .gpick), so the whole list lines up. */
function GradedPick({ p }: { p: Pick }) {
  return (
    <div className="gpick">
      <div className="g-who">{p.player} <span className="muted small">{p.team}</span></div>
      <div className="g-line">{p.stat} {p.side === "more" ? "MORE" : "LESS"} {p.line} <LineTypeBadge lineType={p.line_type} /></div>
      <div className="g-model muted" title="Model's chance this pick hits, when you saved it">{pct(p.model_p)}</div>
      <div className="g-actual" title="His real number">{p.actual ?? ""}</div>
      <div className={`g-result r-${p.result || ""}`}>{p.result ? RESULT_TEXT[p.result] : ""}</div>
    </div>
  );
}
