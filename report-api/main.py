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
from datetime import datetime, timedelta
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

# ========== Настройки Minio/S3 ==========
MINIO_ENDPOINT = "http://minio:9000"
MINIO_ACCESS_KEY = "minio_user"
MINIO_SECRET_KEY = "minio_password"
MINIO_BUCKET = "reports"
CDN_BASE_URL = "http://localhost:8085"

# TTL кеша (5 минут)
CACHE_TTL_SECONDS = 300

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


def is_report_fresh(cache_key: str) -> bool:
    """
    Проверяет, не устарел ли отчёт (моложе CACHE_TTL_SECONDS).
    """
    try:
        response = s3_client.head_object(Bucket=MINIO_BUCKET, Key=cache_key)
        last_modified = response['LastModified']
        age = datetime.now(last_modified.tzinfo) - last_modified
        is_fresh = age.total_seconds() < CACHE_TTL_SECONDS
        logger.info(f"Report age: {age.total_seconds():.0f}s, fresh: {is_fresh}")
        return is_fresh
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            return False
        raise


def save_report_to_s3(report_data: dict, cache_key: str) -> str:
    """Сохраняет отчёт в S3 и возвращает CDN URL"""
    ensure_bucket_exists()

    s3_client.put_object(
        Bucket=MINIO_BUCKET,
        Key=cache_key,
        Body=json.dumps(report_data, indent=2, default=str),
        ContentType='application/json',
        Metadata={
            'generated-at': datetime.now().isoformat()
        }
    )
    logger.info(f"Report saved to S3: {cache_key}")

    return get_cdn_url(cache_key)


def get_report_from_s3(cache_key: str):
    """
    Проверяет наличие и свежесть отчёта в S3.
    Возвращает cdn_url или None.
    """
    if is_report_fresh(cache_key):
        cdn_url = get_cdn_url(cache_key)
        logger.info(f"Fresh report found in cache: {cdn_url}")
        return cdn_url
    else:
        logger.info(f"Report not found or stale: {cache_key}")
        return None


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


async def get_user_id_by_email_from_clickhouse(email: str) -> int:
    """Получение user_id из витрины ClickHouse (customers_snapshot)"""
    client = clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username="default",
        password="",
        database="reports"
    )
    result = client.query_df(f"""
        SELECT id FROM customers_snapshot
        WHERE email = '{email}'
        ORDER BY updated_at DESC
        LIMIT 1
    """)
    if result.empty:
        return None
    return int(result.iloc[0]['id'])


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
    Кеширование в S3 на 5 минут (только если есть данные).
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

    # 3. По email получаем числовой user_id из ClickHouse (customers_snapshot)
    user_id = await get_user_id_by_email_from_clickhouse(user_email)
    if not user_id:
        raise HTTPException(
            status_code=404,
            detail=f"User with email {user_email} not found in CRM"
        )

    # 4. Генерируем ключ кеша и проверяем S3
    cache_key = get_report_cache_key(user_id, start_date, end_date)
    cdn_url = get_report_from_s3(cache_key)

    # 5. Если отчёт есть и свежий — отдаём CDN ссылку
    if cdn_url:
        json_response = JSONResponse(content={
            "cached": True,
            "cdn_url": cdn_url,
            "report_data": None
        })
        if new_session_id:
            json_response.headers["X-New-Session-Id"] = new_session_id
        return json_response

    # 6. Генерируем новый отчёт из витрины telemetry_enriched
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

    # Запрос к обогащённой витрине
    query = f"""
        SELECT
            toStartOfHour(signal_time) as interval_start,
            prosthesis_type,
            avg(signal_frequency) as avg_frequency,
            avg(signal_duration) as avg_duration,
            avg(signal_amplitude) as avg_amplitude,
            count() as signal_count
        FROM reports.telemetry_enriched
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
        # Нет данных — не кешируем, возвращаем пустой ответ
        content = {
            "cached": False,
            "report_data": {
                "user_id": user_id,
                "user_email": user_email,
                "start_date": start_date,
                "end_date": end_date,
                "generated_at": datetime.now().isoformat(),
                "total_intervals": 0,
                "data": []
            }
        }
        json_response = JSONResponse(content=content)
        if new_session_id:
            json_response.headers["X-New-Session-Id"] = new_session_id
        return json_response

    # Есть данные — форматируем результат
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
        "total_intervals": len(result),
        "data": result.to_dict(orient='records')
    }

    # 7. Сохраняем в S3 (только если есть данные)
    cdn_url = save_report_to_s3(report_data, cache_key)

    # 8. Формируем ответ
    content = {
        "cached": False,
        "cdn_url": cdn_url,
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