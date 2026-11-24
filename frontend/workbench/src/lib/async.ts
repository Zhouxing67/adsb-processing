/** Run an async worker over items with a bounded concurrency limit and optional AbortSignal. */
export async function runWithConcurrency<T>(
  items: readonly T[],
  concurrency: number,
  worker: (item: T, index: number) => Promise<void>,
  signal?: AbortSignal,
): Promise<void> {
  if (!items.length || signal?.aborted) return;
  let cursor = 0;
  const count = Math.max(1, Math.min(concurrency, items.length));
  const runWorker = async () => {
    while (cursor < items.length && !signal?.aborted) {
      const index = cursor++;
      await worker(items[index], index);
    }
  };
  await Promise.all(Array.from({ length: count }, runWorker));
}
