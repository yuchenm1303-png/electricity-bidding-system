/** Coalesce requests without overlapping screenshots or polling behind input. */
export function createFramePump({ capture, blocked, schedule, cancel, onError,
  interval = 1200, settle = 40,
}: {
  capture: () => Promise<void>;
  blocked: () => boolean;
  schedule: (callback: () => void, delay: number) => number;
  cancel: (timer: number) => void;
  onError: (error: unknown) => void;
  interval?: number;
  settle?: number;
}) {
  let stopped = false;
  let running = false;
  let requested = false;
  let timer: number | undefined;

  function arm(delay: number) {
    if (timer !== undefined) cancel(timer);
    timer = schedule(() => { timer = undefined; void run(); }, delay);
  }

  async function run() {
    if (stopped || running) return;
    if (blocked()) { arm(interval); return; }
    running = true;
    requested = false;
    try { await capture(); }
    catch (error) { if (!stopped) onError(error); }
    finally {
      running = false;
      if (!stopped) arm(requested ? settle : interval);
    }
  }

  return {
    request() {
      if (stopped) return;
      requested = true;
      if (!running) arm(settle);
    },
    stop() {
      stopped = true;
      if (timer !== undefined) cancel(timer);
    },
  };
}
