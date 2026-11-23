// What the page remembers between visits, saved in this browser only (localStorage): the entry slip,
// the last pasted board for 12 hours, the Best lineup's size, how open entries are shown, and how
// Results' sections are opened and sorted. The names are the same as the earlier page used, so nothing is lost in the switch.
import type { EntryKind, LineType, Side } from "./types";

/** A pick on the entry slip, before it's saved as an entry. */
export interface SlipPick {
  player: string;
  team?: string;
  opp?: string;
  stat: string;
  line: number;
  side: Side;
  p_over: number | null;
  model_p: number | null;
  line_type?: LineType;
  line_hint?: "goblin" | "demon" | null;
  manual?: boolean;
}

export type StatSort = { by: "stat" | "lines" | "right" | "breakeven"; desc: boolean };
export type StatView = "all" | "shown";

const SLIP_KEY = "nbaline-slip";
const BOARD_KEY = "nbaline-board";
const VIEW_KEY = "nbaline-entries-view";
const LINEUP_SIZE_KEY = "nbaline-lineup-size";
const STAT_SORT_KEY = "nbaline-stat-sort";
const STAT_VIEW_KEY = "nbaline-stat-view";
const BOARD_KEEP_MS = 12 * 60 * 60 * 1000;

// localStorage can be unavailable (private mode, blocked storage): the page still works, it just forgets.
function read<T>(key: string): T | null {
  try { return JSON.parse(localStorage.getItem(key) || "null"); } catch { return null; }
}
function write(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* not saved */ }
}
function forget(key: string) {
  try { localStorage.removeItem(key); } catch { /* nothing to forget */ }
}

export function loadSlip(): { slip: SlipPick[]; kind: EntryKind } {
  const saved = read<{ slip?: SlipPick[]; kind?: EntryKind }>(SLIP_KEY) || {};
  return { slip: saved.slip || [], kind: saved.kind || "power" };
}
export const saveSlip = (slip: SlipPick[], kind: EntryKind) => write(SLIP_KEY, { slip, kind });

/** The last pasted board, if it was pasted in the last 12 hours. */
export function loadBoardText(): { text: string; target?: string } | null {
  const saved = read<{ text: string; target?: string; at: number }>(BOARD_KEY);
  return saved && Date.now() - saved.at < BOARD_KEEP_MS ? saved : null;
}
export const saveBoardText = (text: string, target: string) => write(BOARD_KEY, { text, target, at: Date.now() });
export const forgetBoardText = () => forget(BOARD_KEY);

/** The Standard lineup's size: a 6-pick Flex (the default) or a 5-pick Flex. */
export const loadLineupSize = (): 6 | 5 => (read(LINEUP_SIZE_KEY) === 5 ? 5 : 6);
export const saveLineupSize = (size: 6 | 5) => write(LINEUP_SIZE_KEY, size);

/** Whether a collapsible section (e.g. "byStat" on Results) was left open. */
export const loadSectionOpen = (name: string, fallback = false) => read<boolean>(`nbaline-open-${name}`) ?? fallback;
export const saveSectionOpen = (name: string, open: boolean) => write(`nbaline-open-${name}`, open);

/** Open entries as "list" (one per row, the default) or "grid" (two per row). */
export const loadEntriesView = (): "list" | "grid" => (read(VIEW_KEY) === "grid" ? "grid" : "list");
export const saveEntriesView = (view: "list" | "grid") => write(VIEW_KEY, view);

/** How Results' "Model's pick by stat" table is sorted. */
export const loadStatSort = (): StatSort => read<StatSort>(STAT_SORT_KEY) || { by: "lines", desc: true };
export const saveStatSort = (sort: StatSort) => write(STAT_SORT_KEY, sort);

/** Which lines that table counts: "all" graded standard lines (the default), or only the "shown" picks. */
export const loadStatView = (): StatView => (read(STAT_VIEW_KEY) === "shown" ? "shown" : "all");
export const saveStatView = (view: StatView) => write(STAT_VIEW_KEY, view);
