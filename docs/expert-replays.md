# Expert replays for the coach

custy coach gathers high-elo games in the background so the coach can learn how top players play.

## What it does

1. **custy.gg picks a game.** It reads the NA ladder from the top: Challenger first, then Grandmaster, then Master. It hands each PC a different recent game from the current patch, so no game is downloaded twice.
2. **Your app downloads the replay** through your League client, up to 8 an hour (leaving room for your own replays), whenever League is open and you're not in champ select or a game.
3. **The replay is boiled down to a small data file** (about 1 MB). It holds every champion's positions, hits, ability and summoner casts, levels and health over the whole game. Then the replay is deleted.
4. **The data file is sent to custy.gg** and then deleted from your PC too.
5. **custy.gg collects everyone's files in one place,** and the coach learns from them: how experts trade, when they fight, how lanes play out.

## On the Recordings tab

- **Download 8 high-elo replays an hour:** turns it on or off. It's on by default.
- **Status:** what it's doing right now, how many games it downloaded today and in total, and how many were sent to custy.gg.
- **custy.gg storage:** whether uploads are working.
- **Sent to custy.gg so far:** how many games each person's app has contributed, by Riot ID.
- **Open League when it's closed:** if League is closed and you've been away from your PC for 10 minutes, the app opens it so downloads can keep going.
