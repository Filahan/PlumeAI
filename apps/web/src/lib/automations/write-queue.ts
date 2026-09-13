/** Serialization for the editor's document writes.
 *
 *  Two overlapping writes would each echo a whole document back, and whichever answered
 *  last would win — which is not necessarily the newest edit. So every write chains
 *  through one queue and carries a stamp taken when it is *issued*: its response may be
 *  adopted only while that stamp is still the newest one.
 *
 *  Module state rather than store state on purpose: none of it belongs in a render.
 */

let writeQueue: Promise<unknown> = Promise.resolve();
let writeStamp = 0;

export function enqueueWrite<T>(task: () => Promise<T>): Promise<T> {
  // `then(task, task)` so one rejected write does not poison the queue behind it.
  const run = writeQueue.then(task, task);
  writeQueue = run.then(
    () => undefined,
    () => undefined
  );
  return run;
}

/** Claim a stamp for a write about to be issued. */
export function nextWriteStamp(): number {
  writeStamp += 1;
  return writeStamp;
}

/** True while no later write has been issued — the condition for adopting a response. */
export function isNewestWrite(stamp: number): boolean {
  return stamp === writeStamp;
}
