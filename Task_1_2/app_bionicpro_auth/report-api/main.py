from fastapi import FastAPI, HTTPException, Request, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import clickhouse_connect
import pandas as pd
import asyncpg
import logging

app = FastAPI(title="Report API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-New-Session-Id", "x-new-session-id"]
)

AUTH_SERVICE_URL = "http://auth:8000"
CLICKHOUSE_HOST = "clickhouse_db"
CLICKHOUSE_PORT = 8123
CRM_DB_HOST = "crm_db"
CRM_DB_PORT = 5432
CRM_DB_USER = "crm_user"
CRM_DB_PASSWORD = "crm_password"
CRM_DB_NAME = "crm_db"


# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def validate_session(session_id: str) -> tuple[dict, str | None]:
    """
    Проверка сессии через auth-service.
    Возвращает (validation_data, new_session_id)
    """
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


@app.get("/reports")
async def get_report(
    request: Request,
    response: Response,
    start_date: str = Query(..., description="Start date format: YYYY-MM-DD HH:MM:SS"),
    end_date: str = Query(..., description="End date format: YYYY-MM-DD HH:MM:SS")
):
    """
    Получение отчёта по телеметрии пользователя.
    Группировка по prosthesis_type и 5-минутным интервалам.
    """
    # 1. Получаем session_id из cookie
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 2. Проверяем сессию и получаем email пользователя
    validation, new_session_id = await validate_session(session_id)
    logger.info(f"new_session_id: {new_session_id}")

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

    # 4. Подключаемся к ClickHouse
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

    # 5. Формируем и выполняем запрос
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

    # 6. Преобразуем результат в JSON
    if result.empty:
        content = {
            "user_id": user_id,
            "user_email": user_email,
            "start_date": start_date,
            "end_date": end_date,
            "total_intervals": 0,
            "data": []
        }
    else:
        result['interval_start'] = result['interval_start'].dt.strftime('%Y-%m-%d %H:%M:%S')
        result['avg_frequency'] = result['avg_frequency'].round(2)
        result['avg_duration'] = result['avg_duration'].round(0).astype(int)
        result['avg_amplitude'] = result['avg_amplitude'].round(2)

        content = {
            "user_id": user_id,
            "user_email": user_email,
            "start_date": start_date,
            "end_date": end_date,
            "total_intervals": len(result),
            "data": result.to_dict(orient='records')
        }

    # 7. Создаём JSONResponse и добавляем заголовок для ротации сессии
    json_response = JSONResponse(content=content)

    if new_session_id:
        logger.info(f"Setting X-New-Session-Id header: {new_session_id}")
        json_response.headers["X-New-Session-Id"] = new_session_id

    return json_response


@app.options("/reports")
async def options_reports():
    return JSONResponse(content={}, status_code=200)


@app.get("/health")
async def health():
    return {"status": "ok"}