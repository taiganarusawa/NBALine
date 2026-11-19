// Explanations shown on hover, and the rules behind a few labels.
import { pct } from "./format";
import type { LineResult } from "./types";

/** A "lean" (before or during the game) needs at least this chance on one side: the per-pick
 *  break-even of a 5/6-pick Flex. */
export const LEAN_AT = 0.542;

/** Props that give an element a hover explanation (see Tooltip.tsx); none when there's nothing to explain. */
export const tipProps = (text: string | null | undefined) => (text ? { "data-tip": text, tabIndex: 0 } : {});

export const TIPS = {
  median: "The average is pulled up by a few big nights. The median is his typical game: half his games " +
    "land above it, half below. The median is what decides More vs. Less, so a pick can say LESS even " +
    "when the average is above the line.",
  lessTested: "This stat's model hasn't been shown to beat a simple average: it's either not tested yet, " +
    "or it didn't clearly win when tested.",
  push: "Landing exactly on a whole-number line is a push: PrizePicks removes the pick and the entry drops a size. " +
    "The More and Less chances above leave pushes out, so they add up to 100% and compare to the break-even.",
  lowMinutes: "He's averaged under 15 minutes over his last 10 games. The models were built and tested on " +
    "players above that; for bench players their chances were off by about 6 points in testing.",
  injuriesGuessed: "No official injury report covers this game yet, so who's out is guessed from recent games. " +
    "Run it again closer to tip-off.",
  moreOnly: "PrizePicks only offers More on this line.",
  lineup: "A change of role usually changes his minutes, and the model takes tonight's role into account. " +
    "\"Expected\" lineups can still change; they're \"Confirmed\" about 30 minutes before tip-off.",
  inactive: "NBA.com's lineups list him as inactive for tonight's game: he isn't expected to play. " +
    "On PrizePicks a player who doesn't play is removed from your lineup (it reverts).",
  boost: "A Profit Boost (a PrizePicks promo) adds this percentage to the winnings above your entry fee. " +
    "With 30%, a 7x payout pays 8.8x and 1.25x pays 1.325x; a payout of 1x or less gets it on the whole " +
    "amount, so 0.4x pays 0.52x. " +
    "The app adds it to every payout of the entry, including what it pays if players revert.",
  protectedPlay: "A PrizePicks protected play: if it loses outright, you don't lose the money, so it's left out of " +
    "your profit and ROI. If it pays anything back, it counts like any other entry.",
};

const STATUS_TIPS: Record<string, string> = {
  Available: "Available: cleared to play.",
  Probable: "Probable: very likely to play (rule of thumb: about 75% or more). The team has to list even a " +
    "minor injury or illness.\n\nIf he sits anyway, PrizePicks removes the pick and your entry drops a size.\n" +
    "The bigger risk is that he plays hurt: the model predicts him as if he's healthy.\n\nUsually fine to play.",
  Questionable: "Questionable: could go either way (rule of thumb: about 50%).\n\nIf he sits, PrizePicks removes " +
    "the pick and your entry drops a size.\nIf he plays hurt, the model predicts him as if he's healthy.\n\n" +
    "Check the news before tip-off. Teams update the report every 15 minutes.",
  Doubtful: "Doubtful: very unlikely to play (rule of thumb: about 25%). The app treats him as out.",
  Out: "Out: not playing. The app leaves him out of the rankings.",
};

export const LINE_TYPE_TIPS = {
  goblin: "Goblin: an easier line than his standard one, so it pays less. PrizePicks shows the exact payout " +
    "when you build the entry.",
  demon: "Demon: a harder line than his standard one, so it pays more. PrizePicks shows the exact payout " +
    "when you build the entry.",
};

/** Hover text for an injury-report entry like "Probable: Injury/Illness - Right Wrist Sprain". */
export function statusTip(text: string | null | undefined): string {
  const status = Object.keys(STATUS_TIPS).find((s) => new RegExp(`\\b${s}\\b`).test(text || ""));
  if (!status || !text) return "";
  const reason = text.includes(":") ? text.split(":").slice(1).join(":").trim() : "";
  return STATUS_TIPS[status] + (reason ? `\n\nOfficial injury report: ${reason}` : "");
}

/** Hover text for a line's chance: says so when it was adjusted to the model's record against
 *  PrizePicks (the server sends the model's own chance as p_over_model; see Results). */
export const chanceTitle = (r: LineResult, plain: string) => (r.p_over_model == null ? plain
  : `Adjusted to the model's record against PrizePicks (Results › Chance adjustment). The model's own chance of More: ${pct(r.p_over_model)}`);
