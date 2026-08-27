# Fantasy Football War Room

A local Plotly Dash assistant for a 16-team ESPN Fantasy Football league. The first
release prioritizes a fast, resilient live draft workflow: it tracks every pick,
estimates who will survive to your next selection, and explains objective player
recommendations. The same normalized data and SQLite layers support a later
transition from Draft Mode to in-season roster, waiver, lineup, trade, injury,
matchup, standings, and playoff analysis.

The application runs immediately without an ESPN account using an unmistakably
synthetic sample player pool. That data is for application testing only—not for
a real draft.

## Current features

- Configurable snake order, including verified slot-10 picks in a 16-team league:
  `10, 23, 42, 55, 74, 87, 106`
- Fast manual pick entry with search and position filtering
- Automatic pick, round, and drafting-slot inference
- Undo, correction, reset, and SQLite save/load
- Monte Carlo next-pick availability estimates with configurable simulation count
- Opponent behavior influenced independently by ESPN rank, ADP, consensus/model
  rank, projections, roster need, reaches, and random variation
- Positional scarcity, expected position runs, tier drops, and replacement value
- Configurable recommendation weights and roster-construction penalties
- ESPN Rank, Model Rank, ADP, projection, probability, and recommendation columns
- ESPN Value Gap analysis with an explicit sign convention
- ESPN connection/settings, League, and My Team pages
- Minimal season-mode shells for Waivers, Start / Sit, Trades, News & Injuries,
  and Matchups
- SQLite tables for leagues, teams, players, draft picks, rosters, projections,
  rankings, simulations, transactions, and application settings

## Install and run

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

macOS/Linux:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Then open `http://127.0.0.1:8050`.

Run the tests with:

```bash
pytest
```

## ESPN configuration

The integration uses the community-maintained
[`espn_api` package](https://github.com/cwendt94/espn-api). ESPN does not publish a
supported Fantasy Football API contract, so all calls are isolated in
`src/integrations/espn.py` and fail back to offline/manual mode.

1. Copy `.env.example` to `.env`.
2. Put the league ID from the ESPN league URL in `ESPN_LEAGUE_ID`.
3. Keep `ESPN_SEASON=2026`, or change it to the league's season.
4. Leave `ESPN_S2` and `ESPN_SWID` blank for a public league.
5. For a private league, obtain both cookie values from your authenticated ESPN
   browser session and add them locally.

```dotenv
ESPN_LEAGUE_ID=
ESPN_SEASON=2026
ESPN_S2=
ESPN_SWID=
```

Do not commit `.env`. `espn_s2` and `SWID` are sensitive session credentials;
someone holding valid cookies may be able to access your ESPN account data. They
are never shown in the UI, logged, serialized into draft state, or stored in
SQLite. The database rejects settings keys that look like credentials.

In the app, open **Settings**, enter the non-secret league ID and season, and click
**Test ESPN Connection**. **Refresh League Data** fetches a new snapshot and
invalidates cached simulations. If ESPN rejects the credentials, the season is not yet
available, the network is down, or the response format changes, the app displays a
safe explanation and keeps the manual Draft Room operational.

After connecting, select **My ESPN team** by team name/owner. This ESPN team ID is
stored separately from draft slot 10 because those identities are not guaranteed
to match.

## ESPN data behavior

The adapter attempts to normalize:

- league name, team count, scoring label, roster and draft settings
- teams, owners, records, standings, and points
- team rosters and lineup slots
- free agents and available ESPN player metadata
- injury, ownership, ESPN/platform rank, and projections when exposed
- completed draft results
- current scoreboard/matchups

Missing fields remain nullable at the integration boundary. For draft operation,
ESPN players missing projections use a clearly disclosed rank-derived proxy; for
a real draft, import a current projection/ADP CSV and match it to ESPN identities.
The matching layer removes suffixes and punctuation, normalizes team aliases, uses
position/team disambiguation, and refuses ambiguous merges.

ESPN settings override fallback team count and round count when a snapshot loads
before manual picks begin. If ESPN reports a scoring format different from the
fallback, the interface surfaces the difference. Accurate custom-scoring player
values still require stat-level projections or scoring-specific external
projections; the app does not silently claim a standard projection is custom.

## Live draft synchronization limitation

The wrapper exposes a `draft` collection for completed/available draft results,
but ESPN's undocumented backend does not guarantee a reliable low-latency feed
during an active draft. Consequently, this version does not advertise automatic
live synchronization. Assisted manual tracking is the dependable path during the
draft, while ESPN draft results can be used for later reconciliation once ESPN
returns them. This avoids losing the War Room when a platform request is delayed
or changes shape.

## Recommendation model

Weights live in `config/league_config.yaml`. The score combines normalized:

- model value and projected points
- ADP value and current tier
- positional scarcity and tier drop
- open roster needs
- probability of being drafted before the next selection
- expected replacement value

The model penalizes early D/ST and kicker picks, usually penalizes a second early
quarterback, and discourages extreme one-position builds. These are configurable
constraints, not absolute rules. Recommendations are estimates rather than
guarantees.

The simulator makes every opponent selection probabilistic. A configurable reach
rate and lognormal noise prevent managers from behaving like perfect optimizers.
Default simulation count is 5,000; lower it in YAML on slower machines.

## Data format

Normalized player sources use these columns (nullable where unavailable):

```text
player_id, espn_player_id, player_name, position, team, bye_week,
injury_status, espn_rank, ownership_pct, projected_points, actual_points,
adp, consensus_rank, model_rank, position_rank, tier, drafted
```

`src/data/loaders.py` is provider-neutral. Replace the synthetic generator with a
normalized CSV or add another provider without changing the draft engine.

## Project structure

```text
fantasy-football-app/
├── app.py
├── config/league_config.yaml
├── data/{raw,processed,sample}/
├── src/
│   ├── integrations/espn.py
│   ├── draft/{order,state,simulator}.py
│   ├── recommendations/{scoring,scarcity,engine}.py
│   ├── roster/roster.py
│   ├── data/{loaders,player_matching}.py
│   ├── storage/database.py
│   ├── waivers/
│   ├── injuries/
│   ├── trades/
│   ├── lineup/
│   └── projections/
├── tests/
└── notebooks/simulation_experiments.ipynb
```

## Persistence and security

The local database is created at `data/fantasy_war_room.db` and is ignored by Git.
It stores manual draft history, the chosen ESPN team ID, and normalized/cached
non-secret data. It never stores cookies. Local saved states, environment files,
local secrets, common credential filenames, notebook checkpoints, virtual
environments, and editor caches are ignored.

## Planned development

The best next feature is a real 2026 projection/ADP import pipeline with an
interactive unmatched-player review. That makes ESPN's actual player pool useful
for high-quality recommendations while preserving ESPN rank as a separate signal.
After that, calibrate opponent behavior against your league's completed draft and
implement lineup-aware waiver recommendations using synchronized ESPN rosters and
free agents.
