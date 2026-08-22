FROM python:3.11-slim

WORKDIR /app
RUN apt-get update \
	&& apt-get install -y --no-install-recommends ca-certificates curl unzip \
	&& curl -fsSL https://gu-st.ru/content/lending/linux_russian_trusted_root_ca_pem.zip -o /tmp/root-ca.zip \
	&& curl -fsSL https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.zip -o /tmp/sub-ca.zip \
	&& mkdir -p /usr/local/share/ca-certificates/mincifry \
	&& unzip -jo /tmp/root-ca.zip '*.crt' -d /usr/local/share/ca-certificates/mincifry \
	&& unzip -jo /tmp/sub-ca.zip '*.crt' -d /usr/local/share/ca-certificates/mincifry \
	&& update-ca-certificates \
	&& rm -rf /tmp/root-ca.zip /tmp/sub-ca.zip \
	&& rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p /app/data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
