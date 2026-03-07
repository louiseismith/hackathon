-- NYC Urban Risk — Supabase schema

CREATE TABLE IF NOT EXISTS community_districts (
    cd_id               TEXT PRIMARY KEY,
    borough             TEXT NOT NULL,
    community_district  INTEGER NOT NULL,
    neighborhood        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS heat_index (
    cd_id               TEXT NOT NULL REFERENCES community_districts(cd_id),
    date                DATE NOT NULL,
    temperature_f       NUMERIC(5,1),
    humidity_pct        NUMERIC(5,1),
    heat_index_f        NUMERIC(5,1),
    heat_index_risk     NUMERIC(5,2),
    PRIMARY KEY (cd_id, date)
);

CREATE TABLE IF NOT EXISTS hospital_capacity (
    cd_id                   TEXT NOT NULL REFERENCES community_districts(cd_id),
    date                    DATE NOT NULL,
    total_capacity_pct      NUMERIC(5,1),
    icu_capacity_pct        NUMERIC(5,1),
    ed_wait_hours           NUMERIC(5,1),
    PRIMARY KEY (cd_id, date)
);

CREATE TABLE IF NOT EXISTS transit_delays (
    cd_id                   TEXT NOT NULL REFERENCES community_districts(cd_id),
    date                    DATE NOT NULL,
    transit_delay_index     NUMERIC(5,2),
    PRIMARY KEY (cd_id, date)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_heat_index_date        ON heat_index(date);
CREATE INDEX IF NOT EXISTS idx_hospital_capacity_date ON hospital_capacity(date);
CREATE INDEX IF NOT EXISTS idx_transit_delays_date    ON transit_delays(date);
