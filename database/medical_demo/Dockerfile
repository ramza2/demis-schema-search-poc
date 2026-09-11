FROM postgres:16-alpine

RUN apk add --no-cache python3 py3-pip \
    && pip3 install --no-cache-dir --break-system-packages "psycopg[binary]==3.2.13"

COPY init/ /docker-entrypoint-initdb.d/
COPY seed/seed_medical_demo.py /opt/medical_demo/seed_medical_demo.py
COPY seed/04_seed.sh /docker-entrypoint-initdb.d/04_seed.sh

RUN chmod +x /docker-entrypoint-initdb.d/04_seed.sh
