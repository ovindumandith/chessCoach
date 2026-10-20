import { useCallback, useEffect, useState } from "react";

import { api, errorText, type Taxonomy } from "./api";

/** Load data with explicit loading / error states, plus a reload function. */
export function useLoad<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);

  const reload = useCallback(async () => {
    if (path === null) return;
    setLoading(true);
    setError(null);
    try {
      setData(await api<T>(path));
    } catch (e) {
      setData(null);
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, [path]);

  /** Re-fetch without a loading state or clearing data (for polling). */
  const refresh = useCallback(async () => {
    if (path === null) return;
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload, refresh, setData };
}

let taxonomyCache: Taxonomy | null = null;

export function useTaxonomy(): Taxonomy | null {
  const [tax, setTax] = useState<Taxonomy | null>(taxonomyCache);
  useEffect(() => {
    if (taxonomyCache) return;
    api<Taxonomy>("/taxonomy")
      .then((t) => {
        taxonomyCache = t;
        setTax(t);
      })
      .catch(() => {});
  }, []);
  return tax;
}

/** Call `fn` every `ms` while `active` (e.g. to follow a running analysis). */
export function usePoll(fn: () => void, ms: number, active: boolean) {
  useEffect(() => {
    if (!active) return;
    const t = setInterval(fn, ms);
    return () => clearInterval(t);
  }, [fn, ms, active]);
}
