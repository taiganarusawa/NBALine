// The entry slip: the picks you're putting together before playing them on PrizePicks, the entry type
// (Power or Flex), and the payout table, which you can edit to match your PrizePicks app.
// Every change is saved in this browser, so the slip survives a refresh.
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { withMultiplier } from "../components/Payouts";
import { loadSlip, saveSlip, type SlipPick } from "../storage";
import type { EntryKind, LineResult, Payouts, Side } from "../types";
import { useApp } from "./AppContext";

const MAX_PICKS = 6;

/** The same player + stat + line is the same pick. */
export const slipKey = (player: string, stat: string, line: number) => `${player.toLowerCase()}|${stat}|${Number(line)}`;

/** The model's chance that a pick hits, given its chance of going over. */
export const chanceFor = (pOver: number | null | undefined, side: Side) =>
  pOver == null ? null : side === "more" ? pOver : 1 - pOver;

interface SlipState {
  slip: SlipPick[];
  kind: EntryKind;
  setKind: (kind: EntryKind) => void;
  payouts: Payouts;
  setPayout: (hits: string, multiplier: number) => void;
  /** What the lineup pays when players revert, by picks left (editable like the payouts). */
  reverted: Payouts;
  setReverted: (picksLeft: string, hits: string, multiplier: number) => void;
  /** The slip's pick for this line, if it's on the slip. */
  pickFor: (line: { player: string; stat: string; line: number }) => SlipPick | undefined;
  /** What a + More / + Less / + Add button does: add the pick, switch its side, or take it off again. */
  togglePick: (line: LineResult, side: Side) => void;
  /** Replace the slip with a whole lineup (each line on its own side) and set its entry type. */
  loadLineup: (lines: LineResult[], kind: EntryKind) => void;
  addManualPick: (player: string, stat: string, line: number, side: Side) => void;
  removePick: (index: number) => void;
  setSide: (index: number, side: Side) => void;
  clearSlip: () => void;
}

const SlipContext = createContext<SlipState | null>(null);

export function useSlip() {
  const slip = useContext(SlipContext);
  if (!slip) throw new Error("useSlip must be used inside <SlipProvider>");
  return slip;
}

export function SlipProvider({ children }: { children: ReactNode }) {
  const { meta, toast } = useApp();
  const [{ slip, kind }, setSaved] = useState(loadSlip);
  const [payouts, setPayouts] = useState<Payouts>(() => structuredClone(meta.payouts));   // your edits stay on this page
  const [reverted, setRevertedAll] = useState<Payouts>(() => structuredClone(meta.reverted ?? { power: {}, flex: {} }));
  useEffect(() => saveSlip(slip, kind), [slip, kind]);

  const setSlip = (next: SlipPick[]) => setSaved((s) => ({ ...s, slip: next }));
  const indexOf = (line: { player: string; stat: string; line: number }) =>
    slip.findIndex((p) => slipKey(p.player, p.stat, p.line) === slipKey(line.player, line.stat, line.line));

  const slipPick = (r: LineResult, side: Side): SlipPick => ({
    player: r.player, team: r.team, opp: r.opp, stat: r.stat, line: r.line, side,
    p_over: r.p_over ?? null, model_p: chanceFor(r.p_over, side), line_type: r.line_type || null, line_hint: r.line_hint || null,
  });

  function addPick(r: LineResult, side: Side) {
    if (slip.length >= MAX_PICKS) return toast(`An entry can have at most ${MAX_PICKS} picks.`);
    // PrizePicks allows one player on different stats in the same entry, but only one line per stat
    const sameStat = slip.find((p) => p.player === r.player && p.stat === r.stat);
    if (sameStat) return toast(`${r.player} ${r.stat} ${sameStat.line} is already on the slip. Take it off first to use this line.`);
    setSlip([...slip, slipPick(r, side)]);
    toast(`Added ${r.player} ${side.toUpperCase()} ${r.line} to your entry slip`);
  }

  function removePick(index: number) {
    const pick = slip[index];
    setSlip(slip.filter((_, i) => i !== index));
    toast(`Took ${pick.player} ${pick.side.toUpperCase()} ${pick.line} off your entry slip`);
  }

  function setSide(index: number, side: Side) {
    setSlip(slip.map((p, i) => (i === index ? { ...p, side, model_p: chanceFor(p.p_over, side) } : p)));
  }

  const value: SlipState = {
    slip,
    kind,
    setKind: (k) => setSaved((s) => ({ ...s, kind: k })),
    payouts,
    setPayout: (hits, multiplier) => setPayouts((all) => {
      const next = structuredClone(all);
      next[kind][String(slip.length)][hits] = multiplier;
      return next;
    }),
    reverted,
    setReverted: (left, hits, multiplier) => setRevertedAll((all) => withMultiplier(all, kind, left, hits, multiplier)),
    pickFor: (line) => slip[indexOf(line)],
    togglePick(line, side) {
      const i = indexOf(line);
      if (i < 0) return addPick(line, side);
      if (slip[i].side === side) return removePick(i);
      setSide(i, side);
      toast(`Switched ${line.player} to ${side.toUpperCase()} ${line.line}`);
    },
    loadLineup(lines, k) {
      setSaved({ slip: lines.slice(0, MAX_PICKS).map((r) => slipPick(r, r.side!)), kind: k });
      toast(`Your entry slip is now this ${lines.length}-pick ${k === "power" ? "Power" : "Flex"}`);
    },
    addManualPick(player, stat, line, side) {
      if (slip.length >= MAX_PICKS) return toast(`An entry can have at most ${MAX_PICKS} picks.`);
      setSlip([...slip, { player, stat, line, side, p_over: null, model_p: null, manual: true }]);
    },
    removePick,
    setSide,
    clearSlip: () => setSlip([]),
  };
  return <SlipContext.Provider value={value}>{children}</SlipContext.Provider>;
}
