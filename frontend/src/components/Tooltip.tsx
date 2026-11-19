// One floating box that shows the data-tip text of whatever is hovered or focused, anywhere on the page.
import { useEffect, useRef, useState } from "react";

export default function Tooltip() {
  const box = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<{ text: string; target: DOMRect } | null>(null);

  useEffect(() => {
    const tipOf = (e: Event) => (e.target as Element | null)?.closest?.("[data-tip]") as HTMLElement | null;
    const show = (e: Event) => {
      const el = tipOf(e);
      if (el?.dataset.tip) setTip({ text: el.dataset.tip, target: el.getBoundingClientRect() });
    };
    const hide = (e: Event) => { if (tipOf(e)) setTip(null); };
    const hideNow = () => setTip(null);
    const events: [string, EventListener][] = [["mouseover", show], ["focusin", show], ["mouseout", hide], ["focusout", hide]];
    for (const [name, fn] of events) document.addEventListener(name, fn);
    window.addEventListener("scroll", hideNow, true);
    return () => {
      for (const [name, fn] of events) document.removeEventListener(name, fn);
      window.removeEventListener("scroll", hideNow, true);
    };
  }, []);

  // placed once its size is known: below the element, or above it when there's no room below
  useEffect(() => {
    const el = box.current;
    if (!el || !tip) return;
    const size = el.getBoundingClientRect(), target = tip.target;
    const fitsBelow = target.bottom + 6 + size.height < window.innerHeight;
    el.style.left = `${Math.min(Math.max(8, target.left), window.innerWidth - size.width - 8)}px`;
    el.style.top = `${fitsBelow ? target.bottom + 6 : target.top - size.height - 6}px`;
  }, [tip]);

  return <div id="tip" ref={box} role="tooltip" className={tip ? "" : "hidden"}>{tip?.text}</div>;
}
