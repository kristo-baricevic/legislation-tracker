"use client";
import React, { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import styles from "./card-tooltip.module.css";

export default function CardTooltip({ text, children }: { text: string; children: React.ReactElement<{ "aria-describedby"?: string }> }) {
  const id = useId();
  const trigger = useRef<HTMLSpanElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const cancel = () => { if (timer.current) clearTimeout(timer.current); };
  const close = () => { cancel(); setPosition(null); };
  const open = () => {
    cancel();
    const rect = trigger.current?.getBoundingClientRect();
    if (rect) setPosition({ left: Math.max(12, Math.min(rect.left, window.innerWidth - Math.min(280, window.innerWidth - 24) - 12)), top: rect.top });
  };
  const leave = () => { cancel(); timer.current = setTimeout(close, 120); };
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  useEffect(() => {
    if (!position) return;
    const dismiss = () => setPosition(null);
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); dismiss(); } };
    window.addEventListener("scroll", dismiss, true);
    window.addEventListener("resize", dismiss);
    document.addEventListener("keydown", key);
    return () => { window.removeEventListener("scroll", dismiss, true); window.removeEventListener("resize", dismiss); document.removeEventListener("keydown", key); };
  }, [position]);
  return <span ref={trigger} className={styles.trigger} onMouseEnter={open} onMouseLeave={leave} onFocus={open} onBlur={close}>
    {React.cloneElement(children, { "aria-describedby": [children.props["aria-describedby"], position ? id : ""].filter(Boolean).join(" ") || undefined })}
    {position && createPortal(<span id={id} role="tooltip" className={styles.tooltip} style={{ left: position.left, top: position.top < 160 ? position.top + (trigger.current?.offsetHeight ?? 32) + 8 : position.top - 8, transform: position.top < 160 ? undefined : "translateY(-100%)" }} onMouseEnter={cancel} onMouseLeave={leave}>{text}</span>, trigger.current?.closest("dialog") ?? document.body)}
  </span>;
}
