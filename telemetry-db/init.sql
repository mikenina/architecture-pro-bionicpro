CREATE TABLE IF NOT EXISTS telemetry_data (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    prosthesis_type VARCHAR(50),
    muscle_group VARCHAR(50),
    signal_frequency integer,
    signal_duration integer,
    signal_amplitude DECIMAL(5,2),
    signal_time TIMESTAMP
);

COPY telemetry_data(user_id, prosthesis_type, muscle_group, signal_frequency, signal_duration, signal_amplitude, signal_time)
    FROM '/docker-entrypoint-initdb.d/telemetry.csv'
    DELIMITER ','
    CSV HEADER;

CREATE INDEX idx_telemetry_user_id ON telemetry_data(user_id);
CREATE INDEX idx_telemetry_time ON telemetry_data(signal_time);