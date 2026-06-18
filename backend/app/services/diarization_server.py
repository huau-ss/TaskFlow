"""
说话人分离 (Speaker Diarization) 服务

使用 pyannote-audio 进行精准的说话人边界检测。
CPU 模式运行（无 GPU），处理速度较慢但质量可靠。

启动：python -m app.services.diarization_server
端口：8004
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, UploadFile

logger = logging.getLogger(__name__)

app = FastAPI(title="Speaker Diarization Service", version="1.1")

# 全局 pipeline（懒加载）
_pipeline = None


def get_pipeline():
    """懒加载 pyannote diarization pipeline"""
    global _pipeline
    if _pipeline is None:
        logger.info("Loading pyannote speaker diarization pipeline...")
        from pyannote.audio import Pipeline

        # HuggingFace token（如果需要访问 gated model）
        hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or None

        _pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=hf_token,
        )
        import torch
        _pipeline.to(torch.device("cpu"))
        logger.info("Diarization pipeline loaded on CPU.")
    return _pipeline


def _load_audio(wav_path: str) -> tuple:
    """
    加载音频文件，返回 (waveform_tensor, sample_rate)。

    优先使用 soundfile（避免 torchcodec 兼容问题），其次用 torchaudio。
    """
    # soundfile 优先（更稳定，不需要 FFmpeg 动态库）
    try:
        import soundfile as sf
        import torch
        wav, sr = sf.read(wav_path, dtype="float32")
        if len(wav.shape) > 1:
            wav = wav.mean(axis=1)
        waveform = torch.from_numpy(wav).unsqueeze(0)
        return waveform, sr
    except Exception:
        pass

    # fallback: torchaudio
    try:
        import torchaudio
        waveform, sr = torchaudio.load(wav_path)
        return waveform, sr
    except Exception:
        pass

    raise RuntimeError("无法加载音频文件：soundfile 和 torchaudio 均不可用")


def _ensure_wav_16k(audio_path: str) -> str:
    """确保音频为 16kHz mono WAV"""
    out_path = audio_path + ".16k.wav"
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path,
         "-ar", "16000", "-ac", "1", "-f", "wav", out_path],
        capture_output=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr.decode()}")
    return out_path


@app.get("/health")
async def health():
    return {"status": "ok", "model": "pyannote-3.1", "device": "cpu"}


@app.post("/api/diarize")
async def diarize(file: UploadFile = File(...)):
    """
    对上传的音频进行说话人分离。

    返回每个说话人的时间段列表：
    {
        "segments": [
            {"speaker": "SPEAKER_00", "start": 0.5, "end": 12.3},
            {"speaker": "SPEAKER_01", "start": 12.8, "end": 25.1},
            ...
        ],
        "num_speakers": 2,
        "duration": 60.0
    }
    """
    content = await file.read()
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    wav_path = None
    try:
        # 转换为 16kHz WAV
        wav_path = _ensure_wav_16k(tmp_path)

        # 加载音频
        waveform, sample_rate = _load_audio(wav_path)

        # 如果需要，重采样到 16kHz
        if sample_rate != 16000:
            import torchaudio.functional as F
            waveform = F.resample(waveform, sample_rate, 16000)
            sample_rate = 16000

        # 转为 mono
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)

        # 运行 diarization
        pipeline = get_pipeline()
        output = pipeline({"waveform": waveform, "sample_rate": sample_rate})

        # pyannote 4.x 返回 DiarizeOutput，用 serialize() 获取结构化数据
        result = output.serialize()

        segments = result.get("diarization", [])
        # 统一字段名
        for seg in segments:
            seg["start"] = round(seg["start"], 2)
            seg["end"] = round(seg["end"], 2)

        # 获取音频时长
        duration = waveform.shape[1] / sample_rate

        # 统计说话人数量
        speakers = set(s["speaker"] for s in segments)

        return {
            "segments": segments,
            "num_speakers": len(speakers),
            "duration": round(duration, 2),
        }

    except Exception as e:
        logger.error(f"Diarization failed: {e}")
        raise
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if wav_path:
            Path(wav_path).unlink(missing_ok=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
