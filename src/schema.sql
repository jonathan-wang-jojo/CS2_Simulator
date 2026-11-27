CREATE TABLE teams (
    team_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE
);

CREATE TABLE team_aliases (
    alias_key TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    team_id TEXT NOT NULL REFERENCES teams(team_id),
    source_url TEXT NOT NULL
);

CREATE TABLE players (
    player_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE
);

CREATE TABLE player_aliases (
    alias_key TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    player_id TEXT NOT NULL REFERENCES players(player_id),
    source_url TEXT NOT NULL
);

CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tier TEXT NOT NULL,
    is_lan INTEGER NOT NULL CHECK (is_lan IN (0, 1)),
    format TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    is_major INTEGER NOT NULL CHECK (is_major IN (0, 1)),
    source_url TEXT NOT NULL
);

CREATE TABLE matches (
    match_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(event_id),
    date TEXT NOT NULL,
    round_name TEXT NOT NULL DEFAULT '',
    team_a_id TEXT NOT NULL REFERENCES teams(team_id),
    team_b_id TEXT NOT NULL REFERENCES teams(team_id),
    score_a INTEGER NOT NULL CHECK (score_a >= 0),
    score_b INTEGER NOT NULL CHECK (score_b >= 0),
    best_of INTEGER NOT NULL CHECK (best_of > 0 AND best_of % 2 = 1),
    source_url TEXT NOT NULL,
    CHECK (team_a_id != team_b_id),
    CHECK (score_a != score_b),
    UNIQUE (source_url)
);

CREATE TABLE maps (
    map_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE map_results (
    match_id TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    map_number INTEGER NOT NULL CHECK (map_number > 0),
    map_id TEXT NOT NULL REFERENCES maps(map_id),
    score_a INTEGER NOT NULL CHECK (score_a >= 0),
    score_b INTEGER NOT NULL CHECK (score_b >= 0),
    PRIMARY KEY (match_id, map_number),
    UNIQUE (match_id, map_id),
    CHECK (score_a != score_b)
);

CREATE TABLE player_series_ratings (
    match_id TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    player_id TEXT NOT NULL REFERENCES players(player_id),
    rating REAL NOT NULL CHECK (rating >= 0),
    PRIMARY KEY (match_id, player_id)
);

CREATE TABLE player_map_ratings (
    match_id TEXT NOT NULL,
    map_number INTEGER NOT NULL,
    player_id TEXT NOT NULL REFERENCES players(player_id),
    rating REAL NOT NULL CHECK (rating >= 0),
    PRIMARY KEY (match_id, map_number, player_id),
    FOREIGN KEY (match_id, map_number)
        REFERENCES map_results(match_id, map_number) ON DELETE CASCADE
);

CREATE TABLE veto_actions (
    match_id TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    action_number INTEGER NOT NULL CHECK (action_number > 0),
    action TEXT NOT NULL CHECK (action IN ('pick', 'ban')),
    map_id TEXT NOT NULL REFERENCES maps(map_id),
    team_id TEXT NOT NULL REFERENCES teams(team_id),
    PRIMARY KEY (match_id, action_number),
    UNIQUE (match_id, map_id)
);

CREATE TABLE roster_stints (
    team_id TEXT NOT NULL REFERENCES teams(team_id),
    player_id TEXT NOT NULL REFERENCES players(player_id),
    start_date TEXT NOT NULL,
    end_date TEXT,
    is_stand_in INTEGER NOT NULL CHECK (is_stand_in IN (0, 1)),
    known_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    PRIMARY KEY (team_id, player_id, start_date),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE INDEX matches_by_date ON matches(date);
CREATE INDEX matches_by_event ON matches(event_id, date);
CREATE UNIQUE INDEX matches_unique_event_date_pair ON matches(
    event_id,
    date,
    CASE WHEN team_a_id < team_b_id THEN team_a_id ELSE team_b_id END,
    CASE WHEN team_a_id < team_b_id THEN team_b_id ELSE team_a_id END
);
CREATE INDEX roster_stints_by_date ON roster_stints(start_date, end_date);
