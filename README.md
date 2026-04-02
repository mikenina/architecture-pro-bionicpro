# Кейс компании BionicPRO
## Цели бизнеса
Компания BionicPRO ставит перед собой следующие цели:
1) Злоумышленники не должны использовать уязвимость SSO в приложении.
2) У пользователей должна быть возможность скачать данные о работе протеза в виде отчёта. Чтобы реализовать эту функциональность, необходимо выгружать данные из CRM в ClickHouse. Для этого требуется написать отдельное приложение, которое сможет предоставлять отчёт из нескольких источников — CRM и DB.
3) Пользователь должен иметь доступ только к тем отчётам, которые содержат данные о его протезе или протезах. Доступ к информации о других пользователях должен быть закрыт.

## Задание 1. Повышение безопасности системы
### Задача 1. Предложите архитектурное решение и доработайте диаграмму C4 для управления учётными данными пользователя. 
![c4_container_model_auth](schemas/BionicPRO_C4_model_auth.drawio.png)

### Задача 2. Улучшите безопасность существующего приложения, заменив Code Grant на PKCE.
_Его нужно добавить к уже существующим приложениям — фронтенду и Keycloak._

[PKCE code](./app_pkce)

```bash
cd ./app_pkce
docker compose up -d
```


### Задача 3. Обеспечьте безопасное получение и хранение access-и refresh-токенов.
### Задача 4. Добавьте LDAP для возможности получения данных о пользователях представительства BionicPRO в другой стране.
### Задача 5. Настройте MFA.

```bash
docker compose up -d
```

#### Keycloak Panel
http://localhost:8080/admin/master/console/

#### Application

http://localhost:3000/

#### Диаграмма последовательности процесса аутентификации\авторизации пользователя
![auth_sequence](schemas/auth_sequence.png)

##### Выгрузка конфига из Keycloak
```bash
docker exec bionicpro-keycloak-1 /opt/keycloak/bin/kc.sh export --realm reports-realm --file /tmp/realm-export.json
docker cp bionicpro-keycloak-1:/tmp/realm-export.json ./keycloak/keycloak-results-export.json
```

[keycloak-results-export.json](keycloak/keycloak-results-export.json)

### Задача 6. Добавьте OAuth 2.0 от Яндекс ID.

https://github.com/playa-ru/keycloak-russian-providers

```bash 
mkdir -p keycloak/providers

wget -O keycloak-russian-providers-21.1.1.rsp.jar \
  https://repo1.maven.org/maven2/ru/playa/keycloak/keycloak-russian-providers/21.1.1.rsp/keycloak-russian-providers-21.1.1.rsp.jar

wget -O keycloak/providers/json-path-2.7.0.jar \
  https://repo1.maven.org/maven2/com/jayway/jsonpath/json-path/2.7.0/json-path-2.7.0.jar

wget -O keycloak/providers/json-smart-2.4.7.jar \
  https://repo1.maven.org/maven2/net/minidev/json-smart/2.4.7/json-smart-2.4.7.jar

wget -O keycloak/providers/accessors-smart-2.4.7.jar \
  https://repo1.maven.org/maven2/net/minidev/accessors-smart/2.4.7/accessors-smart-2.4.7.jar

wget -O keycloak/providers/asm-9.3.jar \
  https://repo1.maven.org/maven2/org/ow2/asm/asm/9.3/asm-9.3.jar
  
docker compose up --build -d
```

## Задание 2. Разработка сервиса отчётов
### Задача 1. Создать архитектуру решения для подготовки и получения отчётов.

![c4_container_model_reports](schemas/BionicPRO_C4_model.drawio.png)

### Задача 2. Разработать Airflow DAG и настроить его на запуск по расписанию.
#### Диаграмма последовательности процесса ETL
![airflow-etl-sequence](schemas/airflow-etl-sequence.png)

### Задача 3. Создайте бэкенд-часть приложения для API.
### Задача 4. Реализуйте ограничение доступа к эндпоинту отчётности.
### Задача 5. Добавьте в UI кнопку получения отчёта и вызова эндпоинта его генерации.

```bash
docker compose up --build -d
```

#### Тестовые пользователи (ldap)
- rebecca.harmon / password
- david.richards / password

![reports-screenshot](reports-screenshot.png)

#### Диаграмма последовательности получения отчетов и валидации\ротации сессии
![get-report-sequence](schemas/get-report-sequence.png)

## Задание 3. Снижение нагрузки на базу данных
не успеваю по срокам :(

## Задание 4. Повышение оперативности и стабильности работы CRM
не успеваю по срокам :(