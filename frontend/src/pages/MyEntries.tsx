// Tab 3 · My entries: edit the slip, set Power/Flex, the payouts and any profit boost, see the entry's
// odds, and save what you actually played so it gets graded after the games. Open entries follow their
// games live, and their payouts can be fixed to what PrizePicks shows (e.g. once a pick reverts).
import { useCallback, useEffect, useRef, useState } from "react";
import { api, messageOf, post } from "../api";
import { LineTypeBadge } from "../components/Badges";
import EntryCard, { type ChancesNow } from "../components/EntryCard";
import { BoostInput, boostRate, PayoutBoxes, RevertedRows } from "../components/Payouts";
import PullToRefresh from "../components/PullToRefresh";
import Seg from "../components/Seg";
import { useApp } from "../context/AppContext";
import { useSlip } from "../context/SlipContext";
import { pct } from "../format";
import { useKept } from "../kept";
import { TIPS, tipProps } from "../labels";
import { GIVE_UP_AFTER, keepChecking, LIVE_EVERY } from "../poll";
import { loadEntriesView, saveEntriesView, type SlipPick } from "../storage";
import type { EntriesLive, Entry, EntryOdds, EntryPayouts, Side } from "../types";

const WAITING_EVERY = 120_000;  // nothing on yet, but a game is still to start (LIVE_EVERY while one is on)

const SIDES = (moreOnly: boolean) => [
  { value: "more" as Side, label: "More" },
  { value: "less" as Side, label: "Less", disabled: moreOnly, title: moreOnly ? "PrizePicks only offers More on this line" : undefined },
];

export default function MyEntries() {
  const [saved, setSaved] = useState(0);   // goes up when an entry is saved, so the open entries reload
  return (
    <section>
      <SlipEditor onSaved={() => setSaved((n) => n + 1)} />
      <OpenEntries reload={saved} />
    </section>
  );
}

// ------------------------------------------------------------- the slip editor
function SlipEditor({ onSaved }: { onSaved: () => void }) {
  const { meta, gameDate, toast } = useApp();
  const { slip, kind, setKind, payouts, setPayout, reverted, setSide, removePick, clearSlip } = useSlip();
  const [stake, setStake] = useKept("entries.stake", "");
  const [isProtected, setProtected] = useKept("entries.protected", false);   // a PrizePicks protected play
  const [boost, setBoost] = useKept("entries.boost", "");   // a Profit Boost promo, in %
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const table = payouts[kind]?.[String(slip.length)];   // this entry type and size's payouts (editable)

  async function save() {
    setMessage("Saving (checks each pick with the model)…");
    setSaving(true);
    try {
      // reverted: what it pays if players revert; boost: a profit boost on top of every payout
      const sent: EntryPayouts = { ...structuredClone(meta.payouts), reverted, boost: boostRate(boost) };
      if (table) sent[kind][String(slip.length)] = table;   // your edited numbers for this size
      await post("/api/entries", {
        date: gameDate, kind, stake: parseFloat(stake), payouts: sent, protected: isProtected,
        picks: slip.map((p) => ({ player: p.player, stat: p.stat, line: p.line, side: p.side, line_type: p.line_type || null })),
      });
      clearSlip();
      setProtected(false);   // the next entry starts unprotected, with no boost
      setBoost("");
      setMessage("");
      toast("Entry saved. It will be graded after the games.");
      onSaved();
    } catch (e) {
      setMessage(messageOf(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <h2>Entry slip <span className="muted small">— record what you actually played on PrizePicks</span></h2>
      {slip.length ? (
        <>
          {slip.map((p, i) => <SlipRow key={`${p.player}|${p.stat}|${p.line}`} p={p}
            onSide={(side) => setSide(i, side)} onRemove={() => removePick(i)} />)}
          {slip.some((p) => p.line_type) && (
            <div className="note" style={{ marginTop: 10 }}>This entry has Goblin/Demon picks, so PrizePicks pays a different amount
              than the usual table. Type the payout PrizePicks shows into the boxes below, so your profit is tracked correctly.</div>
          )}
        </>
      ) : (
        <div className="empty">No picks yet. Use <b>+ Add</b> on Best lines, <b>+ More</b> / <b>+ Less</b> on
          Check lines, or add one by hand below.</div>
      )}
      <ManualPick />
      <div className="entry-form">
        <div className="row gap wrap">
          <div>
            <div className="label">Entry type</div>
            <Seg value={kind} onChange={setKind} options={[{ value: "power", label: "Power Play" }, { value: "flex", label: "Flex Play" }]} />
          </div>
          <label>Amount played ($)<input type="number" min="0" step="1" placeholder="10" value={stake} onChange={(e) => setStake(e.target.value)} /></label>
          <BoostInput value={boost} onChange={setBoost} />
          <label className="inline check protect" {...tipProps(TIPS.protectedPlay)}>
            <input type="checkbox" checked={isProtected} onChange={(e) => setProtected(e.target.checked)} /> Protected play
          </label>
        </div>
        <div className="label">Payouts <span className="muted small">— copy the multipliers your PrizePicks app shows
          for this entry, before any boost</span></div>
        {table ? <PayoutBoxes key={`${kind}-${slip.length}`} table={table} of={slip.length} boost={boostRate(boost)} onChange={setPayout} />
          : <span className="muted small">{kind === "flex" ? "Flex needs 3-6 picks." : "Power needs 2-6 picks."}</span>}
        {table && <RevertedPayouts picks={slip.length} boost={boostRate(boost)} />}
        <EntryOddsBox hasTable={!!table} boost={boostRate(boost)} />
        <div className="row gap">
          <button className="primary" disabled={saving} onClick={save}>Save entry (I played this)</button>
          <button className="ghost" onClick={() => { if (confirm("Remove all picks from the slip?")) clearSlip(); }}>Clear slip</button>
          <span className="muted">{message}</span>
        </div>
      </div>
    </div>
  );
}

/** What the lineup pays if players revert (didn't play, or finished exactly on the line), one row per
 *  number of picks left, like PrizePicks' "What is a reverted payout?" table. Editable, since Goblins and
 *  Demons change it: copy what your PrizePicks app shows for the lineup. */
function RevertedPayouts({ picks, boost }: { picks: number; boost: number }) {
  const { kind, reverted, setReverted } = useSlip();
  return (
    <details className="manual reverted">
      <summary>If players revert <span className="muted">(didn't play, or exactly on the line)</span></summary>
      <RevertedRows kind={kind} picks={picks} reverted={reverted} boost={boost} onChange={setReverted} />
    </details>
  );
}

function SlipRow({ p, onSide, onRemove }: { p: SlipPick; onSide: (side: Side) => void; onRemove: () => void }) {
  const chance = p.model_p != null ? pct(p.model_p) : p.manual ? "checked on save" : "no model";
  return (
    <div className="slip-pick">
      <div className="who">{p.player} <span>{p.team ? `${p.team} · ` : ""}{p.stat} {p.line}</span>{" "}
        <LineTypeBadge lineType={p.line_type} hint={p.line_hint} /></div>
      <Seg value={p.side} onChange={onSide} options={SIDES(!!p.line_type)} />
      <div className="mp" title="Model's chance this pick hits">{chance}</div>
      <button className="ghost" aria-label="Remove pick" onClick={onRemove}>✕</button>
    </div>
  );
}

/** Add a pick typed by hand (it's checked with the model when the entry is saved). */
function ManualPick() {
  const { meta, toast } = useApp();
  const { addManualPick } = useSlip();
  const [player, setPlayer] = useState("");
  const [stat, setStat] = useState(meta.stats[0]);
  const [line, setLine] = useState("");
  const [side, setSide] = useState<Side>("more");

  function add() {
    const value = parseFloat(line);
    if (!player.trim() || isNaN(value)) return toast("Type a player and a line.");
    addManualPick(player.trim(), stat, value, side);
    setPlayer("");
    setLine("");
  }

  return (
    <details className="manual">
      <summary>Add a pick by hand</summary>
      <div className="row gap wrap">
        <input list="playerList" placeholder="Player" autoComplete="off" value={player} onChange={(e) => setPlayer(e.target.value)} />
        <select value={stat} onChange={(e) => setStat(e.target.value)}>{meta.stats.map((s) => <option key={s}>{s}</option>)}</select>
        <input type="number" step="0.5" placeholder="Line" value={line} onChange={(e) => setLine(e.target.value)} />
        <Seg value={side} onChange={setSide} options={SIDES(false)} />
        <button className="ghost" onClick={add}>Add pick</button>
      </div>
    </details>
  );
}

/** The model's view of the whole entry, with the profit boost: chance all hit, chance of a profit,
 *  expected return. */
function EntryOddsBox({ hasTable, boost }: { hasTable: boolean; boost: number }) {
  const { slip, kind, payouts } = useSlip();
  const [odds, setOdds] = useState<EntryOdds | null>(null);
  useEffect(() => {
    if (!hasTable) { setOdds(null); return; }
    let current = true;
    post<EntryOdds>("/api/entries/odds", { probs: slip.map((p) => p.model_p), kind, payouts: { ...payouts, boost } })
      .then((r) => current && setOdds(r)).catch(() => current && setOdds(null));
    return () => { current = false; };
  }, [hasTable, slip, kind, payouts, boost]);
  if (!odds) return null;

  const breakEven = `Break-even: about ${pct(odds.break_even)} per pick.`;
  if (odds.ev == null) {
    return <div className="odds">{breakEven} <span className="muted">The model's odds need a model prediction for every pick.</span></div>;
  }
  const edge = odds.ev - 1;
  return (
    <div className="odds">
      <b>Model's view of this entry:</b> {pct(odds.p_all)} chance all {slip.length} hit · {pct(odds.p_profit)} chance of a profit ·
      expected return <b style={{ color: `var(${edge >= 0 ? "--more" : "--less"})` }}>{odds.ev.toFixed(2)}x</b>
      {" "}({edge >= 0 ? "+" : ""}{(edge * 100).toFixed(0)}% per $1). {breakEven}
      <div className="muted small"><IndependenceNote names={slip.map((p) => p.player)} /></div>
    </div>
  );
}

/** The entry odds treat every pick as independent. Two lines on one player (Points and Rebounds) are
 *  far from it: a big night or an early exit moves both. */
function IndependenceNote({ names }: { names: string[] }) {
  const twice = [...new Set(names.filter((name, i) => names.indexOf(name) !== i))];
  return twice.length
    ? <>Assumes picks are independent, but {twice.join(" and ")} {twice.length === 1 ? "has" : "have"} more than one pick,
        and those tend to hit or miss together, so take these odds as rougher than usual.</>
    : <>Assumes picks are independent. Picks from the same game often aren't.</>;
}

// ------------------------------------------------------------- saved entries
function OpenEntries({ reload }: { reload: number }) {
  // kept between tab switches (shown at once when you come back, refreshed in the background)
  const [entries, setEntries] = useKept<Entry[] | null>("entries.open", null);
  const [view, setView] = useState(loadEntriesView);

  const load = useCallback(async () => {
    const r = await api<{ entries: Entry[] }>("/api/entries");
    setEntries(r.entries.filter((e) => e.status === "open"));
  }, []);
  useEffect(() => { load(); }, [load, reload]);

  const [pulls, setPulls] = useKept("entries.pulls", 0);   // pull-to-refresh count: the chances are re-checked too
  const { live, refresh: refreshLive } = useEntriesLive(entries);
  const { now, note } = useChancesNow(entries, pulls);

  /** Pull to refresh: the entries and their live scores now (the chances follow a moment later). */
  async function refreshAll() {
    setPulls((n) => n + 1);
    await Promise.all([load(), refreshLive()]);
  }

  async function remove(id: number) {
    if (!confirm("Delete this entry? This can't be undone.")) return;
    await api(`/api/entries/${id}`, { method: "DELETE" });
    load();
  }

  /** Mark an entry saved without the box ticked as a protected play (or undo it). */
  async function protect(id: number, isProtected: boolean) {
    await post(`/api/entries/${id}/protected`, { protected: isProtected });
    load();
  }

  /** Change an entry's payouts and profit boost to what PrizePicks shows; its chances follow at once. */
  async function setPayouts(id: number, payouts: EntryPayouts) {
    await post(`/api/entries/${id}/payouts`, { payouts });
    await refreshAll();
  }

  return (
    <>
      <PullToRefresh onRefresh={refreshAll} />
      <div className="row between section-head">
        <h3>Open entries</h3>
        <Seg small label="How to show open entries" value={view} onChange={(v) => { setView(v); saveEntriesView(v); }} options={[
          { value: "list", title: "One entry per row", label: <><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 3.5h12M2 8h12M2 12.5h12" /></svg>List</> },
          { value: "grid", title: "Two entries per row", label: <><svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="2" width="5" height="5" rx="1" /><rect x="9" y="2" width="5" height="5" rx="1" /><rect x="2" y="9" width="5" height="5" rx="1" /><rect x="9" y="9" width="5" height="5" rx="1" /></svg>Grid</> },
        ]} />
      </div>
      <p className="muted small">{note}</p>
      {live?.feed_down && <p className="note small">Neither NBA.com's live feed nor ESPN's is answering right now, so the
        picks show the last numbers they sent (the game clock shows when from). NBALine keeps trying every 15 seconds.</p>}
      <div id="openEntries" className={view === "grid" ? "grid" : ""}>
        {!entries ? <p className="muted">Loading…</p>
          : entries.length ? entries.map((e) => <EntryCard key={e.id} e={e} live={live} now={now} onDelete={() => remove(e.id)}
              onProtect={(on) => protect(e.id, on)} onPayouts={(payouts) => setPayouts(e.id, payouts)} />)
          : <div className="empty">No open entries.</div>}
      </div>
    </>
  );
}

/** While picks are being played: each pick's stat so far and whether it has already won or lost, and
 *  each entry what it can still pay. Every 15 seconds while a game is on (2 minutes while waiting for one),
 *  and at once on coming back to the tab. `refresh` asks right away (pull to refresh) and starts the count
 *  again from then. */
function useEntriesLive(entries: Entry[] | null) {
  const [live, setLive] = useKept<EntriesLive | null>("entries.live", null);
  const followNow = useRef<() => Promise<void>>(async () => {});
  const which = entries?.map((e) => e.id).join(",") ?? "";
  useEffect(() => {
    if (!which) return;
    let alive = true;
    const checks = keepChecking(async () => {
      const now = await api<EntriesLive>("/api/entries/live", { timeoutMs: GIVE_UP_AFTER });
      if (!alive) return null;
      setLive(now);
      return now.live ? LIVE_EVERY : now.pending ? WAITING_EVERY : null;
    }, LIVE_EVERY);
    followNow.current = checks.now;
    return () => { alive = false; checks.stop(); followNow.current = async () => {}; };
  }, [which]);
  return { live, refresh: () => followNow.current() };
}

/** An entry keeps the chances from when you saved it. This re-checks open picks with the latest data,
 *  model and injury report, so each shows how it moved: "83.4% → 79.1%". It runs the model, so coming
 *  back to the tab re-checks only if the last check is a few minutes old; a pull to refresh (`again`)
 *  or a changed list of entries always does. */
const RECHECK_AFTER_MS = 5 * 60_000;

function useChancesNow(entries: Entry[] | null, again: number) {
  const [now, setNow] = useKept<ChancesNow | null>("entries.chancesNow", null);
  const [note, setNote] = useKept("entries.chancesNote", "");
  const [checked, setChecked] = useKept<{ which: string; again: number; at: number } | null>("entries.chancesChecked", null);
  const which = entries?.map((e) => e.id).join(",") ?? "";
  useEffect(() => {
    if (!which) { setNote(""); return; }
    if (checked && checked.which === which && checked.again === again && Date.now() - checked.at < RECHECK_AFTER_MS) return;
    let current = true;
    setNote("Re-checking open picks with the latest data and injury report…");
    api<ChancesNow>("/api/entries/now")
      .then((r) => {
        if (!current) return;
        setNow(r);
        setChecked({ which, again, at: Date.now() });
        setNote("Saved % → % now, with the latest data, model and injury report. Green went up, red went down.");
      })
      .catch((e) => current && setNote(`Couldn't re-check the open picks: ${messageOf(e)}`));
    return () => { current = false; };
  }, [which, again]);   // `checked` is only read here, so a finished check doesn't start another
  return { now, note };
}
