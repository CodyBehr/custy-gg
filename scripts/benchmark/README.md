# Expert benchmark (research scripts)

Pull high-elo games for one champion and role through the Riot API and compare a game against them.
Player lists come from onetricks.gg's ranking for that champion (`name #tag|REGION`, one per line).

```bash
export RIOT_API_KEY=RGAPI-...          # never commit this
mkdir -p data/benchmark && curl -o scripts/benchmark/item.json \
  https://ddragon.leagueoflegends.com/cdn/$(curl -s https://ddragon.leagueoflegends.com/api/versions.json | python3 -c "import json,sys;print(json.load(sys.stdin)[0])")/data/en_US/item.json
CHAMP=Jhin POS=BOTTOM PER=8 SCAN=60 PLAYERS=scripts/benchmark/players-jhin-bot.txt \
  python3 scripts/benchmark/pull.py data/benchmark/jhin_bot          # ~5-10 min on a dev key
python3 scripts/benchmark/analyse.py data/benchmark/jhin_bot          # minute break points, backs, items, deaths
python3 scripts/benchmark/builds.py data/benchmark/jhin_bot 3036      # build order; 3036 = Lord Dominik's Regards
python3 scripts/benchmark/mine.py Ringo 1432 Jhin                     # someone's latest game on that champion
python3 scripts/benchmark/compare.py data/benchmark/jhin_bot data/benchmark/mine/<match>.json "$(cat data/benchmark/Ringo.puuid)"
```

Riot blocks Python's default user agent, so the scripts send their own. A development key allows
100 requests per 2 minutes per region; pull.py stays under that.

The review page reads `public/benchmarks/<Champion>-<ROLE>.json` (served from the site) for its **vs Experts** tab:

```bash
python3 scripts/benchmark/build_benchmark.py data/benchmark/jhin_bot public/benchmarks
```
