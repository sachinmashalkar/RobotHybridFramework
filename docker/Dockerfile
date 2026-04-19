# Runtime image for executing the Robot Hybrid Framework inside CI or a grid.
# Ships Python + Chrome so suites can run headlessly without extra setup.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl wget gnupg ca-certificates unzip \
      fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
      libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 \
      libnss3 libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 \
      libxrandr2 xdg-utils \
 && curl -sSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb \
 && apt-get install -y /tmp/chrome.deb \
 && rm -f /tmp/chrome.deb \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/framework
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

ENV PATH="/opt/framework/scripts:${PATH}"
CMD ["bash", "scripts/run_tests.sh", "--browser", "headlesschrome"]
