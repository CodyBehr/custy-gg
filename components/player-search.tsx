"use client";

// Search box in the header. Suggests Riot IDs as you type; picking one goes
// straight to that profile, anything else goes to the search results page.

import { useRouter } from "next/navigation";
import { useId, useState } from "react";

export interface SearchOption { puuid: string; label: string }

export function PlayerSearch({ options, autoFocus, defaultValue = "", big }: {
  options: SearchOption[];
  autoFocus?: boolean;
  defaultValue?: string;
  big?: boolean;
}) {
  const router = useRouter();
  const listId = useId();
  const [value, setValue] = useState(defaultValue);

  const go = (text: string) => {
    const q = text.trim();
    if (!q) return;
    const exact = options.find((o) => o.label.toLowerCase() === q.toLowerCase());
    router.push(exact ? `/players/${encodeURIComponent(exact.puuid)}` : `/players?q=${encodeURIComponent(q)}`);
  };

  return (
    <form
      className={`psearch${big ? " big" : ""}`}
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        go(value);
      }}
    >
      <input
        type="search"
        name="q"
        placeholder={big ? "Riot ID, e.g. Mayo#mayo" : "Search players"}
        aria-label="Search players by Riot ID"
        list={listId}
        value={value}
        autoFocus={autoFocus}
        autoComplete="off"
        onChange={(e) => {
          const v = e.target.value;
          setValue(v);
          // Choosing a suggestion fills the box with an exact Riot ID: jump right away.
          const native = e.nativeEvent as InputEvent;
          if (!native.inputType || native.inputType === "insertReplacementText") {
            const exact = options.find((o) => o.label === v);
            if (exact) router.push(`/players/${encodeURIComponent(exact.puuid)}`);
          }
        }}
      />
      <datalist id={listId}>
        {options.map((o) => <option key={`${o.puuid}:${o.label}`} value={o.label} />)}
      </datalist>
      <button type="submit" aria-label="Search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden>
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
      </button>
    </form>
  );
}
