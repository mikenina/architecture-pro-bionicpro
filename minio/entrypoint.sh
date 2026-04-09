#!/bin/sh

minio server --console-address ":9001" /data &

sleep 5

curl -sL https://dl.min.io/client/mc/release/linux-amd64/mc -o /tmp/mc
chmod +x /tmp/mc
/tmp/mc alias set local http://localhost:9000 minio_user minio_password
/tmp/mc anonymous set download local/reports

echo "Minio started and bucket 'reports' is public"

wait