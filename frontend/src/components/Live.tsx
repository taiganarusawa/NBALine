// Live game pieces shared by My entries, Check lines and Best lines: the progress bar toward the line,
// the "Pace %" pill, the on court / bench tag, the score, and for Check lines and Best lines a whole live
// section per line, with the model's chance from here. The data comes from /api/entries/live or /api/lines/live.
import { useEffect, useState } from "react";
import { post } from "../api";
import { pct } from "../format";
import { LEAN_AT } from "../labels";
import { GIVE_UP_AFTER, keepChecking, LIVE_EVERY } from "../poll";
import type { LineResult, LiveState, Side } from "../types";

/** The side a line is followed for: the model's pick (More for a Goblin or Demon, the only side). */
export const pickSide = (r: LineResult): Side => r.side || (r.p_over == null || r.p_over >= 0.5 ? "more" : "less");

/** Follows lines whose game has started: their live state now, and again every 15 seconds while one
 *  is still being played and the tab is open (and at once on coming back to it). Lines are keyed by id. */
export function useLiveLines(lines: { id: string; r: LineResult }[]) {
  const [now, setNow] = useState<Record<string, LiveState>>({});
  const which = lines.map((l) => l.id).join(",");

  useEffect(() => {
    if (!lines.length) return;
    let alive = true;
    const body = lines.map(({ id, r }) => ({
      id, player_id: r.player_id, game_id: r.game_id, game_date: r.game_date, stat: r.stat, line: r.line,
      side: pickSide(r), proj: r.proj, sd: r.sd, usual_minutes: r.usual_minutes,
    }));
    const checks = keepChecking(async () => {
      const res = await post<{ picks: Record<string, LiveState>; live: boolean }>("/api/lines/live", { lines: body },
        { timeoutMs: GIVE_UP_AFTER });
      if (!alive) return null;
      setNow(res.picks);
      return res.live ? LIVE_EVERY : null;
    }, LIVE_EVERY);
    return () => { alive = false; checks.stop(); };
  }, [which]);   // starts over only when the set of lines changes (`which` names them)

  return now;
}

/** A line's live section: score, clock, on court, pace, the bar toward the line, how the model's pick
 *  stands, and the model's chance from here (r is the line, x its live state). */
export function LiveBox({ r, x }: { r: LineResult; x?: LiveState }) {
  const side = pickSide(r);
  const known = x?.clock != null;   // NBA.com's feed has sent his game
  return (
    <div className={`live-box${known && !x.game_live ? " over" : ""}`}>
      <div className="live-head">
        <span className="live-dot" hidden={known && !x.game_live} /><b className="live-label">{known && !x.game_live ? "FINAL" : "LIVE"}</b>
        {known ? (
          <>
            {x.score && <span><GameLine team={r.team!} opp={r.opp!} x={{ ...x, game_final: false }} /></span>}
            {x.game_live && <span className="muted">{clockText(x)}</span>}
            <CourtTag x={x} />
            <FeedDown x={x} />
            <PacePill x={x} side={side} />
          </>
        ) : (
          <span className="muted">{x?.feed_down ? "waiting for NBA.com's live feed…" : "getting the live box score…"}</span>
        )}
      </div>
      {known && <ProgressBar x={x} line={r.line} />}
      {known && (
        <div className="live-note">
          {r.p_over == null ? side.toUpperCase() : <>Model's pick <b>{side.toUpperCase()}</b></>} {r.line}:{" "}
          <span className={`r-${x.state}`}>{x.text}</span>
        </div>
      )}
      {known && <LiveChance x={x} r={r} />}
    </div>
  );
}

/** "Live pick MORE · More 72% · Less 28% · heading for about 27 (before tip-off: More 54%)": the
 *  pre-game projection updated with his stats, minutes and the time left (nbaline/pickem/ingame.py). */
function LiveChance({ x, r }: { x: LiveState; r: LineResult }) {
  if (x.state !== "live" || x.live_more == null) return null;
  const more = x.live_more, less = 1 - more;
  const moreOnly = r.sides && r.sides !== "both";   // a Goblin or Demon: More is the only side
  const lean = more >= LEAN_AT ? "more" : !moreOnly && less >= LEAN_AT ? "less" : null;
  return (
    <div className="live-chance">
      {lean ? <span className={`lean ${lean}`}>Live pick {lean.toUpperCase()}</span> : <span className="muted">No clear edge now</span>}
      {" "}More <b>{pct(more)}</b>{!moreOnly && <> · Less <b>{pct(less)}</b></>} · heading for about {x.live_expected}
      {r.p_over != null && <span className="muted"> (before tip-off: More {pct(r.p_over)})</span>}
    </div>
  );
}

/** "feed not answering": NBA.com's live feed didn't answer the last check, so these are the last
 *  numbers it sent (the clock shows when from). */
function FeedDown({ x }: { x?: LiveState }) {
  if (!x?.feed_down) return null;
  return <span className="feed-down" title={FEED_DOWN_TIP}>feed not answering</span>;
}

const FEED_DOWN_TIP = "NBA.com's live feed didn't answer the last check, so these are the last numbers it sent " +
  "(the game clock shows when from). NBALine keeps trying every 15 seconds.";

const BAR_LOOK: Record<string, string> = { hit: "won", miss: "lost", push: "even", void: "even", live: "live" };

/** The bar runs from 0 to the line: how far he's got, coloured by where the pick stands, with his
 *  number under the end of the fill. Nothing until there's a number. */
export function ProgressBar({ x, line }: { x?: LiveState; line: number }) {
  if (x?.value == null) return null;
  const share = Math.min(Math.max(x.value / Math.max(line, 0.5), 0), 1);
  const look = BAR_LOOK[x.state] || "live";
  return (
    <div className="pbar-row">
      <div className="pbar"><div className={`fill ${look}`} style={{ width: `${share * 100}%` }} /></div>
      <div className="pbar-val">
        <span className={look} style={{ left: `clamp(4px, ${share * 100}%, calc(100% - 4px))` }}>{x.value}</span>
      </div>
    </div>
  );
}

/** "Pace 80%": where he finishes at this rate, as a share of the line (like PrizePicks). Green when that's
 *  on the right side of the line for this pick, amber when behind, red once lost, grey for a push or void. */
export function PacePill({ x, side }: { x?: LiveState; side: Side }) {
  if (x?.pace == null) return null;
  const onPace = side === "more" ? x.pace > 1 : x.pace < 1;
  const look = x.state === "hit" ? "good" : x.state === "miss" ? "bad" : x.state === "push" || x.state === "void" ? "even"
    : onPace ? "good" : "behind";
  return (
    <span className={`pace ${look}`} title={x.state === "live" ? `At this rate he finishes with about ${x.projected}` : `Finished with ${x.value}`}>
      Pace {Math.round(x.pace * 100)}%
    </span>
  );
}

/** "on court" / "bench" tag while his game is on. */
export function CourtTag({ x }: { x?: LiveState }) {
  if (!x?.game_live || x.state === "void") return null;
  return x.on_court
    ? <span className="badge court" title="On the floor right now">on court</span>
    : <span className="badge bench" title="On the bench right now">bench</span>;
}

/** The game next to the player: "UTA – MIA" before tip-off, "UTA 98 – MIA 102" while it's on,
 *  "UTA 109 – MIA 115 · Final" after. His team first; its score is green when ahead, red when behind. */
export function GameLine({ team, opp, x }: { team: string; opp: string; x?: LiveState }) {
  const score = x?.score;
  if (!score || score[team] == null || score[opp] == null) return <>{team} – {opp}</>;
  const mine = score[team], theirs = score[opp];
  const look = mine > theirs ? "ahead" : mine < theirs ? "behind" : "";
  return (
    <>
      <span className="score">{team} <b className={look}>{mine}</b> – {opp} <b>{theirs}</b></span>
      {x?.game_final && <span className="muted"> · Final</span>}
    </>
  );
}

/** "Q3 4:12 · 31 min" while in play, else the game status ("Final"). */
export function clockText(x?: LiveState) {
  if (!x?.clock) return "";
  return x.state === "live" && x.minutes != null ? `${x.clock} · ${x.minutes} min` : x.clock;
}
