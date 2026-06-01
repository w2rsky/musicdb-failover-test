CREATE USER repl_user WITH REPLICATION LOGIN PASSWORD 'repl_password';

\connect musicdb

CREATE TABLE listeners (
    listener_id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    country TEXT NOT NULL
);

CREATE TABLE artists (
    artist_id SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE tracks (
    track_id SERIAL PRIMARY KEY,
    artist_id INT REFERENCES artists(artist_id),
    title TEXT NOT NULL,
    duration_ms INT NOT NULL
);

CREATE TABLE playback_events (
    event_id BIGSERIAL PRIMARY KEY,
    listener_id INT REFERENCES listeners(listener_id),
    track_id INT REFERENCES tracks(track_id),
    played_at TIMESTAMPTZ DEFAULT now(),
    device TEXT NOT NULL,
    played_ms INT NOT NULL,
    completed BOOLEAN NOT NULL
);

CREATE INDEX idx_playback_events_played_at ON playback_events(played_at);
CREATE INDEX idx_playback_events_listener ON playback_events(listener_id);

INSERT INTO listeners(username, country)
SELECT 'user_' || g,
       CASE WHEN g % 3 = 0 THEN 'DE'
            WHEN g % 3 = 1 THEN 'FR'
            ELSE 'US'
       END
FROM generate_series(1, 100) AS g;

INSERT INTO artists(name)
SELECT 'artist_' || g
FROM generate_series(1, 20) AS g;

INSERT INTO tracks(artist_id, title, duration_ms)
SELECT ((g - 1) % 20) + 1,
       'track_' || g,
       120000 + ((g % 180) * 1000)
FROM generate_series(1, 200) AS g;
