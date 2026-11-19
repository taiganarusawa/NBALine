// Payout boxes, shared by the entry slip (before you save) and an open entry's Payouts editor: each table
// as PrizePicks shows it before any boost, the Profit Boost, and what each payout comes to with it.
// The math is the same as nbaline/pickem/payouts.py, which is what grading and the chances use.
import { useState, type FormEvent } from "react";
import { messageOf } from "../api";
import { useApp } from "../context/AppContext";
import { TIPS, tipProps } from "../labels";
import type { Entry, EntryKind, EntryPayouts, Payouts } from "../types";

/** A multiplier with a Profit Boost (0.3 = 30%), as payouts.boosted: above 1x it's on the part above
 *  the entry fee (7x -> 8.8x); at 1x or less, on the whole amount (0.4x -> 0.52x). */
export const boosted = (m: number, boost: number) => (!boost ? m : m > 1 ? m + boost * (m - 1) : m * (1 + boost));

/** The boost box's "30" -> 0.3 (empty, or not a number: 0). */
export const boostRate = (percent: string) => Math.max(parseFloat(percent) || 0, 0) / 100;

/** 0.3 -> "30" for the boost box (no boost: empty). */
export const boostPercent = (boost?: number) => (boost ? String(+(boost * 100).toFixed(2)) : "");

/** "8.8x", "1.325x" */
const times = (m: number) => `${+m.toFixed(3)}x`;

/** The Profit Boost box, in %. */
export function BoostInput({ value, onChange }: { value: string; onChange: (percent: string) => void }) {
  return (
    <label className="boost-input" {...tipProps(TIPS.boost)}>Profit boost (%)
      <input type="number" inputMode="decimal" min="0" max="500" step="any" placeholder="none" value={value}
        onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

/** One table's boxes, most hits first ("5 of 6 correct" [7]), as PrizePicks shows it before any boost;
 *  with a boost, what each comes to beside its box ("→ 8.8x"). `of`: the picks in the lineup.
 *  The boxes keep what you type, so give this a key that changes when the table does. */
export function PayoutBoxes({ table, of, boost, onChange }: {
  table: Record<string, number>; of?: number; boost: number; onChange: (hits: string, multiplier: number) => void;
}) {
  return (
    <div className="row gap wrap">
      {Object.keys(table).sort((a, b) => +b - +a).map((hits) => {
        const m = table[hits], withBoost = boosted(m, boost);
        return (
          <label key={hits} className="payout">{hits}{of ? ` of ${of}` : ""} correct
            <span className="payout-box">
              <input type="number" inputMode="decimal" step="any" min="0" defaultValue={m}
                onChange={(e) => onChange(hits, parseFloat(e.target.value) || 0)} />
              {withBoost !== m && <span className="boosted" title="With the profit boost">→ {times(withBoost)}</span>}
            </span>
          </label>
        );
      })}
    </div>
  );
}

/** What the lineup pays if players revert (didn't play, or exactly on the line), one row per number of
 *  picks left, like PrizePicks' "What is a reverted payout?" table. `now`: picks already reverted, so
 *  the row that pays now is marked. */
export function RevertedRows({ kind, picks, reverted, boost, now = 0, onChange }: {
  kind: EntryKind; picks: number; reverted: Payouts; boost: number; now?: number;
  onChange: (picksLeft: string, hits: string, multiplier: number) => void;
}) {
  const rows = Array.from({ length: picks - 1 }, (_, i) => picks - 1 - i);   // picks left: n-1 down to 1
  return (
    <>
      {rows.map((left) => {
        const out = picks - left, table = reverted[kind]?.[String(left)];
        return (
          <div key={`${kind}-${picks}-${left}`} className={`reverted-row${out === now ? " now" : ""}`}>
            <div className="label">If {out} revert{out > 1 ? "" : "s"} ({left} pick{left > 1 ? "s" : ""} left)
              {out === now && <> <span className="badge now">pays now</span></>}</div>
            {table ? <PayoutBoxes table={table} boost={boost} onChange={(hits, m) => onChange(String(left), hits, m)} />
              : <span className="muted small">refunded</span>}
          </div>
        );
      })}
      <div className="label">If all {picks} revert: refunded</div>
    </>
  );
}

/** Set one multiplier in a payouts table (kind -> picks -> hits), as a new copy. */
export function withMultiplier(all: Payouts, kind: EntryKind, picks: string, hits: string, m: number): Payouts {
  const next = structuredClone(all);
  ((next[kind] ||= {})[picks] ||= {})[hits] = m;
  return next;
}

/** An open entry's payouts, to match what PrizePicks shows: the profit boost, what the lineup pays, and
 *  what it pays if players revert. Goblins and Demons change all of these, and once a pick is removed
 *  PrizePicks shows what the rest pays. `removed`: picks reverted so far, so that row is marked. */
export function PayoutsEditor({ e, removed, onSave, onClose }: {
  e: Entry; removed: number; onSave: (payouts: EntryPayouts) => Promise<void>; onClose: () => void;
}) {
  const { meta } = useApp();
  const n = e.picks.length;
  const [boost, setBoost] = useState(boostPercent(e.payouts.boost));
  const [table, setTable] = useState<Record<string, number>>(() => structuredClone(e.payouts[e.kind]?.[String(n)] ?? {}));
  const [reverted, setReverted] = useState<Payouts>(() => structuredClone(e.payouts.reverted ?? meta.reverted));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const rate = boostRate(boost);

  async function save(ev: FormEvent) {
    ev.preventDefault();
    setSaving(true);
    try {
      await onSave({ ...e.payouts, [e.kind]: { ...e.payouts[e.kind], [n]: table }, reverted, boost: rate });
      onClose();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="payouts-edit" onSubmit={save}>
      <div className="muted small">Copy what PrizePicks shows for this lineup, before any boost. Goblins and Demons
        change every row, and once a pick is removed, PrizePicks shows what the rest pays.</div>
      <div className="row gap wrap"><BoostInput value={boost} onChange={(v) => { setBoost(v); setError(""); }} /></div>
      <div className="label">All {n} count</div>
      <PayoutBoxes table={table} of={n} boost={rate} onChange={(hits, m) => setTable((t) => ({ ...t, [hits]: m }))} />
      <RevertedRows kind={e.kind} picks={n} reverted={reverted} boost={rate} now={removed}
        onChange={(left, hits, m) => setReverted((all) => withMultiplier(all, e.kind, left, hits, m))} />
      <div className="row gap wrap payouts-edit-actions">
        <button className="primary small" disabled={saving}>Save payouts</button>
        <button type="button" className="ghost small" disabled={saving} onClick={onClose}>Cancel</button>
        {error && <span className="error-text small">{error}</span>}
      </div>
    </form>
  );
}
