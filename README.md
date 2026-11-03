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
- **Player pages**: match history, rating graph, champion stats, roles, best duos and toughest opponents
- **Match pages**: full scoreboard with items, runes, damage, gold, CS, vision, bans and an MVP
- **Champions**: what your group picks and bans, and who's best on each
- **Records**: most kills, most damage, longest game, pentakills and more

Everything is free: Supabase and Vercel's free tiers are plenty for a friend group.

---

## Setup (about 15 minutes, one person does this)

### 1. Make the database

1. Sign up at [supabase.com](https://supabase.com) and create a new project. Save the database password it asks for.
2. Click **Connect** at the top of the project, choose **Transaction pooler**, and copy the connection string.
   It looks like `postgresql://postgres.abcd:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:6543/postgres`.
   Replace `[YOUR-PASSWORD]` with your database password.

That's it. The site creates its table automatically the first time it runs (the SQL is in `db/schema.sql` if you want to see it).

### 2. Put the site online

1. Push this folder to a new GitHub repository (private is fine).
2. Sign up at [vercel.com](https://vercel.com) with GitHub, click **Add New > Project**, and import the repository.
3. Before clicking Deploy, open **Environment Variables** and add:

   | Name | Value |
   | --- | --- |
   | `DATABASE_URL` | the Supabase connection string from step 1 |
   | `INGEST_KEY` | any long random string, e.g. from [this generator](https://www.uuidgenerator.net/) |
   | `SITE_PASSWORD` | optional: a password your group types once to see the site |
   | `NEXT_PUBLIC_GROUP_NAME` | optional: shown in the header, e.g. `Rift Night.gg` |
   | `NEXT_PUBLIC_TIMEZONE` | optional: defaults to `America/New_York` |

4. Click **Deploy**. Your site will be at something like `https://custy-gg.vercel.app`.

### 3. Set up the collector

1. Copy `collector/config.example.json` to `collector/config.json` and fill in:
   ```json
   {
     "site_url": "https://custy-gg.vercel.app",
     "ingest_key": "the same INGEST_KEY you put in Vercel",
     "league_path": "",
     "min_players": 2
   }
   ```
2. Zip the `collector` folder and send it to your friends. Everyone who wants to log games does step 4.

### 4. Each player (Windows)

1. Install Python from [python.org/downloads](https://www.python.org/downloads/). On the first installer screen,
   tick **Add python.exe to PATH**.
2. Unzip the collector folder somewhere permanent, like `Documents\custy-collector`.
3. Open League and log in, then double-click **`windows-test.bat`**. You should see three `[ok]` lines.
4. Double-click **`windows-autostart-on.bat`**. The collector now runs hidden in the background every time
   you log in to Windows. It checks for new custom games every minute and uploads them about 20 seconds
   after a game ends.

To stop it, run `windows-autostart-off.bat`. To watch it work instead, run `windows-start.bat`.
Everything it does is written to `collector.log` in the same folder.

**Mac:** install Python 3, then run `bash mac-autostart-on.sh` in Terminal from the collector folder.

On its first run the collector uploads every custom game still in your client's recent history (the last 50
games of any mode), so your last few game nights show up right away.

---

## Good to know

- **Roles are guessed.** Custom games don't record positions, so the site works them out from Smite, lane and CS.
  Usually right on Summoner's Rift, sometimes wrong.
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
curl -X POST https://your-site/api/admin/renormalize -H "Authorization: Bearer YOUR_INGEST_KEY"
```

---

custy.gg isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially
involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks
or registered trademarks of Riot Games, Inc.
