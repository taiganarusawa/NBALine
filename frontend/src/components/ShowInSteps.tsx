// A long list shown 10 at a time, so the page never grows by hundreds of rows at once: the first 10,
// then "Show 10 more" adds the next ones and "Show fewer" folds it back to the first 10.
// To start a new list from the top again, give the component a new `key`.
import { Fragment, useRef, useState, type Key, type ReactNode } from "react";

interface Props<T> {
  items: T[];
  render: (item: T, index: number) => ReactNode;
  step?: number;
  /** Each item's own key (default: its place), so a row that keeps state stays with its item when the list changes. */
  keyOf?: (item: T) => Key;
}

export default function ShowInSteps<T>({ items, render, step = 10, keyOf }: Props<T>) {
  const [shown, setShown] = useState(step);
  const controls = useRef<HTMLDivElement>(null);
  const left = Math.max(items.length - shown, 0);

  function showFewer() {
    setShown(step);
    requestAnimationFrame(() => controls.current?.scrollIntoView({ block: "nearest" }));   // stay at the list
  }

  return (
    <>
      <div>{items.slice(0, shown).map((item, i) => <Fragment key={keyOf ? keyOf(item) : i}>{render(item, i)}</Fragment>)}</div>
      <div className="more-row" ref={controls}>
        {left > 0 && (
          <button className="ghost small" onClick={() => setShown(shown + step)}>
            Show {Math.min(step, left)} more <span className="muted">· {left} left</span>
          </button>
        )}
        {shown > step && items.length > step && <button className="ghost small" onClick={showFewer}>Show fewer</button>}
      </div>
    </>
  );
}
