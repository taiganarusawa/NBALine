// Numbers and dates as the page shows them.

/** 0.5423 -> "54.2%" ("—" when missing). */
export const pct = (p: number | null | undefined) => (p == null ? "—" : `${(p * 100).toFixed(1)}%`);

/** -3.5 -> "-$3.50" */
export const money = (x: number) => `${x < 0 ? "-" : ""}$${Math.abs(x).toFixed(2)}`;

/** 125 -> "2m 5s" */
export const duration = (seconds: number) =>
  seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`;

/** plural(1, "day") -> "1 day", plural(3, "entry", "entries") -> "3 entries" */
export const plural = (n: number, word: string, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;

/** "2026-11-10" -> "Tue, Nov 10" */
export const dayName = (d: string) =>
  new Date(`${d}T12:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });

/** "2026-11-10" -> "11/10" */
export const shortDay = (d: string) =>
  new Date(`${d}T12:00`).toLocaleDateString(undefined, { month: "numeric", day: "numeric" });
