import asyncio
import json
import logging
import os
import re
import tempfile
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import soundfile as sf
from vosk import KaldiRecognizer, Model

VOSK_AVAILABLE = True

import uvicorn
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level), format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {'.mp3', '.wav', '.m4a', '.flac', '.ogg', '.mp4', '.avi', '.mov', '.mkv', '.opus'}

vosk_model = None

# Global semaphore to limit concurrent transcription jobs
MAX_CONCURRENT_TRANSCRIPTIONS = int(os.getenv("MAX_CONCURRENT_TRANSCRIPTIONS", 1))  # Default to 1
transcription_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TRANSCRIPTIONS)


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        if websocket.client_state == 3: # WebSocketState.DISCONNECTED
            self.disconnect(websocket)
            return
        try:
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"Error sending message to WebSocket: {e}")
            self.disconnect(websocket)

    async def broadcast(self, message: str):
        disconnected = []
        for connection in self.active_connections[:]:  # Create a copy
            if connection.client_state == 3: # WebSocketState.DISCONNECTED
                disconnected.append(connection)
                continue
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to WebSocket: {e}")
                disconnected.append(connection)

        # Remove disconnected connections
        for connection in disconnected:
            self.disconnect(connection)


manager = ConnectionManager()


class JobStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TranscriptionJob:
    job_id: str
    filename: str
    model: str
    language: str
    status: JobStatus
    position: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict] = None
    error: Optional[str] = None
    temp_file_path: Optional[str] = None


class JobQueue:
    def __init__(self):
        self.queue = deque()
        self.jobs = {}  # job_id -> TranscriptionJob
        self.processing = False
        self.lock = asyncio.Lock()

    async def add_job(self, job: TranscriptionJob) -> int:
        async with self.lock:
            position = len(self.queue) + 1
            job.position = position
            self.queue.append(job.job_id)
            self.jobs[job.job_id] = job
            logger.info(f"Added job {job.job_id} to queue at position {position}")
            return position

    async def get_job(self, job_id: str) -> Optional[TranscriptionJob]:
        return self.jobs.get(job_id)

    async def get_queue_position(self, job_id: str) -> Optional[int]:
        if job_id not in self.jobs:
            return None

        job = self.jobs[job_id]
        if job.status == JobStatus.COMPLETED or job.status == JobStatus.FAILED:
            return 0

        position = 1
        for queued_job_id in self.queue:
            if queued_job_id == job_id:
                return position
            if self.jobs[queued_job_id].status == JobStatus.PENDING:
                position += 1

        return None

    async def get_next_job(self) -> Optional[TranscriptionJob]:
        async with self.lock:
            if not self.queue:
                return None

            job_id = self.queue.popleft()
            job = self.jobs.get(job_id)
            if job and job.status == JobStatus.PENDING:
                job.status = JobStatus.PROCESSING
                job.started_at = datetime.now()
                logger.info(f"Started processing job {job_id}")
                return job

            return None

    async def complete_job(self, job_id: str, result: Dict, error: Optional[str] = None):
        if job_id in self.jobs:
            job = self.jobs[job_id]
            job.completed_at = datetime.now()

            if error:
                job.status = JobStatus.FAILED
                job.error = error
                logger.error(f"Job {job_id} failed: {error}")
            else:
                job.status = JobStatus.COMPLETED
                job.result = result
                logger.info(f"Job {job_id} completed successfully")

            await self.notify_job_update(job)

    async def notify_job_update(self, job: TranscriptionJob):
        try:
            job_data = {
                "type": "job_update",
                "job_id": job.job_id,
                "status": job.status.value,
                "filename": job.filename,
                "position": await self.get_queue_position(job.job_id),
                "timestamp": datetime.now().isoformat(),
            }

            if job.status == JobStatus.COMPLETED and job.result:
                job_data["result"] = job.result
            elif job.status == JobStatus.FAILED and job.error:
                job_data["error"] = job.error

            await manager.broadcast(json.dumps(job_data))
            logger.info(f"Broadcasted job update for {job.job_id}: {job.status.value}")
        except Exception as e:
            logger.error(f"Error broadcasting job update: {e}")

    async def notify_job_progress(self, job_id: str, message: str):
        try:
            progress_data = {"type": "job_progress", "job_id": job_id, "message": message, "timestamp": datetime.now().isoformat()}
            await manager.broadcast(json.dumps(progress_data))
            logger.info(f"Broadcasted progress for {job_id}: {message}")
        except Exception as e:
            logger.error(f"Error broadcasting job progress: {e}")

    async def notify_queue_stats(self):
        try:
            stats = await self.get_queue_stats()
            stats_data = {"type": "queue_stats", "stats": stats, "timestamp": datetime.now().isoformat()}
            await manager.broadcast(json.dumps(stats_data))
            logger.debug("Broadcasted queue stats update")
        except Exception as e:
            logger.error(f"Error broadcasting queue stats: {e}")

    async def get_queue_stats(self) -> Dict:
        pending = sum(1 for job in self.jobs.values() if job.status == JobStatus.PENDING)
        processing = sum(1 for job in self.jobs.values() if job.status == JobStatus.PROCESSING)
        completed = sum(1 for job in self.jobs.values() if job.status == JobStatus.COMPLETED)
        failed = sum(1 for job in self.jobs.values() if job.status == JobStatus.FAILED)

        return {
            "total_jobs": len(self.jobs),
            "pending": pending,
            "processing": processing,
            "completed": completed,
            "failed": failed,
            "queue_length": len(self.queue),
        }


job_queue = JobQueue()


class AudioTranscriptionAPI:
    def __init__(self):
        self.app = FastAPI(
            title="Bia Transcript API", description="Offline audio transcription using Vosk", version="1.0.0"
        )
        self.setup_middleware()
        self.setup_templates()
        self.setup_routes()
        self.model_name = "vosk-model-small-pt-0.3"  # Default model
        self.load_vosk_model()
        self.start_queue_processor()

    def load_vosk_model(self):
        global vosk_model
        model_path = f"models/{self.model_name}"
        if not os.path.exists(model_path):
            logger.error(f"Vosk model not found at {model_path}. Please download a model and place it in the 'models' directory.")
            # Exit or raise an exception if the model is critical for startup
            raise RuntimeError(f"Vosk model not found at {model_path}")
        logger.info(f"Loading Vosk model: {self.model_name}")
        vosk_model = Model(model_path)

    def setup_middleware(self):
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def setup_templates(self):
        self.templates = Jinja2Templates(directory="templates")

    def start_queue_processor(self):
        pass

    async def process_queue(self):
        while True:
            try:
                job = await job_queue.get_next_job()
                if job:
                    asyncio.create_task(self.process_transcription_job(job))
                    await job_queue.notify_queue_stats()
                else:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error in queue processor: {e}")
                await asyncio.sleep(1)

    async def process_transcription_job(self, job: TranscriptionJob):
        async with transcription_semaphore:
            try:
                global vosk_model
                if vosk_model is None:
                    error_msg = "Vosk model not loaded. This should not happen."
                    logger.error(error_msg)
                    await job_queue.complete_job(job.job_id, {}, error_msg)
                    return

                logger.info(f"Processing transcription for job {job.job_id}")
                loop = asyncio.get_event_loop()

                def transcribe():
                    audio_file = job.temp_file_path
                    data, samplerate = sf.read(audio_file, dtype='int16')
                    rec = KaldiRecognizer(vosk_model, samplerate)
                    rec.SetWords(True)

                    full_text = ""
                    segments = []
                    # Process in chunks
                    for i in range(0, len(data), 4000):
                        chunk = data[i:i+4000]
                        if rec.AcceptWaveform(chunk.tobytes()):
                            result = json.loads(rec.Result())
                            full_text += result.get('text', '') + " "
                            if 'result' in result:
                                segments.extend(result['result'])
                    result = json.loads(rec.FinalResult())
                    full_text += result.get('text', '')
                    if 'result' in result:
                        segments.extend(result['result'])

                    return full_text.strip(), segments

                transcript, segments_data = await asyncio.wait_for(
                    loop.run_in_executor(None, transcribe),
                    timeout=1800,
                )

                response_data = {
                    "success": True,
                    "filename": job.filename,
                    "model_used": self.model_name,
                    "language": job.language,
                    "transcript": transcript,
                    "raw_transcript": transcript,
                    "segments": [
                        {"start": s["start"], "end": s["end"], "text": s["word"]}
                        for s in segments_data if "start" in s
                    ],
                    "detected_language": job.language,
                    "processing_time": None,
                    "timestamp": datetime.now().isoformat(),
                    "download_url": f"/download/{job.job_id}",
                }

                await job_queue.complete_job(job.job_id, response_data)

                if job.temp_file_path and os.path.exists(job.temp_file_path):
                    os.unlink(job.temp_file_path)
                    logger.debug(f"Cleaned up temporary file: {job.temp_file_path}")

            except asyncio.TimeoutError:
                error_msg = "Job timed out during processing"
                logger.error(f"Job {job.job_id} timed out")
                await job_queue.complete_job(job.job_id, {}, error_msg)

                if job.temp_file_path and os.path.exists(job.temp_file_path):
                    os.unlink(job.temp_file_path)
            except Exception as e:
                logger.error(f"Error processing job {job.job_id}: {e}")
                await job_queue.complete_job(job.job_id, {}, str(e))

                if job.temp_file_path and os.path.exists(job.temp_file_path):
                    os.unlink(job.temp_file_path)

    def setup_routes(self):
        @self.app.get("/", response_class=HTMLResponse)
        async def root(request: Request):
            return self.templates.TemplateResponse("index.html", {"request": request})

        @self.app.get("/health")
        async def health_check():
            queue_stats = await job_queue.get_queue_stats()

            status = {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "vosk_available": VOSK_AVAILABLE,
                "model_loaded": vosk_model is not None,
                "supported_formats": list(SUPPORTED_FORMATS),
                "queue_stats": queue_stats,
            }

            if vosk_model:
                status["current_model"] = self.model_name

            return JSONResponse(content=status)

        @self.app.post("/transcribe")
        async def transcribe_audio(file: UploadFile = File(...), language: Optional[str] = "pt"):
            if not VOSK_AVAILABLE:
                raise HTTPException(status_code=500, detail="Vosk is not installed. Please install with: pip install vosk")

            file_extension = Path(file.filename).suffix.lower()
            if file_extension not in SUPPORTED_FORMATS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file format: {file_extension}. " f"Supported formats: {', '.join(SUPPORTED_FORMATS)}",
                )

            job_id = str(uuid.uuid4())
            job = TranscriptionJob(
                job_id=job_id,
                filename=file.filename,
                model=self.model_name,
                language=language,
                status=JobStatus.PENDING,
                position=0,
                created_at=datetime.now(),
            )

            loop = asyncio.get_event_loop()

            def save_file():
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=file_extension, prefix="audio_transcription_")
                content = file.file.read()
                temp_file.write(content)
                temp_file.close()
                return temp_file.name, len(content)

            temp_file_path, content_size = await loop.run_in_executor(None, save_file)
            job.temp_file_path = temp_file_path

            logger.info(f"Created job {job_id} for file: {file.filename} ({content_size} bytes)")

            position = await job_queue.add_job(job)

            return JSONResponse(
                content={
                    "job_id": job_id,
                    "status": job.status.value,
                    "position": position,
                    "message": f"File uploaded successfully. Your job is in position {position} in the queue.",
                }
            )

        @self.app.get("/jobs/{job_id}")
        async def get_job_status(job_id: str):
            job = await job_queue.get_job(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")

            response = {
                "job_id": job_id,
                "status": job.status.value,
                "filename": job.filename,
                "model": job.model,
                "language": job.language,
                "created_at": job.created_at.isoformat(),
                "position": await job_queue.get_queue_position(job_id),
            }

            if job.started_at:
                response["started_at"] = job.started_at.isoformat()

            if job.completed_at:
                response["completed_at"] = job.completed_at.isoformat()

            if job.status == JobStatus.COMPLETED and job.result:
                response["result"] = job.result
            elif job.status == JobStatus.FAILED and job.error:
                response["error"] = job.error

            return JSONResponse(content=response)

        @self.app.get("/queue/stats")
        async def get_queue_stats():
            stats = await job_queue.get_queue_stats()
            return JSONResponse(content=stats)

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await manager.connect(websocket)
            try:
                stats = await job_queue.get_queue_stats()
                initial_data = {"type": "queue_stats", "stats": stats, "timestamp": datetime.now().isoformat()}
                await manager.send_personal_message(json.dumps(initial_data), websocket)

                while True:
                    try:
                        data = await websocket.receive_text()
                        message = json.loads(data)

                        if message.get("type") == "subscribe_job":
                            job_id = message.get("job_id")
                            if job_id:
                                job = await job_queue.get_job(job_id)
                                if job:
                                    job_data = {
                                        "type": "job_update",
                                        "job_id": job.job_id,
                                        "status": job.status.value,
                                        "filename": job.filename,
                                        "position": await job_queue.get_queue_position(job.job_id),
                                        "timestamp": datetime.now().isoformat(),
                                    }

                                    if job.status == JobStatus.COMPLETED and job.result:
                                        job_data["result"] = job.result
                                    elif job.status == JobStatus.FAILED and job.error:
                                        job_data["error"] = job.error

                                    await manager.send_personal_message(json.dumps(job_data), websocket)
                                    logger.info(f"Sent job status to WebSocket for job {job_id}")

                    except WebSocketDisconnect:
                        manager.disconnect(websocket)
                        break
                    except Exception as e:
                        logger.error(f"WebSocket error: {e}")
                        break

            except WebSocketDisconnect:
                manager.disconnect(websocket)
            except Exception as e:
                logger.error(f"WebSocket connection error: {e}")
                manager.disconnect(websocket)

        @self.app.get("/download/{job_id}")
        async def download_transcript(job_id: str):
            job = await job_queue.get_job(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")

            if job.status != JobStatus.COMPLETED or not job.result:
                raise HTTPException(status_code=400, detail="Job not completed or no result available")

            transcript = job.result.get("transcript", "")
            filename = job.filename
            base_name = Path(filename).stem

            content = transcript
            file_extension = ".txt"

            download_filename = f"{base_name}_transcript{file_extension}"

            temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=file_extension, prefix="transcript_")

            temp_file.write(content)
            temp_file.close()

            return FileResponse(path=temp_file.name, filename=download_filename, media_type="text/plain")


def cleanup_temp_file(file_path: str):
    if os.path.exists(file_path):
        os.unlink(file_path)
        logger.debug(f"Cleaned up temporary file: {file_path}")


api = AudioTranscriptionAPI()
app = api.app

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(api.process_queue())
    logger.info("Queue processor started")
