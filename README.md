# custy.gg

An op.gg-style stats site for League of Legends custom games with your friends.

Riot's API doesn't return custom games, so a small collector script runs on your
computers instead. It reads finished custom games from the League client's local
match history and sends them to your site. Only one person who played a game
needs to be running it; duplicates are ignored.

```
League client  ──>  collector (Python, runs in background)  ──>  your site (Vercel)  ──>  database (Supabase)
```

What the site shows:

- **Standings**: everyone ranked by an Elo-style rating, with win rate, KDA, last 10 games and most played champions
- **Player lookup**: search anyone by Riot ID from the header, or browse a sortable table of every player
- **Player pages**: op.gg-style profile with a last-20-games summary, match history you can filter by champion or role and expand into the full scoreboard, a full champion table, multikills, rating graph, roles, best duos and toughest opponents
- **Match pages**: full scoreboard with items, runes, damage, gold, CS, vision, bans and an MVP, plus (from the
  game's timeline, app 1.5+) a gold lead graph with objectives, a kill map, and CS/gold at 10 and 15 vs. lane opponent
- **Champions**: what your group picks and bans, and who's best on each
- **Records**: most kills, most damage, longest game, pentakills and more

Everything is free: Supabase and Vercel's free tiers are plenty for a friend group.

---

## Adding your games

Live site: **https://custy-gg.vercel.app**

**Windows (one click):** open the site's **Add your games** page and download `custy-collector.exe`. Double-click it.
If Windows shows "Windows protected your PC", click *More info* then *Run anyway* (it isn't code-signed). It installs
itself to `%LOCALAPPDATA%\custy-collector`, starts with Windows and runs in the background. Run the download again
to update (Yes) or remove (No) it. Its log is `%LOCALAPPDATA%\custy-collector\collector.log`.

**Mac, or with Python:** download `custy-collector.zip` from the same page, install Python 3, then run
`bash mac-autostart-on.sh` (Mac) or `windows-autostart-on.bat` (Windows) from the unzipped folder.

On its first run the collector uploads every custom game still in your client's recent history.

### How the Windows app is built

`.github/workflows/build-collector.yml` runs on GitHub's Windows machines whenever `collector/custy_collector.py`
or `collector/windows_app.py` changes. It packs the collector into one `.exe` with PyInstaller, checks it starts,
and commits it to `collector-dist/`. The site's `/api/collector/windows` route serves that file with this site's
address and upload key attached to the end, where the app reads them.

## Discord bot

The site answers Discord slash commands itself at `/api/discord` (no separate bot to host):

- `/custy_teams` splits the current custom lobby into two teams. `balance`: custy rating (default), solo queue
  rank, or random. Also `players` (use a list instead of the lobby), `together`, `apart`, `add`, `remove`.
  A **Reroll** button gives another fair split with the same rules.
- `/custy_lobby` shows who's in the custom lobby, with custy ratings and solo queue ranks.
- `/custy_player` shows someone's custom-game stats and solo queue rank.

Solo queue ranks come from the League client: the app reads them for everyone in your lobby and in each game it
uploads, so no Riot API key is needed. Balancing is plain math, not AI: it tries every possible split, keeps
the ones closest to even (and that follow the together/apart rules), and picks one of those at random.

- **Link my account**: a button under each team split lets people pick which League player they are. Linked
  people get pinged in team splits and shown as @mentions (without pings) in game posts, drafts and recaps;
  `/custy_player @someone` works too.
- **Captain draft**: the button under a team split lets two random captains pick teams, snake order.
- **Predictions**: Blue wins / Red wins buttons under every team split (open for 15 minutes). When the game
  uploads, right calls earn 100 × (all votes ÷ votes for the winner), so calling the upset pays more.
  The 🏆 Leaderboard button shows the standings. Fake points, bragging rights only.
- **Game posts**: every newly uploaded game is posted to a channel (result, MVP, KDA, rating changes, pentas).
  Connect a channel on `/discord` by pasting the channel's webhook link.
- **Weekly recap**: every Monday around 8 AM Eastern (Vercel cron in `vercel.json`, `/api/cron/weekly`) the channel
  gets last week's games: climbers, awards, big moments, duo of the week, most picked/banned and the top 5.

Setup is on the site's `/discord` page.

## The Windows app updates itself

Every 15 minutes (never during a game) the app asks the site for its latest version
(`/api/collector/version`, read from the built .exe) and installs it quietly if it's newer. Turn this off from
the tray menu ("Update automatically").

## Game review (test)

The Windows app also has a **Review my games (test)** window: right-click the tray icon, or open *custy.gg game
review* from the Start menu. It reviews your recent ranked, normal and quickplay games on Summoner's Rift (not
customs):

- your lane gold difference by minute against your lane opponent, with the middle half of your own recent games
  in the same role behind it (same champion once you have 3+ games on it)
- up to 5 moments to watch: gold swings of 400+, deaths before 14:00, CS, first back, boots, first item, level 6
  and plates, with what happened around each one
- **Watch in my replay** downloads the replay through the League client, starts it and jumps to the moment.
  Jumping needs League's Replay API on; the page offers to add `EnableReplayApi=1` to `Config/game.cfg` (it keeps
  `game.cfg.custy-backup`). Replays only open for games on the current patch.

Everything stays on your PC: games are read from the League client and kept in
`%LOCALAPPDATA%\custy-collector\review-cache`, so the comparison improves as you play with the app running.
Without the Windows app: `python collector/custy_collector.py --review`. To try it without League, run
`MOCK_RANKED=1 MOCK_REPLAY_API=1 python scripts/mock_lcu.py some-folder` first.

## Agent API

Read-only JSON for AI agents (like a Discord bot) at `/api/agent`; that address lists every endpoint. The main one is
`/api/agent/player?name=<name>`: a full analysis of one player (stats vs. the group for their roles, strengths and
weaknesses, form, champion pool, teammates, opponents, early game and where they die). Set `AGENT_API_KEY` in Vercel
to require `Authorization: Bearer <key>`.

## How it's hosted

- **Vercel** (free Hobby plan) runs the site and redeploys automatically whenever `main` changes on GitHub.
- **Supabase** (free plan, connected through Vercel's Storage tab) is the database. Vercel provides
  `POSTGRES_URL`; the site creates its tables on first use.
- The upload key is generated by the site and stored in the database. To use your own instead, set
  `INGEST_KEY` in Vercel (then re-download the collector).

Optional Vercel environment variables:

| Name | What it does |
| --- | --- |
| `SITE_PASSWORD` | asks visitors for a group password before showing anything |
| `NEXT_PUBLIC_GROUP_NAME` | name in the header, e.g. `Rift Night.gg` |
| `NEXT_PUBLIC_TIMEZONE` | defaults to `America/New_York` |

## Good to know

- **Roles come from the role quest slot.** Each player's role quest item names the role the game gave them. When
  it's missing (older games, odd setups), the site falls back to Smite, lane and CS.
- **Remakes** (games under 5 minutes) are listed but don't count toward any stats.
- **Ratings** start at 1500. A win against a stronger team earns more than a win against a weaker one. Fine
  for fun among friends; it isn't connected to your real rank.
- **League installed somewhere unusual?** The collector finds the client automatically. If `windows-test.bat`
  can't, put your League folder (the one containing `LeagueClient.exe`) in `league_path` in `config.json`.
  Use double backslashes: `"D:\\Games\\Riot Games\\League of Legends"`.
- **The League client's local API isn't officially supported by Riot.** It's what tools like Porofessor and Blitz
  use, and it's read-only here, but a client patch could change it. If uploads stop after a patch, check
  `collector.log`.

## Trying it on your own computer first

You don't need Supabase to look around. With Node.js 20+ installed:

```bash
npm install
INGEST_KEY=test npm run dev            # Windows PowerShell: $env:INGEST_KEY="test"; npm run dev
python scripts/make_sample_games.py --post http://localhost:3000 test
```

Open http://localhost:3000. Without `DATABASE_URL`, games are saved to `data/matches.json`.
The sample players and games are made up. To test the collector without League, run
`python scripts/mock_lcu.py some-folder` and set `"league_path": "some-folder"` in `config.json`.

To clear sample data from a real database, run `delete from matches;` in the Supabase SQL editor.

## Project layout

```
app/                    the website (Next.js)
  api/ingest/           where the collector sends games
  page.tsx              standings
  players/ matches/ champions/ records/
lib/
  normalize.ts          turns the League client's game data into what the site uses
  stats.ts              ratings, MVPs, records, duos: every number on the site
  store.ts              Postgres (or a local JSON file)
  ddragon.ts            champion names and icons from Riot's Data Dragon
collector/              the Python script your friends run
scripts/                sample data and a pretend League client for testing
```

If you change `lib/normalize.ts` later, rebuild every stored game with:

```bash
curl -X POST https://custy-gg.vercel.app/api/admin/renormalize -H "Authorization: Bearer <ingest_key from the collector's config.json>"
```

---

custy.gg isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially
involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks
or registered trademarks of Riot Games, Inc.
