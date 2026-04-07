from fastapi import FastAPI, HTTPException, Request, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import clickhouse_connect
import pandas as pd
import asyncpg
import logging
import boto3
import json
import hashlib
from datetime import datetime
from botocore.config import Config
from botocore.exceptions import ClientError

app = FastAPI(title="Report API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-New-Session-Id", "x-new-session-id"]
)

# ========== Настройки сервисов ==========
AUTH_SERVICE_URL = "http://auth:8000"
CLICKHOUSE_HOST = "clickhouse_db"
CLICKHOUSE_PORT = 8123
CRM_DB_HOST = "crm_db"
CRM_DB_PORT = 5432
CRM_DB_USER = "crm_user"
CRM_DB_PASSWORD = "crm_password"
CRM_DB_NAME = "crm_db"

# ========== Настройки Minio/S3 ==========
MINIO_ENDPOINT = "http://minio:9000"
MINIO_ACCESS_KEY = "minio_user"
MINIO_SECRET_KEY = "minio_password"
MINIO_BUCKET = "reports"
CDN_BASE_URL = "http://localhost:8085"
METADATA_KEY = "metadata/etl_version.json"

# ========== Настройка логирования ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== Инициализация S3 клиента ==========
s3_client = boto3.client(
    's3',
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY,
    config=Config(signature_version='s3v4'),
    region_name='us-east-1'
)


def ensure_bucket_exists():
    """Создаёт bucket в Minio, если не существует"""
    try:
        s3_client.head_bucket(Bucket=MINIO_BUCKET)
        logger.info(f"Bucket '{MINIO_BUCKET}' already exists")
    except ClientError:
        s3_client.create_bucket(Bucket=MINIO_BUCKET)
        logger.info(f"Bucket '{MINIO_BUCKET}' created")


def get_current_etl_version() -> tuple[str, str]:
    """
    Получает текущую версию ETL из S3.
    Возвращает (version, updated_at)
    """
    ensure_bucket_exists()

    try:
        response = s3_client.get_object(Bucket=MINIO_BUCKET, Key=METADATA_KEY)
        metadata = json.loads(response['Body'].read().decode('utf-8'))
        return metadata.get('version'), metadata.get('updated_at')
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            new_version = datetime.now().isoformat()
            s3_client.put_object(
                Bucket=MINIO_BUCKET,
                Key=METADATA_KEY,
                Body=json.dumps({
                    'version': new_version,
                    'updated_at': new_version,
                    'description': 'Initial ETL version'
                })
            )
            logger.info(f"Created initial ETL version: {new_version}")
            return new_version, new_version
        raise


def get_report_cache_key(user_id: int, start_date: str, end_date: str) -> str:
    """Генерирует ключ для хранения отчёта в S3"""
    params_str = f"{user_id}:{start_date}:{end_date}"
    params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
    safe_start = start_date.replace(' ', '_').replace(':', '-')
    safe_end = end_date.replace(' ', '_').replace(':', '-')
    filename = f"{safe_start}_{safe_end}_{params_hash}.json"
    return f"users/{user_id}/{filename}"


def get_cdn_url(cache_key: str) -> str:
    """Возвращает CDN URL для отчёта"""
    return f"{CDN_BASE_URL}/reports/{cache_key}"


def get_report_etl_version(cache_key: str) -> str | None:
    """Получает версию ETL, под которой был сохранён отчёт"""
    try:
        response = s3_client.head_object(Bucket=MINIO_BUCKET, Key=cache_key)
        return response.get('Metadata', {}).get('etl-version')
    except ClientError:
        return None


def is_report_valid(cache_key: str, current_etl_version: str) -> bool:
    """Проверяет, актуален ли отчёт"""
    report_version = get_report_etl_version(cache_key)
    return report_version == current_etl_version


def save_report_to_s3(report_data: dict, cache_key: str, etl_version: str) -> str:
    """Сохраняет отчёт в S3 и возвращает CDN URL"""
    ensure_bucket_exists()

    s3_client.put_object(
        Bucket=MINIO_BUCKET,
        Key=cache_key,
        Body=json.dumps(report_data, indent=2, default=str),
        ContentType='application/json',
        Metadata={
            'etl-version': etl_version,
            'generated-at': datetime.now().isoformat()
        }
    )
    logger.info(f"Report saved to S3: {cache_key} (ETL version: {etl_version})")

    return get_cdn_url(cache_key)


def get_report_from_s3(cache_key: str, current_etl_version: str):
    """
    Проверяет наличие и актуальность отчёта в S3.
    Возвращает (cdn_url, is_valid) или (None, None).
    """
    try:
        s3_client.head_object(Bucket=MINIO_BUCKET, Key=cache_key)

        if is_report_valid(cache_key, current_etl_version):
            cdn_url = get_cdn_url(cache_key)
            logger.info(f"Report found in cache (valid): {cdn_url}")
            return cdn_url, True
        else:
            logger.info(f"Report found but stale (ETL version mismatch)")
            return None, False
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            logger.info(f"Report not found in cache: {cache_key}")
            return None, None
        raise


async def validate_session(session_id: str) -> tuple[dict, str | None]:
    """Проверка сессии через auth-service"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AUTH_SERVICE_URL}/session/validate",
            cookies={"session_id": session_id}
        )
        data = response.json()
        logger.info(f"Auth-service response: {data}")
        new_session_id = data.get("new_session_id")
        logger.info(f"new_session_id from auth: {new_session_id}")
        return data, new_session_id

async def get_user_id_by_email(email: str) -> int:
    """Получение user_id из CRM по email"""
    conn = await asyncpg.connect(
        host=CRM_DB_HOST,
        port=CRM_DB_PORT,
        user=CRM_DB_USER,
        password=CRM_DB_PASSWORD,
        database=CRM_DB_NAME
    )
    try:
        result = await conn.fetchrow(
            "SELECT id FROM customers WHERE email = $1",
            email
        )
        return result['id'] if result else None
    finally:
        await conn.close()


@app.on_event("startup")
async def startup():
    """Инициализация при старте"""
    ensure_bucket_exists()
    logger.info("Report API started")


@app.get("/reports")
async def get_report(
    request: Request,
    response: Response,
    start_date: str = Query(..., description="Start date format: YYYY-MM-DD HH:MM:SS"),
    end_date: str = Query(..., description="End date format: YYYY-MM-DD HH:MM:SS")
):
    """
    Получение отчёта по телеметрии пользователя.
    Поддерживает кеширование в S3 и CDN.
    """
    # 1. Получаем session_id из cookie
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 2. Проверяем сессию и получаем email пользователя
    validation, new_session_id = await validate_session(session_id)

    if not validation.get("valid"):
        raise HTTPException(status_code=401, detail="Invalid session")

    user_email = validation.get("email")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email not found")

    # 3. По email получаем числовой user_id из CRM
    user_id = await get_user_id_by_email(user_email)
    if not user_id:
        raise HTTPException(
            status_code=404,
            detail=f"User with email {user_email} not found in CRM"
        )

    # 4. Получаем текущую версию ETL
    current_etl_version, data_updated_at = get_current_etl_version()
    logger.info(f"Current ETL version: {current_etl_version}, updated at: {data_updated_at}")

    # 5. Генерируем ключ кеша и проверяем S3
    cache_key = get_report_cache_key(user_id, start_date, end_date)
    cdn_url, is_valid = get_report_from_s3(cache_key, current_etl_version)

    # 6. Если отчёт есть и валиден — отдаём CDN ссылку
    if cdn_url and is_valid:
        json_response = JSONResponse(content={
            "cached": True,
            "valid": True,
            "cdn_url": cdn_url,
            "data_updated_at": data_updated_at,
            "report_data": None
        })
        if new_session_id:
            json_response.headers["X-New-Session-Id"] = new_session_id
        return json_response

    # 7. Генерируем новый отчёт
    logger.info(f"Generating new report for user {user_id}, period {start_date} - {end_date}")

    # Подключаемся к ClickHouse
    try:
        client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            username="default",
            password="",
            database="reports"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ClickHouse connection error: {e}")

    # Формируем и выполняем запрос
    query = f"""
        SELECT
            toStartOfHour(signal_time) as interval_start,
            prosthesis_type,
            avg(signal_frequency) as avg_frequency,
            avg(signal_duration) as avg_duration,
            avg(signal_amplitude) as avg_amplitude,
            count() as signal_count
        FROM telemetry_stat
        WHERE user_id = {user_id}
          AND signal_time >= parseDateTimeBestEffort('{start_date}')
          AND signal_time <= parseDateTimeBestEffort('{end_date}')
        GROUP BY interval_start, prosthesis_type
        HAVING count() > 0
        ORDER BY interval_start, prosthesis_type
    """

    try:
        result = client.query_df(query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ClickHouse query error: {e}")

    # Преобразуем результат в JSON
    if result.empty:
        report_data = {
            "user_id": user_id,
            "user_email": user_email,
            "start_date": start_date,
            "end_date": end_date,
            "generated_at": datetime.now().isoformat(),
            "data_updated_at": data_updated_at,
            "total_intervals": 0,
            "data": []
        }
    else:
        result['interval_start'] = result['interval_start'].dt.strftime('%Y-%m-%d %H:%M:%S')
        result['avg_frequency'] = result['avg_frequency'].round(2)
        result['avg_duration'] = result['avg_duration'].round(0).astype(int)
        result['avg_amplitude'] = result['avg_amplitude'].round(2)

        report_data = {
            "user_id": user_id,
            "user_email": user_email,
            "start_date": start_date,
            "end_date": end_date,
            "generated_at": datetime.now().isoformat(),
            "data_updated_at": data_updated_at,
            "total_intervals": len(result),
            "data": result.to_dict(orient='records')
        }

    # 8. Сохраняем в S3
    cdn_url = save_report_to_s3(report_data, cache_key, current_etl_version)

    # 9. Формируем ответ
    content = {
        "cached": False,
        "valid": True,
        "cdn_url": cdn_url,
        "data_updated_at": data_updated_at,
        "report_data": report_data
    }

    json_response = JSONResponse(content=content)
    if new_session_id:
        json_response.headers["X-New-Session-Id"] = new_session_id

    return json_response


@app.options("/reports")
async def options_reports():
    return JSONResponse(content={}, status_code=200)


@app.get("/health")
async def health():
    return {"status": "ok"}