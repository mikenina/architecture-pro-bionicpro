from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.models import Variable
import pandas as pd
import logging
from airflow.operators.python import PythonOperator
import boto3
import json
from botocore.config import Config

# Настройка логирования
logger = logging.getLogger(__name__)

# Параметры DAG
default_args = {
    'owner': 'bionicpro',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=1),
}

# Создаем DAG с расписанием раз в минуту
dag = DAG(
    'telemetry_etl',
    default_args=default_args,
    description='ETL: Load telemetry data from PostgreSQL to ClickHouse',
    schedule_interval='0 * * * *',
    catchup=False,
    tags=['bionicpro', 'telemetry', 'etl'],
    max_active_runs=1,
)


def extract_telemetry(**context):
    """
    Извлечение новых данных телеметрии из PostgreSQL
    """
    logger.info("Starting extraction from telemetry_db...")

    # Получаем время последнего запуска из переменной Airflow
    last_run = Variable.get('last_processed_time', default_var=None)

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

    logger.info(f"Executing SQL:\n{sql}")

    df = pg_hook.get_pandas_df(sql)
    logger.info(f"Extracted {len(df)} records from telemetry_db")

    if df.empty:
        logger.info("No new data to process")
        return None

    # Сохраняем данные в XCom для следующей задачи
    context['task_instance'].xcom_push(key='telemetry_data', value=df.to_json())

    # Сохраняем максимальное время в XCom (для последующего сохранения в переменную)
    max_time = df['signal_time'].max()
    max_time_str = max_time.isoformat()
    logger.info(f"Max signal time in this batch: {max_time_str}")
    context['task_instance'].xcom_push(key='batch_max_time', value=max_time_str)

    return len(df)


def extract_crm(**context):
    """
    Извлечение данных о клиентах из CRM PostgreSQL
    """
    logger.info("Starting extraction from crm_db...")

    pg_hook = PostgresHook(postgres_conn_id='crm_db')

    sql = """
        SELECT
            id as user_id,
            age,
            gender,
            country
        FROM customers
    """

    df = pg_hook.get_pandas_df(sql)
    logger.info(f"Extracted {len(df)} customers from crm_db")

    context['task_instance'].xcom_push(key='crm_data', value=df.to_json())

    return len(df)


def enrich_and_load(**context):
    """
    Обогащение телеметрии данными CRM и загрузка в ClickHouse
    """
    import clickhouse_connect
    import pandas as pd

    # Получаем данные из XCom
    telemetry_json = context['task_instance'].xcom_pull(key='telemetry_data', task_ids='extract_telemetry')
    crm_json = context['task_instance'].xcom_pull(key='crm_data', task_ids='extract_crm')

    if not telemetry_json:
        logger.info("No telemetry data to load")
        return "No data to load"

    # Загружаем в DataFrame
    telemetry_df = pd.read_json(telemetry_json)
    crm_df = pd.read_json(crm_json)

    logger.info(f"Telemetry records: {len(telemetry_df)}")
    logger.info(f"CRM records: {len(crm_df)}")

    # Обогащаем: JOIN по user_id
    enriched_df = telemetry_df.merge(crm_df, on='user_id', how='left')

    # Заполняем пропуски
    enriched_df['age'] = enriched_df['age'].fillna(0)
    enriched_df['gender'] = enriched_df['gender'].fillna('Unknown')
    enriched_df['country'] = enriched_df['country'].fillna('Unknown')

    # Приводим типы данных
    enriched_df['user_id'] = enriched_df['user_id'].astype('int64')
    enriched_df['age'] = enriched_df['age'].astype('int8')
    enriched_df['signal_frequency'] = enriched_df['signal_frequency'].astype('int64')
    enriched_df['signal_duration'] = enriched_df['signal_duration'].astype('int64')
    enriched_df['signal_amplitude'] = enriched_df['signal_amplitude'].astype('float64')
    enriched_df['signal_time'] = pd.to_datetime(enriched_df['signal_time'])

    # Выбираем нужные колонки
    final_df = enriched_df[[
        'user_id', 'age', 'gender', 'country',
        'prosthesis_type', 'muscle_group',
        'signal_frequency', 'signal_duration',
        'signal_amplitude', 'signal_time'
    ]]

    logger.info(f"Enriched records: {len(final_df)}")

    # Подключаемся к ClickHouse
    client = clickhouse_connect.get_client(
        host='clickhouse_db',
        port=8123,
        username='default',
        password='',
        database='reports'
    )

    # Проверяем таблицу
    try:
        client.command("SELECT 1 FROM telemetry_stat LIMIT 1")
        logger.info("Table telemetry_stat exists")
    except Exception:
        create_table_sql = """
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
        ORDER BY (user_id, prosthesis_type, signal_time)
        """
        client.command(create_table_sql)
        logger.info("Table telemetry_stat created")

    # Вставляем данные
    client.insert_df('reports.telemetry_stat', final_df)
    logger.info(f"Loaded {len(final_df)} records to ClickHouse")

    # Передаем batch_max_time в XCom для следующей задачи
    batch_max_time = context['task_instance'].xcom_pull(key='batch_max_time', task_ids='extract_telemetry')
    if batch_max_time:
        context['task_instance'].xcom_push(key='batch_max_time_to_save', value=batch_max_time)

    return f"Loaded {len(final_df)} records"


def save_last_processed_time(**context):
    """
    Сохраняем время последней успешной обработки в переменную Airflow
    Выполняется ТОЛЬКО после успешной загрузки в ClickHouse
    """
    batch_max_time = context['task_instance'].xcom_pull(
        key='batch_max_time_to_save',
        task_ids='enrich_and_load'
    )

    if batch_max_time:
        logger.info(f"Saving last processed time: {batch_max_time}")
        Variable.set('last_processed_time', batch_max_time)
    else:
        logger.info("No batch_max_time found, nothing to save")

def update_etl_version(**context):
    """
    Обновляет метку времени последнего успешного ETL в S3.
    """
    # Проверяем, были ли новые данные
    telemetry_json = context['task_instance'].xcom_pull(
        key='telemetry_data',
        task_ids='extract_telemetry'
    )

    if not telemetry_json:
        print("No new data. Skipping ETL version update.")
        return "No new data, version not updated"

    minio_endpoint = 'http://minio:9000'
    minio_access_key = 'minio_user'
    minio_secret_key = 'minio_password'
    bucket = 'reports'
    metadata_key = 'metadata/etl_version.json'

    s3_client = boto3.client(
        's3',
        endpoint_url=minio_endpoint,
        aws_access_key_id=minio_access_key,
        aws_secret_access_key=minio_secret_key,
        config=Config(signature_version='s3v4'),
        region_name='us-east-1'
    )

    # Создаём bucket, если не существует
    try:
        s3_client.head_bucket(Bucket=bucket)
    except:
        s3_client.create_bucket(Bucket=bucket)
        print(f"Bucket '{bucket}' created")

    # Сохраняем новую версию etl в общие метаданные
    new_version = datetime.now().isoformat()
    s3_client.put_object(
        Bucket=bucket,
        Key=metadata_key,
        Body=json.dumps({
            'version': new_version,
            'updated_at': new_version,
            'description': 'ETL completed'
        })
    )

    print(f"ETL version updated to {new_version}")
    return new_version

# Определяем задачи
extract_telemetry_task = PythonOperator(
    task_id='extract_telemetry',
    python_callable=extract_telemetry,
    dag=dag,
)

extract_crm_task = PythonOperator(
    task_id='extract_crm',
    python_callable=extract_crm,
    dag=dag,
)

enrich_load_task = PythonOperator(
    task_id='enrich_and_load',
    python_callable=enrich_and_load,
    dag=dag,
)

save_time_task = PythonOperator(
    task_id='save_last_processed_time',
    python_callable=save_last_processed_time,
    dag=dag,
)

update_etl_version_task = PythonOperator(
    task_id='update_etl_version',
    python_callable=update_etl_version,
    dag=dag,
)

# Порядок выполнения
[extract_telemetry_task, extract_crm_task] >> enrich_load_task >> save_time_task >> update_etl_version_task