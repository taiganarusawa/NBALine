// Pull down at the top of the page to refresh, like a phone app. Phones only do this themselves inside
// the browser, not for a page added to the home screen, so the page does it: drag down from the top,
// release past the mark, and `onRefresh` runs while a small "Refreshing…" pill shows. Touch only.
import { useEffect, useRef, useState } from "react";

const TRIGGER = 64;    // how far to pull (after resistance) before letting go refreshes
const MAX_PULL = 96;   // the pill stops following the finger here
const RESISTANCE = 0.5;   // the pill moves half as far as the finger, like a native pull

export default function PullToRefresh({ onRefresh }: { onRefresh: () => Promise<unknown> }) {
  const [pull, setPull] = useState(0);
  const [busy, setBusy] = useState(false);
  const refresh = useRef(onRefresh);   // the latest callback, without re-subscribing to touches
  refresh.current = onRefresh;

  useEffect(() => {
    let startY: number | null = null, pulled = 0, running = false;
    const onStart = (e: TouchEvent) => {
      startY = window.scrollY <= 0 && !running && e.touches.length === 1 ? e.touches[0].clientY : null;
    };
    const onMove = (e: TouchEvent) => {
      if (startY == null) return;
      const dy = e.touches[0].clientY - startY;
      if (dy <= 0 || window.scrollY > 0) { pulled = 0; setPull(0); return; }   // scrolling the page, not pulling
      e.preventDefault();   // the pull, not the page bouncing
      pulled = Math.min(dy * RESISTANCE, MAX_PULL);
      setPull(pulled);
    };
    const onEnd = async () => {
      if (startY == null) return;
      startY = null;
      const far = pulled >= TRIGGER;
      pulled = 0;
      setPull(0);
      if (!far) return;
      running = true;
      setBusy(true);
      try { await refresh.current(); } finally { running = false; setBusy(false); }
    };
    window.addEventListener("touchstart", onStart, { passive: true });
    window.addEventListener("touchmove", onMove, { passive: false });   // so the pull can stop the bounce
    window.addEventListener("touchend", onEnd);
    window.addEventListener("touchcancel", onEnd);
    return () => {
      window.removeEventListener("touchstart", onStart);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onEnd);
      window.removeEventListener("touchcancel", onEnd);
    };
  }, []);

  if (!pull && !busy) return null;
  const ready = pull >= TRIGGER;
  return (
    <div className="ptr" role="status" style={{ transform: `translate(-50%, ${busy ? 12 : pull - 36}px)` }}>
      <span className={`ptr-icon${busy ? " spin" : ready ? " up" : ""}`} aria-hidden="true">{busy ? "⟳" : "↓"}</span>
      {busy ? "Refreshing…" : ready ? "Release to refresh" : "Pull to refresh"}
    </div>
  );
}
