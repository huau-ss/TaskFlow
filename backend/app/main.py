from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, employees, meetings, voiceprints, messages, tasks, transcripts
from app.schemas import HealthResponse
from app.services.health import check_asr_health, check_diarization_health, check_llm_health


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.nas_path).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="TaskFlow API", version="0.1.0", lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(employees.router)
app.include_router(meetings.router)
app.include_router(voiceprints.router)
app.include_router(messages.router)
app.include_router(tasks.router)
app.include_router(transcripts.router)


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        asr_diarize_url=settings.asr_diarize_url,
        llm_url=settings.llm_url,
        diarization_url=settings.diarization_url,
    )


@app.get("/health/services")
async def health_services():
    asr = await check_asr_health()
    llm = await check_llm_health()
    diarization = await check_diarization_health()
    return {"asr": asr, "llm": llm, "diarization": diarization}
