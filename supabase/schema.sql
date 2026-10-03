-- NHL Total Model: run history in Supabase (same project as the MLB model, tables prefixed nhl_).
-- Paste into the Supabase SQL Editor once. Safe to re-run (IF NOT EXISTS / OR REPLACE).
--
-- Security: row-level security is ON with no policies, and the anon/authenticated roles get no
-- access, so the public (anon) key used by the MLB website can't read or write these tables.
-- Only the service key (GitHub secret SUPABASE_KEY) can, and it bypasses RLS.

-- one row per model run
create table if not exists nhl_runs (
  run_id        uuid primary key,
  run_at        timestamptz not null,
  game_date     date not null,
  trigger       text,              -- hourly / pregame / manual / schedule
  commit_sha    text,
  gh_run_url    text,
  n_games       int,
  n_flags       int,
  sources       jsonb              -- which data sources loaded, e.g. {"dailyfaceoff": true, ...}
);

-- one row per game per run (the history): everything the dashboard shows at that moment
create table if not exists nhl_projections (
  run_id        uuid not null references nhl_runs(run_id) on delete cascade,
  game_date     date not null,
  away          text not null,
  home          text not null,
  game_id       bigint,
  start_utc     timestamptz,
  proj          real, proj_away real, proj_home real, p7 real, cutoff real,
  flag          boolean,
  call          text,              -- SLAM / 1U / AVOID
  open_total    real, open_over int,
  line_total    real, line_over int, line_under int,
  best_book     text, best_total real, best_over int, best_under int,
  away_goalie   text, home_goalie text,
  away_b2b      boolean, home_b2b boolean,
  away_out      text, home_out text, away_dtd text, home_dtd text,
  away_ev real, away_pp real, away_oth real, away_gadj real, away_b2badj real, away_spd real, away_inj real,
  home_ev real, home_pp real, home_oth real, home_gadj real, home_b2badj real, home_spd real, home_inj real,
  primary key (run_id, game_date, away, home)
);
create index if not exists nhl_projections_game on nhl_projections (game_date, away, home);

-- one row per game: schedule, final score, closing line
create table if not exists nhl_games (
  game_date     date not null,
  away          text not null,
  home          text not null,
  game_id       bigint,
  start_utc     timestamptz,
  away_score    int, home_score int, final_total int,
  close_total   real, close_over int, close_under int,
  updated_at    timestamptz default now(),
  primary key (game_date, away, home)
);

-- the paper-trading record: first-flagged bet, never changed after it's logged (results added at settle)
create table if not exists nhl_paper_bets (
  game_date     date not null,
  away          text not null,
  home          text not null,
  flagged_at    text,
  proj          real, p7 real,
  bet_total     real, bet_over int, bet_under int,
  best_book     text, best_total real, best_over int, best_under int,
  result        text, profit real, clv real,
  result_best   text, profit_best real,
  updated_at    timestamptz default now(),
  primary key (game_date, away, home)
);

alter table nhl_runs        enable row level security;
alter table nhl_projections enable row level security;
alter table nhl_games       enable row level security;
alter table nhl_paper_bets  enable row level security;

-- latest projection per game, and the last one before puck drop (what results are graded on)
create or replace view nhl_latest_projection with (security_invoker = on) as
select distinct on (p.game_date, p.away, p.home) p.*, r.run_at, r.trigger
from nhl_projections p join nhl_runs r using (run_id)
order by p.game_date, p.away, p.home, r.run_at desc;

create or replace view nhl_pregame_call with (security_invoker = on) as
select distinct on (p.game_date, p.away, p.home) p.*, r.run_at, r.trigger
from nhl_projections p join nhl_runs r using (run_id)
where p.start_utc is null or r.run_at < p.start_utc
order by p.game_date, p.away, p.home, r.run_at desc;

-- how each run's call did, by hours before puck drop (the question this whole table exists for)
create or replace view nhl_call_by_lead_time with (security_invoker = on) as
select p.call,
       floor(extract(epoch from (p.start_utc - r.run_at)) / 3600)::int as hours_before,
       count(*) as games,
       sum(case when (p.call <> 'AVOID') = (g.final_total > p.line_total) and g.final_total <> p.line_total then 1 else 0 end) as right_calls,
       sum(case when g.final_total = p.line_total then 1 else 0 end) as pushes
from nhl_projections p
join nhl_runs r using (run_id)
join nhl_games g using (game_date, away, home)
where g.final_total is not null and p.line_total is not null and p.start_utc is not null and r.run_at < p.start_utc
group by 1, 2;

revoke all on nhl_runs, nhl_projections, nhl_games, nhl_paper_bets,
              nhl_latest_projection, nhl_pregame_call, nhl_call_by_lead_time from anon, authenticated;
