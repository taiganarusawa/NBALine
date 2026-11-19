// A group of buttons where exactly one is selected (Power/Flex, More/Less, List/Grid).
import type { ReactNode } from "react";

export interface SegOption<T extends string> {
  value: T;
  label: ReactNode;
  disabled?: boolean;
  title?: string;
}

interface Props<T extends string> {
  options: SegOption<T>[];
  value: T;
  onChange: (value: T) => void;
  small?: boolean;
  label?: string;
}

export default function Seg<T extends string>({ options, value, onChange, small, label }: Props<T>) {
  return (
    <div className={`seg${small ? " small" : ""}`} role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} className={o.value === value ? "on" : ""} disabled={o.disabled} title={o.title}
          aria-pressed={o.value === value} onClick={() => o.value !== value && onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
