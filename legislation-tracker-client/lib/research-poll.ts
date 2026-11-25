import { getResearch, type Research } from "./representative-research";
import { dashboardValue } from "./dashboard-cache";

type Listener = { value: (data: Research) => void; error: (e: unknown) => void };
type Entry = { listeners: Set<Listener>; stop: () => void; latest?: Research };
const entries = new Map<string, Entry>();

export function watchResearch(id: number, period: number, dashboard: boolean, listener: Listener) {
  const key = `rep:${id}:research:${period}`;
  let entry = entries.get(key);
  if (!entry) {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const listeners = new Set<Listener>();
    const current: Entry = { listeners, stop() { controller.abort(); clearTimeout(timer); } };
    const load = async () => {
      try {
        const result = dashboard
          ? await dashboardValue(key, () => getResearch(id, period), value => !["queued", "running"].includes(value.status))
          : await getResearch(id, period, controller.signal);
        if (controller.signal.aborted) return;
        current.latest = result;
        listeners.forEach(sub => sub.value(result));
        if (["queued", "running"].includes(result.status)) timer = setTimeout(load, 2500);
      } catch (error) {
        if (controller.signal.aborted) return;
        listeners.forEach(sub => sub.error(error));
        timer = setTimeout(load, 5000);
      }
    };
    entry = current;
    entries.set(key, current);
    void load();
  }
  entry.listeners.add(listener);
  if (entry.latest) listener.value(entry.latest);
  return () => {
    entry.listeners.delete(listener);
    if (!entry.listeners.size) { entry.stop(); entries.delete(key); }
  };
}
