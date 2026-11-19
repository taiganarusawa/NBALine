// The details behind one line, shared by Check lines (every card) and Best lines (a row's dropdown):
// what the model expects, who's in and who's out, his last games, and why the model thinks this.
import type { ReactNode } from "react";
import { pct } from "../format";
import { statusTip, TIPS, tipProps } from "../labels";
import type { LineResult } from "../types";

/** What the model expects: average, median and range, or for a yes/no stat (double-double) its chance. */
export function Projection({ r }: { r: LineResult }) {
  if (r.yes_no) {
    const what = r.stat.replace(/s$/, "").toLowerCase().replace(" ", "-");   // "Double Doubles" -> "double-double"
    return <>Chance of a {what}: <b>{pct(r.p_over)}</b></>;
  }
  return (
    <>
      <span className="hint" {...tipProps(TIPS.median)}>Average <b>{r.proj}</b> · median <b>{r.q50}</b></span>
      {" "}· typical range <TypicalRange r={r} />
    </>
  );
}

/** The range he usually lands in ("6–22"), plus how likely he lands exactly on a whole-number line
 *  (a push: the pick is removed). */
export function TypicalRange({ r }: { r: LineResult }) {
  return (
    <>
      {Math.round(r.q10 ?? 0)}–{Math.round(r.q90 ?? 0)}
      {(r.p_push ?? 0) >= 0.005 && <> · <span className="hint" {...tipProps(TIPS.push)}>exactly {r.line}: {pct(r.p_push)}</span></>}
    </>
  );
}

/** Who's in and who's out: where the information comes from, then one tidy row per team's absences
 *  and one per injury status (Questionable, Probable), each name with its details on hover. */
export function Injuries({ r }: { r: LineResult }) {
  const rows: [label: string, value: ReactNode, look?: string][] = [];
  if (r.self_status) rows.push(["Status", <span className="w" {...tipProps(statusTip(r.self_status))}>{r.self_status}</span>]);
  rows.push(["Tonight", <Role r={r} />]);
  for (const [team, names] of Object.entries(r.outs || {})) {
    rows.push([`${team} out`, joined(names.map((n) => <OutName text={n} />))]);
  }
  const byStatus: Record<string, ReactNode[]> = {};
  for (const q of r.questionable || []) {
    const m = q.match(/^(.+) \(([A-Z]{2,4})\) (\w+): (.*)$/);   // "Name (TOR) Questionable: Injury/Illness - Illness"
    const status = m ? m[3] : "Questionable";
    (byStatus[status] ||= []).push(<span {...tipProps(statusTip(q))}>{m ? <>{m[1]} <span className="muted">{m[2]}</span></> : q}</span>);
  }
  for (const [status, names] of Object.entries(byStatus)) rows.push([status, joined(names), "w"]);

  return (
    <div className="inj">
      <div className="inj-src">
        {r.injury_report ? (
          <>
            Injury report · <b>{r.injury_report}</b>
            {!!r.injury_notes?.length && <> <span className="muted">({r.injury_notes.join("; ")})</span></>}
            {!!r.injury_missing?.length && <> · <span className="w">not submitted yet: {r.injury_missing.join(", ")}</span></>}
          </>
        ) : (
          <><span className="w" {...tipProps(TIPS.injuriesGuessed)}>No injury report yet</span> · absences guessed from recent games</>
        )}
      </div>
      {rows.length ? (
        <div className="inj-rows">
          {rows.map(([label, value, look = ""]) => (
            <span key={label} style={{ display: "contents" }}>
              <span className={`inj-k ${look}`}>{label}</span><span className="inj-v">{value}</span>
            </span>
          ))}
        </div>
      ) : null}
      {!rows.some(([label]) => label.endsWith(" out")) && <div className="muted small">Nobody in either rotation is listed out.</div>}
    </div>
  );
}

/** His role tonight from NBA.com's lineups ("Starting · confirmed"), against how often he's started
 *  lately, or that the lineup isn't posted yet. */
function Role({ r }: { r: LineResult }) {
  const usually = r.start_rate == null ? "" : `started ${Math.round(r.start_rate * 10)} of his last 10`;
  if (!r.lineup) {
    return <span className="muted" {...tipProps(TIPS.lineup)}>lineup not posted yet{usually && ` · ${usually}`}</span>;
  }
  if (r.lineup.inactive) return <span className="bad-text" {...tipProps(TIPS.inactive)}>Inactive (not playing)</span>;
  return (
    <span {...tipProps(TIPS.lineup)}>
      {r.lineup.starting ? "Starting" : "Off the bench"} <span className="muted">· {r.lineup.status.toLowerCase()}
        {usually && ` · ${usually}`}</span>
    </span>
  );
}

/** Items with ", " between them. */
const joined = (items: ReactNode[]) => items.map((item, i) => <span key={i}>{i > 0 && ", "}{item}</span>);

/** "Chet Holmgren (10 FGA/g)" -> the name, with his usual shots a game on hover */
function OutName({ text }: { text: string }) {
  const m = text.match(/^(.+) \((\d+) FGA\/g\)$/);
  return m ? <span title={`Usually takes ${m[2]} shots a game`}>{m[1]}</span> : <>{text}</>;
}

/** His last games as chips: green above the line, red below. */
export function RecentGames({ r }: { r: LineResult }) {
  return (
    <div className="chips">
      <span className="muted small">Last games:</span>
      {(r.history?.recent || []).map(([date, value], i) => (
        <span key={i} className={`chip ${value > r.line ? "o" : "u"}`} title={date}>{value}</span>
      ))}
    </div>
  );
}

/** The biggest factors behind the prediction (from the model's own explanation): how much each one
 *  adds to the projection, or to the chance (in % points) for a yes/no stat. Nothing if there are none. */
export function ReasonList({ r }: { r: LineResult }) {
  if (!r.reasons?.length) return null;
  const unit = r.yes_no ? "%" : "";
  return (
    <ul className="reasons">
      {r.reasons.map(([effect, label, value], i) => (
        <li key={i}><b>{effect > 0 ? "+" : ""}{effect}{unit}</b>{label} = {value}</li>
      ))}
    </ul>
  );
}
