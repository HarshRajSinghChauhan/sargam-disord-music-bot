FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

# Install ffmpeg and other necessary system packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir --upgrade yt-dlp

# Copy the rest of the application
COPY . .

# Command to run the bot
CMD ["python", "bot.py"]
