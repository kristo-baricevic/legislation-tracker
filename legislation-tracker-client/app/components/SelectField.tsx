"use client";

import { useEffect, useId, useRef, useState } from "react";

export interface SelectOption {
  value: string;
  label: string;
}

interface SelectFieldProps {
  label: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  className?: string;
}

export default function SelectField({
  label,
  value,
  options,
  onChange,
  className = "",
}: SelectFieldProps) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const selected = options.find((option) => option.value === value) ?? options[0];

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const selectOption = (nextValue: string) => {
    onChange(nextValue);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className={`relative min-w-0 ${className}`}>
      <label
        id={`${id}-label`}
        className="mb-1 block text-sm text-muted"
      >
        {label}
      </label>
      <button
        id={`${id}-button`}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby={`${id}-label ${id}-button`}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            setOpen(true);
          }
        }}
        className="flex min-h-10 w-full items-center justify-between gap-2 rounded border border-control bg-paper px-2 py-1 text-left text-ink outline-none hover:border-focus focus:border-focus"
      >
        <span className="truncate">{selected?.label ?? ""}</span>
        <span aria-hidden="true" className="shrink-0 text-xs">
          v
        </span>
      </button>
      {open && (
        <div
          role="listbox"
          aria-labelledby={`${id}-label`}
          className="absolute left-0 right-0 top-[calc(100%+0.25rem)] z-50 max-h-64 overflow-y-auto rounded border border-line bg-paper py-1 text-sm shadow-lg"
        >
          {options.map((option) => {
            const isSelected = option.value === value;
            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={isSelected}
                onClick={() => selectOption(option.value)}
                className={`block w-full px-3 py-2 text-left hover:bg-wash  ${
                  isSelected
                    ? "bg-wash font-semibold text-ink  "
                    : "text-ink "
                }`}
              >
                {option.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
