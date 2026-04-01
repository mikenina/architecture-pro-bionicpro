# airflow/Dockerfile
FROM apache/airflow:2.9.1-python3.9

USER airflow

COPY requirements.txt /requirements.txt

# Устанавливаем зависимости без --user
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r /requirements.txt