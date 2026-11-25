"use client";

import { useCallback, useState } from "react";
import { representativeInitials } from "@/lib/representative-name";
import styles from "./avatar-portrait.module.css";

export default function AvatarPortrait({ name, photo, lazy = false }: {
  name: string; photo?: string | null; lazy?: boolean;
}) {
  const [loaded, setLoaded] = useState("");
  const [failed, setFailed] = useState("");
  const ready = Boolean(photo && loaded === photo && failed !== photo);
  const checkCached = useCallback((image: HTMLImageElement | null) => {
    if (photo && image?.complete && image.naturalWidth > 0) setLoaded(photo);
  }, [photo]);

  return <span className={styles.frame}>
    {!ready && <span aria-hidden="true" className={styles.initials}>{representativeInitials(name)}</span>}
    {photo && failed !== photo && <img ref={checkCached} src={photo} alt={name}
      loading={lazy ? "lazy" : undefined} style={{ opacity: ready ? 1 : 0 }}
      onLoad={() => setLoaded(photo)} onError={() => setFailed(photo)} />}
  </span>;
}
