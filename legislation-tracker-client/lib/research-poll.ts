import { getResearch, type Research } from "./representative-research";

type Listener = { value: (data: Research) => void; error: (e: unknown) => void };

function createPoll(id: number, period: number) {
  const listeners = new Set<Listener>();
  let active: Research | undefined;
  let request: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function cancel() {
    clearTimeout(timer);
    request?.abort();
    request = undefined;
    active = undefined;
  }

  async function load() {
    if (request) return;
    clearTimeout(timer);
    const controller = new AbortController();
    request = controller;
    try {
      const result = await getResearch(id, period, controller.signal);
      if (controller.signal.aborted) return;
      active = ["queued", "running"].includes(result.status) ? result : undefined;
      listeners.forEach(listener => listener.value(result));
      if (active) timer = setTimeout(load, 2500);
    } catch (error) {
      if (controller.signal.aborted) return;
      active = undefined;
      listeners.forEach(listener => listener.error(error));
      timer = setTimeout(load, 5000);
    } finally {
      controller.abort();
      if (request === controller) request = undefined;
    }
  }

  function refresh() { cancel(); void load(); }
  function updated(event: Event) {
    if ((event as CustomEvent<number>).detail === id) refresh();
  }
  window.addEventListener("representative-research-updated", updated);
  return {
    listen(listener: Listener) {
      listeners.add(listener);
      // A running collection already has a scheduled check. A completed
      // collection may have been superseded since another panel last read it.
      if (active) listener.value(active);
      else void load();
    },
    remove(listener: Listener) {
      listeners.delete(listener);
      if (listeners.size) return false;
      cancel();
      window.removeEventListener("representative-research-updated", updated);
      return true;
    },
    refresh,
  };
}

const polls = new Map<string, ReturnType<typeof createPoll>>();

export function refreshResearchPolls() {
  polls.forEach(poll => poll.refresh());
}

export function watchResearch(id: number, period: number, listener: Listener) {
  const key = `${id}:${period}`;
  const poll = polls.get(key) ?? createPoll(id, period);
  polls.set(key, poll);
  poll.listen(listener);
  return () => { if (poll.remove(listener)) polls.delete(key); };
}
