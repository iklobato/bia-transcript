# Bia Transcript

A FastAPI service for offline audio transcription using OpenAI Whisper with multi-language support.

## Features

- Upload audio files (MP3, WAV, M4A, FLAC, OGG, MP4, AVI, MOV, MKV)
- Offline transcription using Whisper Base model (better quality)
- Enhanced transcription with multi-language support

- Multi-language support
- Conversation transcript formatting
- Error handling and validation
- **Async queue processing** for multiple simultaneous requests
- **Job status tracking** with real-time updates
- **Queue position monitoring** for users
- **Background processing** with automatic cleanup
- **Non-blocking HTTP requests** - file uploads return immediately
- **Thread pool execution** for CPU-intensive transcription tasks
- **Timeout protection** - prevents jobs from getting stuck indefinitely
- **WebSocket real-time updates** - instant status notifications without polling
- **Automatic download** - transcript files download automatically when completed

## Project Structure

```
bia-transcript/
├── app.py              # Backend API logic
├── templates/
│   └── index.html      # Frontend documentation page
├── pyproject.toml      # Poetry configuration and dependencies
├── poetry.lock         # Locked dependency versions
├── run.py              # Application runner script
└── README.md          # Project documentation
```

## Installation

### Local Development

1. Install dependencies using Poetry:
```bash
poetry install
```

2. Install Whisper (if not already installed):
```bash
# Install Whisper using pip in the Poetry environment:
poetry run pip install openai-whisper

# Note: If you encounter NumPy compatibility issues, downgrade NumPy:
poetry run pip install "numpy<2"
```

3. Run the application:
```bash
# Option 1: Using Poetry directly
poetry run python app.py

# Option 2: Using the run script
./run.py

# Option 3: Activate Poetry shell and run
poetry shell
python app.py
```

### Docker Deployment

1. Build the Docker image:
```bash
docker build -t bia-transcript .
```

2. Run the container:
```bash
docker run -p 8000:8000 bia-transcript
```

### DigitalOcean App Platform Deployment

1. Push your code to GitHub
2. Connect your repository to DigitalOcean App Platform
3. Use the provided `do-app.yaml` configuration
4. Deploy with:
```bash
doctl apps create --spec do-app.yaml
```

Or use the DigitalOcean web interface to deploy from your GitHub repository.

## API Endpoints

- `GET /` - API documentation page
- `POST /transcribe` - Submit audio file for transcription (returns job ID)
  - Parameters: `file`, `model`, `language`
- `GET /jobs/{job_id}` - Get job status and result
- `GET /health` - Health check endpoint with queue statistics
- `GET /queue/stats` - Get queue statistics
- `GET /docs` - Interactive API documentation (Swagger UI)
- `WS /ws` - WebSocket endpoint for real-time updates
- `GET /download/{job_id}` - Download transcription result

## Usage Example

### Submit a transcription job:
```bash
curl -X POST "http://localhost:8000/transcribe" \
     -F "file=@audio.mp3" \
     -F "model=base" \
     -F "language=pt"
```

### Check job status:
```bash
curl "http://localhost:8000/jobs/{job_id}"
```

### Get queue statistics:
```bash
curl "http://localhost:8000/queue/stats"
```

### WebSocket real-time updates:
```javascript
// Connect to WebSocket
const ws = new WebSocket('ws://localhost:8000/ws');

// Subscribe to job updates
ws.send(JSON.stringify({
    type: 'subscribe_job',
    job_id: 'your-job-id'
}));

// Listen for updates
ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    if (data.type === 'job_update') {
        console.log('Job status:', data.status);
    } else if (data.type === 'queue_stats') {
        console.log('Queue stats:', data.stats);
    }
};
```

## Supported Formats

MP3, WAV, M4A, FLAC, OGG, MP4, AVI, MOV, MKV

## Model

- **Base**: Good balance of speed and accuracy (~74MB) - Default
- **Small**: Better accuracy (~244MB) - Available for higher quality
- **Medium**: High accuracy (~769MB) - Available for highest quality
- **Large**: Best accuracy (~1550MB) - Available for maximum quality 