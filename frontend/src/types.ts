// What the server (webapp.py) sends, as TypeScript types. Field names match the JSON exactly.

export type Side = "more" | "less";
export type EntryKind = "power" | "flex";
/** Empty for a standard line. Goblins and Demons are More-only; "more_only" when the board didn't say which. */
export type LineType = "goblin" | "demon" | "more_only" | null;

/** Payout multipliers: kind -> picks in the entry -> picks that hit -> multiplier. */
export type Payouts = Record<EntryKind, Record<string, Record<string, number>>>;

/** An entry's own payouts (nbaline/pickem/payouts.py): its tables as PrizePicks shows them before any
 *  boost, what it pays if players revert (by picks left), and a Profit Boost (0.3 = 30%) on top. */
export type EntryPayouts = Payouts & { reverted?: Payouts; boost?: number };

/** /api/meta: everything the page needs at startup. */
export interface Meta {
  today: string;
  model: string;
  trained_on: string;
  data_through: string;
  warnings: string[];
  stats: string[];
  modeled: string[];
  payouts: Payouts;
  /** What a lineup pays when players revert (DNP, or exactly on the line): kind -> picks left -> hits -> multiplier. */
  reverted: Payouts;
  targets: Record<string, { label: string; break_even: number }>;
  break_even: Record<EntryKind, Record<string, number>>;
}

export interface Player {
  name: string;
  team: string;
  opp: string;
  home: boolean;
  tip: string;
}

/** His last 10 games against this line. */
export interface History {
  avg10: number | null;
  over10: number;
  n10: number;
  recent: [date: string, value: number][];
}

/** One analyzed line (lines.analyze_lines). On Best lines, ranking.rank_board adds the side and edge. */
export interface LineResult {
  player: string;
  stat: string;
  line: number;
  error?: string | null;
  player_id?: number;
  team?: string;
  opp?: string;
  home?: boolean;
  game_date?: string;
  game_id?: string;
  tip_local?: string;
  started?: boolean;
  injury_report?: string | null;
  injury_missing?: string[];
  injury_notes?: string[];
  self_status?: string | null;
  outs?: Record<string, string[]>;
  questionable?: string[];
  /** Tonight's role from NBA.com's lineups, once his team's is posted ("Expected", then "Confirmed"). */
  lineup?: { starting: boolean; status: string; inactive?: boolean } | null;
  /** Share of his last 10 games he started (from 2023-24 on). */
  start_rate?: number | null;
  modeled?: boolean;
  reliable?: boolean;
  yes_no?: boolean;
  low_minutes?: boolean;
  proj?: number;
  q10?: number;
  q50?: number;
  q90?: number;
  sd?: number;
  usual_minutes?: number;
  p_over?: number | null;
  /** The model's own chance of More, when the page shows an adjusted one (calibration.py). */
  p_over_model?: number;
  p_push?: number;
  reasons?: [effect: number, label: string, value: string | number][];
  history?: History;
  // a game that's over
  final?: boolean;
  actual?: number | null;
  outcome?: "over" | "under" | "push" | "dnp";
  // Best lines
  side?: Side;
  p_best?: number;
  edge?: number;
  line_type?: LineType;
  line_hint?: "goblin" | "demon" | null;
  sides?: "both" | "more" | "less";
  reason?: string | null;
}

/** /api/board: a pasted board, sorted into groups. */
export interface BoardResult {
  date: string;
  date_note: string | null;
  target: string;
  break_even: number;
  parsed: number;
  unread: string[];
  ranked: LineResult[];
  more_only: LineResult[];
  live: LineResult[];
  other: LineResult[];
  /** The lineups to play from this board (lineup.py). Missing on a board ranked before they existed. */
  lineups?: Lineup[];
  /** Each stat's record on lines like a lineup's: shown at `at_least` or more (calibration.stat_records). */
  stat_records?: { at_least: number; stats: Record<string, LineRecord> };
}

/** How a stat's graded lines that the page showed at the break-even or more went. verdict: "few" (too
 *  few lines to tell), "losing" / "winning" (even the high / low end of the likely range is under /
 *  at or above the break-even), else "unclear". */
export interface LineRecord {
  lines: number;
  right: number;
  rate: number;
  low: number;
  high: number;
  verdict: "few" | "losing" | "winning" | "unclear";
}

/** How graded Goblins or Demons with a chance like a lineup's did: how often they went over, next to the
 *  model's average chance on them (`said`). verdict: "few" (too few lines to tell), "too_sure" /
 *  "cautious" (even the high / low end of the likely range is under / over what it said), else "fair". */
export interface LineTypeRecord {
  lines: number;
  right: number;
  rate: number;
  low: number;
  high: number;
  said: number;
  verdict: "few" | "too_sure" | "cautious" | "fair";
}

/** A lineup built from a board's ranked lines (nbaline/pickem/lineup.py): "standard" (a Flex of
 *  standard lines), "goblin" (safer) or "demon" (high risk), both a Power. */
export interface Lineup {
  key: "standard" | "goblin" | "demon";
  title: string;
  kind: EntryKind;
  /** Picks in the entry (one of `sizes`), or null when too few lines qualify. */
  size: number | null;
  sizes: number[];
  /** The lineup, best first; when size is null, the few lines that qualify. */
  picks: LineResult[];
  /** The least chance a pick needs (the break-even, for standard lines), the lines that have it, and
   *  how many different players they cover. */
  at_least: number;
  candidates: number;
  players: number;
  avg_chance: number | null;
  /** Whether it's at the standard payouts (standard lines), so its return can be worked out. */
  priced: boolean;
  /** Standard: stats left out for a losing record -> how many of tonight's lines that was. */
  losing?: Record<string, number>;
  /** Standard, at the standard payouts: return per $1, chance of a profit. Every one: chance all picks hit. */
  ev?: number;
  p_profit?: number;
  p_all?: number;
  /** Goblins and Demons: the least PrizePicks must pay for the entry to be worth it, and their record. */
  min_payout?: number;
  record?: LineTypeRecord | null;
}

export type PickResult = "hit" | "miss" | "push" | "void";

export interface Pick {
  id: number;
  player: string;
  team: string;
  opp: string;
  game_date: string;
  stat: string;
  line: number;
  side: Side;
  model_p: number | null;
  actual: number | null;
  result: PickResult | null;
  line_type: LineType;
  /** Open picks: his jersey number, from NBA.com's player index (jerseys.py); null if unknown. */
  jersey?: string | null;
  /** Once graded: why it hit or missed (explain.py). */
  why?: PickWhy;
}

/** What was different about his night, sorted by the way the pick went (explain.pick_reasons). */
export interface PickWhy {
  /** Pushed his number the way it went: why it hit or missed. Most telling first. */
  because: string[];
  /** Pushed it the other way: worked against a hit, or helped a miss but not enough. */
  despite: string[];
  /** How close it finished, what the model expected, his last 10 games (or why it was removed). */
  context: string;
}

export type EntryStatus = "open" | "won" | "lost" | "partial" | "refund";

export interface Entry {
  id: number;
  game_date: string;
  kind: EntryKind;
  stake: number;
  payouts: EntryPayouts;
  ev: number | null;
  status: EntryStatus;
  /** What a graded entry paid (counted in your profit): the app's own amount, or paid_set if you typed one in. */
  payout: number | null;
  /** What PrizePicks really paid, typed in on the Results tab because it differed; null: the app's amount. */
  paid_set?: number | null;
  /** With paid_set: what the app had worked out from the payout table. */
  calculated?: number;
  /** 1 for a PrizePicks protected play: if it loses outright, it's left out of profit and ROI. */
  protected?: number;
  picks: Pick[];
  /** Once graded: "4 of 6 hit · missed on Flagg · 1 removed (push)" (explain.py). */
  why?: string;
  /** Picks that won or lost together: several on one player, or players in the same game. */
  together?: string[];
}

/** A pick or line during its game (live.py). */
export interface LiveState {
  state: "pending" | "live" | PickResult;
  text: string;
  value?: number | null;
  pace?: number | null;
  projected?: number | null;
  clock?: string | null;
  minutes?: number | null;
  on_court?: boolean;
  game_live?: boolean;
  game_final?: boolean;
  score?: Record<string, number>;
  /** A game that hasn't started: its tip-off, as shown ("7:30 PM", "Sat 7:30 PM") and in UTC. */
  tip?: string;
  tip_utc?: string;
  /** The model's chance of More from here, and where he's heading (ingame.py). */
  live_more?: number;
  /** ... and of finishing exactly on a whole-number line: a push, so the pick reverts. */
  live_push?: number;
  live_expected?: number;
  /** NBA.com's live feed didn't answer the last check: these are the last numbers it sent (none yet:
   *  state "live", text "waiting for NBA.com's live feed"). */
  feed_down?: boolean;
}

/** What an open entry can still pay, during the games. */
export interface EntryLive {
  hit: number;
  lost: number;
  live: number;
  pending: number;
  other: number;
  done: boolean;
  locked: number;
  best: number;
  /** How likely each amount it can still pay is, now (null: a pick has no model chance). */
  odds?: EntryOutcomes | null;
}

/** One amount an entry can pay: "5 of 6 hit pays $10.00, 20% likely". hits null: it pays nothing. */
export interface OutcomeTier {
  /** null for "nothing" and for a refund. */
  hits: number | null;
  of: number;
  pays: number;
  /** 0 once a miss has ruled it out. */
  chance: number;
  /** How many more picks push (land exactly on the line, so they revert) to get here: "4 of 4" after one. */
  pushes?: number | null;
  /** Every pick left reverts, or too few are left to pay on: the stake back. */
  refund?: boolean;
}

/** An open entry's chances, from each pick's chance now (live during its game) and what's decided. */
export interface EntryOutcomes {
  tiers: OutcomeTier[];
  expected: number;
  p_profit: number;
  p_cash: number;
}

export interface EntriesLive {
  picks: Record<string, LiveState>;
  entries: Record<string, EntryLive>;
  live: boolean;
  pending: boolean;
  /** A pick's game is on, but NBA.com's live feed didn't answer the last check. */
  feed_down?: boolean;
}

export interface EntryOdds {
  break_even: number | null;
  ev?: number;
  p_all?: number;
  p_profit?: number;
}

export interface UpdateStatus {
  running: boolean;
  percent?: number;
  seconds_left?: number;
  step_no?: number;
  steps?: number;
  step?: string;
  elapsed: number;
  exit_code?: number | null;
  output?: string;
  last?: { run_at: string; ok: boolean; data_through?: string; retrained?: boolean; missing_games?: string[] } | null;
}

// ------------------------------------------------------------- Results
export interface ChanceBand {
  low: number;
  high: number;
  n: number;
  went_over: number;
  model_said: number;
}

export interface MoreOnlyKind {
  lines: { n: number; nights: number; bands: ChanceBand[]; went_over: number | null; model_said: number | null };
  picks: { n: number; hits: number; model_expected: number | null };
}

export interface StatRecord {
  n: number;
  nights: number;
  hit_rate: number;
}

export interface SureBand {
  low: number;
  high: number;
  n: number;
  right: number;
  model_said: number;
}

export interface Summary {
  /** staked, returned, profit and roi leave out protected plays that lost outright (protected_losses). */
  entries: { total: number; open: number; won: number; partial: number; lost: number; refund: number;
             protected_losses?: number; staked: number; returned: number; profit: number; roi: number | null };
  picks: { graded: number; hits: number; hit_rate: number | null };
  entries_more_only: { graded: number; open: number; won: number; staked: number; profit: number; roi: number | null };
  /** Every saved line, and where each went: these parts add up to `lines` (store._saved_lines). */
  saved: { lines: number; days: number; boards: number; waiting: number; waiting_lines: number;
           void: number; push: number; no_model: number; moved: number; graded: number };
  more_only: Record<"goblin" | "demon" | "more_only", MoreOnlyKind>;
  model: {
    graded: number;
    brier_model?: number;
    lean_n?: number;
    lean_hit_rate?: number | null;
    mae?: number | null;
    by_stat?: Record<string, StatRecord>;
    by_sure?: SureBand[];
  };
}

/** The chance adjustment (calibration.py). */
export interface Calibration {
  on: boolean;
  keep: number | null;
  nights: number;
  min_nights: number;
  test: { nights: number; lines: number; nights_better: number; brier_model: number; brier_adjusted: number } | null;
}

export interface ResultsResponse {
  summary: Summary;
  entries: Entry[];
  calibration?: Calibration;
}

export interface LongShot {
  player: string;
  team: string;
  opp: string;
  stat: string;
  line: number;
  line_type: LineType;
  side: Side;
  actual: number;
  chance: number;
  played: boolean;
}

export interface LongShotsResponse {
  days: string[];
  date: string | null;
  lines: LongShot[];
}
