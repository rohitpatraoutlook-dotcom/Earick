FROM python:3.11-slim

WORKDIR /app

# Install git — needed for dream mode to push to GitHub
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Git identity for dream mode commits
RUN git config --global user.email "earick@earick.local" && \
    git config --global user.name "Earick Dream" && \
    git config --global --add safe.directory /app

ENV PORT=7860
EXPOSE 7860

CMD ["python", "app.py"]

