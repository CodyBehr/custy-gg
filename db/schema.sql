-- custy.gg database schema.
-- The site creates this table by itself the first time it connects, so you
-- only need to run this by hand if you want to (Supabase > SQL editor).

create table if not exists matches (
  id           text primary key,            -- "<platformId>-<gameId>", e.g. "NA1-5123456789"
  played_at    timestamptz not null,        -- when the game started
  summary      jsonb not null,              -- cleaned-up match the website reads
  raw          jsonb not null,              -- the full game exactly as the League client returned it
  uploaded_by  text,                        -- Riot ID of whoever's collector sent it first
  inserted_at  timestamptz not null default now()
);

create index if not exists matches_played_at_idx on matches (played_at desc);
