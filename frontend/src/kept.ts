// State a tab keeps while you visit other tabs (a pasted board, typed lines, results), the way the
// tabs worked before they had their own addresses. It lasts until the page is reloaded.
import { useEffect, useState } from "react";

const kept = new Map<string, unknown>();

/** Like useState, but the value is still there when you come back to the tab. */
export function useKept<T>(key: string, initial: T | (() => T)) {
  const [value, setValue] = useState<T>(() =>
    kept.has(key) ? (kept.get(key) as T) : initial instanceof Function ? initial() : initial);
  useEffect(() => { kept.set(key, value); }, [key, value]);
  return [value, setValue] as const;
}
