from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.models import Variable
import pandas as pd
import logging
import clickhouse_connect

logger = logging.getLogger(__name__)

default_args = {
    'owner': 'bionicpro',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=1),
}

dag = DAG(
    'telemetry_raw_etl',
    default_args=default_args,
    description='ETL: Load raw telemetry data from PostgreSQL to ClickHouse',
    schedule_interval='0 * * * *',  # каждый час
    catchup=False,
    tags=['bionicpro', 'telemetry', 'raw'],
    max_active_runs=1,
)


def extract_telemetry(**context):
    """Извлечение новых данных телеметрии из PostgreSQL"""
    logger.info("Starting extraction from telemetry_db...")

    last_run = Variable.get('telemetry_last_processed_time', default_var=None)

    if not last_run:
        last_run = '2025-01-01 00:00:00'
        logger.info(f"First run, fetching all data from {last_run}")
    else:
        logger.info(f"Fetching telemetry data after: {last_run}")

    pg_hook = PostgresHook(postgres_conn_id='telemetry_db')

    sql = f"""
        SELECT
            user_id,
            prosthesis_type,
            muscle_group,
            signal_frequency,
            signal_duration,
            signal_amplitude,
            signal_time
        FROM telemetry_data
        WHERE signal_time > '{last_run}'
        ORDER BY signal_time
    """

    df = pg_hook.get_pandas_df(sql)
    logger.info(f"Extracted {len(df)} records from telemetry_db")

    if df.empty:
        logger.info("No new data to process")
        return None

    context['task_instance'].xcom_push(key='telemetry_data', value=df.to_json())

    max_time = df['signal_time'].max()
    max_time_str = max_time.isoformat()
    logger.info(f"Max signal time in this batch: {max_time_str}")
    context['task_instance'].xcom_push(key='batch_max_time', value=max_time_str)

    return len(df)


def load_to_clickhouse(**context):
    """Загрузка сырой телеметрии в ClickHouse (без обогащения)"""
    telemetry_json = context['task_instance'].xcom_pull(key='telemetry_data', task_ids='extract_telemetry')

    if not telemetry_json:
        logger.info("No telemetry data to load")
        return "No data to load"

    telemetry_df = pd.read_json(telemetry_json)

    # Приводим типы данных
    telemetry_df['user_id'] = telemetry_df['user_id'].astype('int64')
    telemetry_df['signal_frequency'] = telemetry_df['signal_frequency'].astype('int64')
    telemetry_df['signal_duration'] = telemetry_df['signal_duration'].astype('int64')
    telemetry_df['signal_amplitude'] = telemetry_df['signal_amplitude'].astype('float64')
    telemetry_df['signal_time'] = pd.to_datetime(telemetry_df['signal_time'])

    logger.info(f"Records to load: {len(telemetry_df)}")

    # Подключаемся к ClickHouse
    client = clickhouse_connect.get_client(
        host='clickhouse_db',
        port=8123,
        username='default',
        password='',
        database='reports'
    )

    # Создаём таблицу для сырой телеметрии (если не существует)
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS reports.telemetry_raw (
        user_id UInt32,
        prosthesis_type LowCardinality(String),
        muscle_group LowCardinality(String),
        signal_frequency UInt32,
        signal_duration UInt32,
        signal_amplitude Decimal(5,2),
        signal_time DateTime
    ) ENGINE = MergeTree()
    ORDER BY (user_id, signal_time)
    """
    client.command(create_table_sql)

    # Вставляем данные
    client.insert_df('reports.telemetry_raw', telemetry_df)
    logger.info(f"Loaded {len(telemetry_df)} records to ClickHouse")

    batch_max_time = context['task_instance'].xcom_pull(key='batch_max_time', task_ids='extract_telemetry')
    if batch_max_time:
        context['task_instance'].xcom_push(key='batch_max_time_to_save', value=batch_max_time)

    return f"Loaded {len(telemetry_df)} records"


def save_last_processed_time(**context):
    """Сохраняем время последней успешной обработки"""
    batch_max_time = context['task_instance'].xcom_pull(
        key='batch_max_time_to_save',
        task_ids='load_to_clickhouse'
    )

    if batch_max_time:
        logger.info(f"Saving last processed time: {batch_max_time}")
        Variable.set('telemetry_last_processed_time', batch_max_time)
    else:
        logger.info("No batch_max_time found, nothing to save")


extract_task = PythonOperator(
    task_id='extract_telemetry',
    python_callable=extract_telemetry,
    dag=dag,
)

load_task = PythonOperator(
    task_id='load_to_clickhouse',
    python_callable=load_to_clickhouse,
    dag=dag,
)

save_time_task = PythonOperator(
    task_id='save_last_processed_time',
    python_callable=save_last_processed_time,
    dag=dag,
)

extract_task >> load_task >> save_time_task