import { useCallback, useEffect, useState, type DependencyList } from 'react';
import { errorText } from '../api/client';

export interface AsyncState<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Run an async loader when deps change; keeps the previous data while reloading. */
export function useAsync<T>(fn: () => Promise<T>, deps: DependencyList): AsyncState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fn().then(
      (d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
        setLoading(false);
      },
      (e: unknown) => {
        if (cancelled) return;
        setError(errorText(e));
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
    // deps are the caller's; `fn` is recreated on every render and intentionally not a dependency
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/** Call `fn` every `ms` while `enabled`. */
export function useInterval(fn: () => void, ms: number, enabled = true): void {
  useEffect(() => {
    if (!enabled) return;
    const t = window.setInterval(fn, ms);
    return () => window.clearInterval(t);
  }, [fn, ms, enabled]);
}
