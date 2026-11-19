// Small labels that explain themselves on hover: injury status, "less tested", Goblin/Demon, a role change.
import { LINE_TYPE_TIPS, statusTip, TIPS, tipProps } from "../labels";
import type { LineResult, LineType } from "../types";

/** Why a line's chance deserves less trust: a bench player (the models were built on 15+ minute players),
 *  or a stat whose model hasn't passed testing. */
export function LessTestedBadge({ lowMinutes }: { lowMinutes?: boolean }) {
  return lowMinutes
    ? <span className="badge w" {...tipProps(TIPS.lowMinutes)}>low minutes</span>
    : <span className="badge" {...tipProps(TIPS.lessTested)}>less tested</span>;
}

/** Tonight's role when it's a change: "Starting" for a player who usually comes off the bench, "Bench"
 *  for one who usually starts (NBA.com's posted lineup), or "Inactive" when he's on the inactive list.
 *  Nothing when his role is the usual one. */
export function RoleBadge({ r }: { r: LineResult }) {
  if (r.lineup?.inactive) {
    return <span className="badge bad" {...tipProps(TIPS.inactive)}>Inactive tonight</span>;
  }
  if (!r.lineup || r.start_rate == null) return null;
  const { starting, status } = r.lineup;
  if (starting === r.start_rate >= 0.5) return null;   // his usual role
  const usually = `He started ${Math.round(r.start_rate * 10)} of his last 10 games.`;
  return (
    <span className={`badge ${starting ? "role-up" : "w"}`} {...tipProps(`${starting ? "Starting" : "Off the bench"} tonight `
      + `(${status.toLowerCase()} by NBA.com's lineups). ${usually} ${TIPS.lineup}`)}>
      {starting ? "Starting" : "Bench"} tonight
    </span>
  );
}

/** "Questionable", "Probable", ... from the injury report, with what it means on hover. */
export function StatusBadge({ status }: { status: string }) {
  return <span className="badge w" {...tipProps(statusTip(status))}>{status.split(":")[0]}</span>;
}

/** "Goblin" / "Demon" for a More-only line ("likely ..." when it's a guess); nothing for standard lines.
 *  It's certain when the pasted board also had the player's standard line for that stat. */
export function LineTypeBadge({ lineType, hint }: { lineType?: LineType; hint?: "goblin" | "demon" | null }) {
  const guessed = lineType === "more_only";
  const type = guessed ? hint : lineType;
  if (type !== "goblin" && type !== "demon") {
    return lineType ? <span className="badge" {...tipProps(TIPS.moreOnly)}>More only</span> : null;
  }
  const why = guessed
    ? `\n\nA guess: his standard line wasn't on the pasted board, and this line is ${type === "goblin" ? "below" : "above"} ` +
      "his last-10-game average. PrizePicks marks the real kind with a green (Goblin) or red (Demon) icon."
    : "";
  return (
    <span className={`badge ${type}`} {...tipProps(LINE_TYPE_TIPS[type] + why)}>
      {guessed ? "likely " : ""}{type === "goblin" ? "Goblin" : "Demon"}
    </span>
  );
}
