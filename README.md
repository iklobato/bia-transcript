# Bia Transcript

A FastAPI service for offline audio transcription using Vosk with multi-language support.

## Features

- Upload audio files (MP3, WAV, M4A, FLAC, OGG, OPUS, MP4, AVI, MOV, MKV)
- Offline transcription using Vosk models
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

2. Download Vosk models:
   - Create a `models` directory in the root of the project.
   - Download the desired Vosk models from [https://alphacephei.com/vosk/models](https://alphacephei.com/vosk/models).
   - Extract the model archives and place the model directories inside the `models` directory. For example, for the Portuguese model, you would have `models/vosk-model-small-pt-0.3`.

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
curl -X POST "http://localhost:8000/transcribe" 
     -F "file=@audio.mp3" 
     -F "model=vosk-model-small-pt-0.3" 
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

MP3, WAV, M4A, FLAC, OGG, OPUS, MP4, AVI, MOV, MKV

Note: Compressed formats (e.g., OPUS, MP3, OGG, M4A) are automatically transcoded to 16kHz mono WAV via ffmpeg for optimal Vosk accuracy.

## Model

- **Vosk Models**: A variety of models for different languages and sizes are available from the [Vosk website](https://alphacephei.com/vosk/models). The default model is `vosk-model-small-pt-0.3`.

``` 