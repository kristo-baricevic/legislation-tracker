import { useRef, useState } from "react";

// A save owns only its card. Other cards can finish in any order.
export function usePendingCards() {
  const requests = useRef(new Set<number>());
  const [pending, setPending] = useState<ReadonlySet<number>>(new Set());
  function begin(id: number) {
    if (requests.current.has(id)) return;
    requests.current.add(id);
    setPending(new Set(requests.current));
    return () => {
      requests.current.delete(id);
      setPending(new Set(requests.current));
    };
  }
  return { pending, begin };
}
