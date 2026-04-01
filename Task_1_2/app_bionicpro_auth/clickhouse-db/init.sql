CREATE DATABASE IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.telemetry_stat (
    user_id UInt32,
    age UInt8,
    gender LowCardinality(String),
    country LowCardinality(String),
    prosthesis_type LowCardinality(String),
    muscle_group LowCardinality(String),
    signal_frequency UInt32,
    signal_duration UInt32,
    signal_amplitude Decimal(5,2),
    signal_time DateTime
    ) ENGINE = MergeTree()
    ORDER BY (user_id, prosthesis_type, signal_time);
