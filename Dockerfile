FROM python:3.11-slim

WORKDIR /app

# Install git + build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app
COPY . .

# Git identity (for commits from inside container)
RUN git config --global user.email "earick@earick.local" && \
    git config --global user.name "Earick Dream" && \
    git config --global --add safe.directory /app

ENV PORT=7860
EXPOSE 7860

CMD ["python", "app.py"]
