// Tab 5 · Long shots: the lines that hit on a day although the model gave them little chance, least
// likely first (or most likely first). Which Demons (or other lines) would have paid off against the odds.
import { useEffect, useState } from "react";
import { api, messageOf } from "../api";
import { LineTypeBadge } from "../components/Badges";
import Seg from "../components/Seg";
import ShowInSteps from "../components/ShowInSteps";
import { dayName, pct, plural } from "../format";
import { useKept } from "../kept";
import type { LongShot, LongShotsResponse } from "../types";

const LONG_SHOT = 0.25;   // a "long shot": the model gave it under 25%
type Kind = "all" | "demon" | "goblin" | "standard";
type Order = "lowest" | "highest";   // by the model's chance

export default function LongShots() {
  const [date, setDate] = useKept<string | null>("longshots.date", null);   // none chosen: the latest graded day
  const [kind, setKind] = useKept<Kind>("longshots.kind", "all");
  const [order, setOrder] = useKept<Order>("longshots.order", "lowest");
  const [day, setDay] = useKept<LongShotsResponse | null>("longshots.day", null);   // shown at once when you come back
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    api<LongShotsResponse>(`/api/long-shots${date ? `?date=${encodeURIComponent(date)}` : ""}`)
      .then((r) => { if (current) { setDay(r); setError(""); } })
      .catch((e) => current && setError(messageOf(e)));
    return () => { current = false; };
  }, [date]);

  const lines = (day?.lines.filter((x) => kind === "all" || (kind === "standard" ? !x.line_type : x.line_type === kind)) ?? [])
    .sort((a, b) => (order === "lowest" ? a.chance - b.chance : b.chance - a.chance));
  const long = lines.filter((x) => x.chance < LONG_SHOT).length;
  return (
    <section>
      <div className="card">
        <div className="row between wrap">
          <h2>Long shots that hit</h2>
          <select aria-label="Game day" value={day?.date ?? ""} onChange={(e) => setDate(e.target.value)}>
            {day?.days.map((d) => <option key={d} value={d}>{dayName(d)}</option>)}
          </select>
        </div>
        <p className="muted small">Every line you pasted or checked, on the side that won, sorted by the model's chance
          before tip-off. Goblins and Demons count only when they went over, since More is the only way to play them.</p>
        <div className="row wrap gap">
          <Seg small label="Which lines" value={kind} onChange={setKind} options={[
            { value: "all", label: "All" }, { value: "demon", label: "Demons" },
            { value: "goblin", label: "Goblins" }, { value: "standard", label: "Standard" },
          ]} />
          <Seg small label="Sort by the model's chance" value={order} onChange={setOrder} options={[
            { value: "lowest", label: "Lowest chance first" }, { value: "highest", label: "Highest chance first" },
          ]} />
          <span className="muted small">
            {lines.length ? `${plural(long, "long shot")} hit (model under ${LONG_SHOT * 100}%) · ${plural(lines.length, "winning line")} in all` : ""}
          </span>
        </div>
        <div id="longShotList">
          {error ? <div className="error">{error}</div>
            : !day ? null
            : !day.date ? <div className="empty">Nothing graded yet. Lines you paste or check are graded once their games finish.</div>
            : lines.length ? <ShowInSteps key={`${day.date}-${kind}-${order}`} items={lines} render={(x, i) => <LongShotRow x={x} rank={i + 1} />} />
            : <div className="empty">None of these hit on {dayName(day.date)}.</div>}
        </div>
      </div>
    </section>
  );
}

/** One line that hit: who, the line and the side that won, the model's chance of it, and his real number. */
function LongShotRow({ x, rank }: { x: LongShot; rank: number }) {
  const by = Math.round(Math.abs(x.actual - x.line) * 10) / 10;
  return (
    <div className="lsrow">
      <div className="rank">{rank}</div>
      <div className="ls-who"><b>{x.player}</b> <span className="muted small">{x.team} – {x.opp}</span>
        <div className="small">{x.stat} <b>{x.line}</b> <LineTypeBadge lineType={x.line_type} />
          {x.played && <> <span className="badge played">you played it</span></>}</div></div>
      <div className={`bpick ${x.side}`}>{x.side === "more" ? "MORE" : "LESS"}</div>
      <div className="ls-num ls-chance"><b>{pct(x.chance)}</b><div className="small muted">model's chance</div></div>
      <div className="ls-num ls-actual"><b>{x.actual}</b><div className="small muted">{x.side === "more" ? "over" : "under"} by {by}</div></div>
    </div>
  );
}
