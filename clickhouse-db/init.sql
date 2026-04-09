CREATE DATABASE IF NOT EXISTS reports;

--- Таблица для демонстрации кейса объединение телеметрии и пользователей на этапе ETL ---
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

--- Таблицы для демонстрации кейса объединение телеметрии и пользователей с помощью Material View ---
-- ========== 1. Таблица-очередь из Kafka (CDC из CRM) ==========
CREATE TABLE IF NOT EXISTS reports.crm_customers_queue (
    id Int32,
    name String,
    email String,
    age String,
    gender String,
    country String,
    address String,
    phone String
) ENGINE = Kafka
    SETTINGS kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'crm.public.customers',
    kafka_group_name = 'clickhouse_consumer',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1;

-- ========== 2. Снапшот ==========
CREATE TABLE IF NOT EXISTS reports.customers_snapshot (
    id Int32,
    name String,
    email String,
    age Int32,
    gender String,
    country String,
    updated_at DateTime
) ENGINE = ReplacingMergeTree(updated_at)
    ORDER BY (id);

-- ========== 3. MaterializedView с преобразованием age ==========
CREATE MATERIALIZED VIEW IF NOT EXISTS reports.customers_snapshot_mv
TO reports.customers_snapshot
AS SELECT
    id,
    name,
    email,
    toInt32OrZero(JSONExtractString(age, 'value')) AS age,
    gender,
    country,
    now() AS updated_at
   FROM reports.crm_customers_queue;

-- ========== 3. Таблица для сырой телеметрии (загружается через Airflow) ==========
CREATE TABLE IF NOT EXISTS reports.telemetry_raw (
    user_id UInt32,
    prosthesis_type LowCardinality(String),
    muscle_group LowCardinality(String),
    signal_frequency UInt32,
    signal_duration UInt32,
    signal_amplitude Decimal(5,2),
    signal_time DateTime
) ENGINE = MergeTree()
ORDER BY (user_id, prosthesis_type, signal_time);

-- ========== 4. Витрина: обогащённая телеметрия ==========
CREATE TABLE IF NOT EXISTS reports.telemetry_enriched (
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

-- ========== 5. MaterializedView: при вставке в telemetry_raw обогащаем данными из CRM ==========
CREATE MATERIALIZED VIEW IF NOT EXISTS reports.telemetry_enriched_mv
TO reports.telemetry_enriched
AS SELECT
    t.user_id,
    c.age,
    c.gender,
    c.country,
    t.prosthesis_type,
    t.muscle_group,
    t.signal_frequency,
    t.signal_duration,
    t.signal_amplitude,
    t.signal_time
FROM reports.telemetry_raw AS t
LEFT JOIN reports.customers_snapshot AS c ON t.user_id = c.id;