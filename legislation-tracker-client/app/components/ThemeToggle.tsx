"use client";

import { useLayoutEffect, useState } from "react";
import { THEME_STORAGE_KEY } from "@/lib/theme";

export default function ThemeToggle() {
  const [isDark, setIsDark] = useState(false);

  useLayoutEffect(() => {
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const nextDark = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", nextDark);
    localStorage.setItem(THEME_STORAGE_KEY, nextDark ? "dark" : "light");
    setIsDark(nextDark);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className="rounded border border-control bg-wash px-2.5 py-1 text-xs font-sans text-ink hover:bg-wash"
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      {isDark ? "Light mode" : "Dark mode"}
    </button>
  );
}
