import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from '../api/client';

interface PendingCtx {
  /** number of reports waiting for a supervisor, null until known */
  count: number | null;
  refresh: () => void;
}

const PendingContext = createContext<PendingCtx>({ count: null, refresh: () => {} });

const REFRESH_MS = 20_000;

/** Count for the «Очередь на проверку» badge; pages call refresh() after a review. */
export function PendingProvider({ children }: { children: ReactNode }) {
  const [count, setCount] = useState<number | null>(null);

  const refresh = useCallback(() => {
    api.pendingReviews({ limit: 500 }).then(
      (list) => setCount(list.length),
      () => {
        /* keep the last known value; the footer shows API health */
      },
    );
  }, []);

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, REFRESH_MS);
    return () => window.clearInterval(t);
  }, [refresh]);

  const value = useMemo(() => ({ count, refresh }), [count, refresh]);
  return <PendingContext.Provider value={value}>{children}</PendingContext.Provider>;
}

export function usePending(): PendingCtx {
  return useContext(PendingContext);
}
