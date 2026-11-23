// Checking the server again and again while games are on (live box scores on My entries, Check lines
// and Best lines), so a slept phone, a dropped connection or a server that doesn't answer can't stop it.

/** How often a page with a game on asks for its live state. */
export const LIVE_EVERY = 15_000;

/** A live request that hasn't answered by then is dropped and asked again: the server waits at most
 *  8 seconds for NBA.com and 10 for ESPN (nbaline/pickem/live.py, espn.py), so this means the request
 *  itself got lost. */
export const GIVE_UP_AFTER = 25_000;

/** Runs `check` now, then again after the delay it returns (null: stop), until `stop()`. A check that
 *  throws (no answer, or an error) is tried again after `retryMs`. Coming back to the tab checks at
 *  once, since a phone pauses a page's timers while it's in the background. Only one check runs at a
 *  time; `now()` checks at once (or waits for the one already running). */
export function keepChecking(check: () => Promise<number | null>, retryMs: number) {
  let timer: number | undefined, running: Promise<void> | null = null, stopped = false;

  function now(): Promise<void> {
    if (stopped) return Promise.resolve();
    if (running) return running;
    clearTimeout(timer);
    running = (async () => {
      let next: number | null;
      try {
        next = await check();
      } catch {
        next = retryMs;
      }
      running = null;
      if (!stopped && next != null) timer = window.setTimeout(now, next);
    })();
    return running;
  }

  const onShow = () => { if (document.visibilityState === "visible") now(); };
  document.addEventListener("visibilitychange", onShow);
  now();
  return {
    now,
    stop() {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onShow);
    },
  };
}
