"use server";

import { get } from "@/lib/api/server";

export type SearchHit = {
  kind: string;
  id: string;
  title: string;
  subtitle: string;
  href: string;
};

/**
 * Backs the ⌘K palette.
 *
 * A Server Action rather than a client fetch, so the palette — which runs on
 * every page — never needs an API token in the browser. Scoping to what the
 * caller may open happens on the backend; this just relays.
 */
export async function searchEverything(term: string): Promise<SearchHit[]> {
  if (term.trim().length < 2) return [];
  try {
    const data = await get<{ results: SearchHit[] }>(
      `/api/admin/search?q=${encodeURIComponent(term.trim())}`,
    );
    return data.results;
  } catch {
    // A failed search must not blow up the shell it is mounted in.
    return [];
  }
}
