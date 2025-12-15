# -------- Base Image --------
FROM python:3.11-slim

# -------- Environment --------
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# -------- System deps --------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        aria2 \
        ca-certificates \
        tzdata && \
    rm -rf /var/lib/apt/lists/*

# -------- Workdir --------
WORKDIR /app

# -------- Python deps --------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# -------- App code --------
COPY . .

# -------- Create downloads dir --------
RUN mkdir -p downloads

# -------- Expose Flask port --------
EXPOSE 8000

# -------- Start --------
CMD ["python", "bot.py"]
