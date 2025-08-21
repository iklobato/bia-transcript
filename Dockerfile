# Stage 1: Build the application
FROM python:3.9-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends build-essential wget unzip ffmpeg libsndfile1 libffi-dev patchelf

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir vosk


# Copy the application code
COPY . .

# Download and extract the Vosk model
RUN mkdir -p models && \
    cd models && \
    wget https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip && \
    unzip -o vosk-model-small-pt-0.3.zip && \
    rm vosk-model-small-pt-0.3.zip

# Stage 2: Create the final image
FROM python:3.9-slim

WORKDIR /app

# Install libsndfile1 in the final stage (as root)
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1

# Create a non-root user
RUN useradd --create-home appuser
USER appuser
ENV PATH="/home/appuser/.local/bin:$PATH"

# Install gunicorn in the final stage
RUN pip install --no-cache-dir gunicorn

# Copy installed dependencies and application code from the builder stage
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=builder /app .

# Expose the port the app runs on
EXPOSE 8000

# Set the command to run the application
CMD ["gunicorn", "-w", "1", "-k", "uvicorn.workers.UvicornWorker", "app:app"]