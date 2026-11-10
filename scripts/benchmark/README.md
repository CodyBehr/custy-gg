# Expert benchmarks

The game review (Overview, Moments and Breakdown) reads `public/benchmarks/<Champion>-<ROLE>.json` from the site. There are two
ways to build those files. Both use `bench_core.py` for the per-game numbers and the summary.

```bash
export RIOT_API_KEY=RGAPI-...          # never commit this
V=$(curl -s https://ddragon.leagueoflegends.com/api/versions.json | python3 -c "import json,sys;print(json.load(sys.stdin)[0])")
curl -o scripts/benchmark/item.json https://ddragon.leagueoflegends.com/cdn/$V/data/en_US/item.json
curl -o scripts/benchmark/champion.json https://ddragon.leagueoflegends.com/cdn/$V/data/en_US/champion.json
```

## Every champion: Master+ games

`.github/workflows/benchmarks.yml` does this on GitHub (Actions tab, *Run workflow*). By hand:

```bash
python3 scripts/benchmark/master_pull.py --platform na1 --route americas --out rows-NA --minutes 300
python3 scripts/benchmark/master_build.py rows-NA --out public/benchmarks --min 40
```

Each game gives ten samples (every player in it). Files whose `source` mentions onetricks are left alone.

## One champion: onetricks.gg one-tricks

Player lists come from onetricks.gg's ranking for the champion (`name #tag|REGION`, one per line).

```bash
CHAMP=Jhin POS=BOTTOM PER=8 SCAN=60 PLAYERS=scripts/benchmark/players-jhin-bot.txt \
  python3 scripts/benchmark/pull.py data/benchmark/jhin_bot          # ~5-10 min on a dev key
python3 scripts/benchmark/build_benchmark.py data/benchmark/jhin_bot public/benchmarks
```

## Exploring (not used by the site)

```bash
python3 scripts/benchmark/analyse.py data/benchmark/jhin_bot          # medians printed as JSON
python3 scripts/benchmark/builds.py data/benchmark/jhin_bot 3036      # build order; 3036 = Lord Dominik's Regards
python3 scripts/benchmark/mine.py Ringo 1432 Jhin                     # someone's latest game on that champion
python3 scripts/benchmark/compare.py data/benchmark/jhin_bot data/benchmark/mine/<match>.json "$(cat data/benchmark/Ringo.puuid)"
python3 scripts/benchmark/to_lcu.py <match file> <puuid file> collector/review-cache   # a Riot API game as the review page reads it
```

Riot blocks Python's default user agent, so the scripts send their own. A development key allows
100 requests per 2 minutes per region; the pull scripts stay under that.
