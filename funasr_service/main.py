"""
FunASR 统一语音服务 — ASR + 说话人分离 + 标点恢复（联合推理）。

端点:
  GET  /health              健康检查
  POST /api/transcribe      完整转写 (VAD → paraformer ASR → CAM++ spk → 标点)
  POST /api/embeddings      纯声纹提取 (注册用，CAM++ 单次推理)

启动: uvicorn main:app --host 0.0.0.0 --port 8005

v2.0 → v3.0 变更：
  - 用 FunASR 联合推理（paraformer + vad + spk + punc）替换旧的
    VAD → 合并段 → CAM++ embedding → AgglomerativeClustering 管线
  - 联合模型一次推理同时完成 ASR + 说话人分离 + 标点恢复
  - 说话人分离质量显著提升，尤其适合 3-6 人会议场景
"""

import gc
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── 模型路径 ──
ASR_MODEL = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
VAD_MODEL = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
PUNC_MODEL = "iic/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727"
SPK_MODEL = "iic/speech_campplus_sv_zh-cn_16k-common"

# ── OOM 防护：单次处理最大音频时长（秒）──
_MAX_AUDIO_DURATION = 7200.0  # 2 小时，防止超长会议 OOM

app = FastAPI(title="FunASR Service", version="3.0")

# ── 延迟加载 ──
_model: Any = None
_spk_model: Any = None  # 独立 CAM++ 模型（用于 /api/embeddings 注册端点）
_models_loaded = False
_load_error: str | None = None


def _load_models():
    """加载 FunASR 联合模型 + 独立 CAM++（用于声纹注册）。"""
    global _model, _spk_model, _models_loaded, _load_error
    if _models_loaded:
        return
    try:
        from funasr import AutoModel

        logger.info("加载 FunASR 联合模型 (paraformer + vad + spk + punc)...")
        _model = AutoModel(
            model=ASR_MODEL,
            vad_model=VAD_MODEL,
            punc_model=PUNC_MODEL,
            spk_model=SPK_MODEL,
            device="cpu",
            ncpu=4,
            disable_update=True,
        )
        logger.info("联合模型加载完成")

        # 独立 CAM++ 模型用于 /api/embeddings（声纹注册）
        logger.info("加载独立 CAM++ 声纹模型...")
        _spk_model = AutoModel(
            model=SPK_MODEL,
            device="cpu",
            disable_update=True,
        )
        logger.info("独立 CAM++ 模型加载完成")

        _models_loaded = True
    except Exception as e:
        _load_error = str(e)
        logger.error(f"模型加载失败: {e}")
        raise


@app.on_event("startup")
async def startup():
    try:
        _load_models()
    except Exception:
        logger.warning("模型将在首次请求时加载")


@app.get("/health")
async def health():
    return {
        "status": "ok" if _models_loaded else "loading",
        "models": {
            "joint": f"{ASR_MODEL} + {VAD_MODEL} + {SPK_MODEL} + {PUNC_MODEL}",
            "spk_standalone": SPK_MODEL,
        },
        "device": "cpu",
        "version": "3.0",
        "error": _load_error,
    }


# ────────── 辅助函数 ──────────


def _audio_to_wav(src: str | Path, dst: Path) -> bool:
    """用 ffmpeg 转为 16kHz mono WAV。返回是否成功。"""
    import subprocess
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", "-f", "wav", str(dst)],
        capture_output=True, timeout=60,
    )
    return r.returncode == 0


def _get_audio_duration(wav_path: str | Path) -> float:
    """用 soundfile 获取音频时长（秒）。"""
    import soundfile as sf
    wav, sr = sf.read(wav_path, dtype="float32")
    return len(wav) / sr if sr > 0 else 0.0


def _speaker_id_to_letter(speaker_id: str) -> str:
    """将 SPEAKER_00, SPEAKER_01 等转换为 A, B, C, ... 字母标识。"""
    try:
        idx = int(speaker_id.rsplit("_", 1)[-1])
        return chr(ord("A") + idx)
    except (ValueError, IndexError):
        return speaker_id


# ────────── API ──────────


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """
    完整转写 pipeline（联合推理 v3.0）：
    1. 音频转 16kHz mono WAV
    2. FunASR 联合推理（VAD + ASR + 说话人分离 + 标点）
    3. 格式化为后端兼容的 segment 列表

    返回格式与 v2.0 兼容：
    {
        "segments": [
            {
                "speaker_label": "SPEAKER_00",
                "text": "转写文本",
                "start_time": 0.0,
                "end_time": 5.2,
                "sequence": 0
            },
            ...
        ],
        "num_speakers": 3,
        "duration": 12.5
    }
    """
    global _model

    if not _models_loaded:
        _load_models()

    t0 = time.time()

    # 保存上传文件
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    raw = __import__("tempfile").NamedTemporaryFile(suffix=suffix, delete=False)
    raw.write(await file.read())
    raw.close()

    wav_path = raw.name + ".wav"
    if not _audio_to_wav(raw.name, Path(wav_path)):
        Path(raw.name).unlink(missing_ok=True)
        raise HTTPException(500, "音频格式转换失败")

    try:
        # 检查时长
        duration = _get_audio_duration(wav_path)
        if duration > _MAX_AUDIO_DURATION:
            raise HTTPException(
                400,
                f"音频过长 ({duration:.0f}s > {_MAX_AUDIO_DURATION}s)，不支持处理"
            )

        logger.info(f"转写开始: {Path(file.filename or '').name}, {duration:.1f}s")

        # ── FunASR 联合推理 ──
        # 2pass 模式：chunk_size=[0, 10, 5] 表示
        #   - 首个 chunk 为 0s（全量处理）
        #   - 后续 chunk 按 10s 窗口，5s 步长
        result = _model.generate(
            input=wav_path,
            batch_size_s=300,
            hotword="",
            is_final=True,
            return_timestamp=True,
        )

        if not result or len(result) == 0:
            # 没有检测到任何语音 → 返回空结果
            logger.info("未检测到有效语音，返回空结果")
            return {"segments": [], "num_speakers": 0, "duration": time.time() - t0}

        # ── 解析联合模型输出 ──
        # FunASR 联合模型返回格式（单人场景可能无 speaker 字段）：
        # [{
        #     "text": "转写文本",
        #     "timestamp": [[start_ms, end_ms], ...],
        #     "speaker_id": "SPEAKER_00"  (仅多人场景有)
        # }, ...]

        segments = []
        speaker_set = set()

        for item_idx, item in enumerate(result):
            if not isinstance(item, dict):
                continue

            text = (item.get("text") or "").strip()
            if not text:
                continue

            # 说话人 ID（多人场景才有，单人场景默认 SPEAKER_00）
            speaker_id = item.get("speaker_id") or item.get("speaker") or "SPEAKER_00"
            speaker_set.add(speaker_id)

            # 时间戳：可能是 [[start_ms, end_ms], ...] 列表或 [[start_ms, end_ms]]
            timestamps = item.get("timestamp")
            start_time = 0.0
            end_time = 0.0

            if timestamps and isinstance(timestamps, list) and len(timestamps) > 0:
                # 取首个时间戳的 start 和最后一个的 end
                first_ts = timestamps[0]
                last_ts = timestamps[-1]
                if isinstance(first_ts, (list, tuple)) and len(first_ts) >= 2:
                    start_time = first_ts[0] / 1000.0
                if isinstance(last_ts, (list, tuple)) and len(last_ts) >= 2:
                    end_time = last_ts[1] / 1000.0

            segments.append({
                "speaker_label": speaker_id,
                "text": text,
                "start_time": round(start_time, 2),
                "end_time": round(end_time, 2),
                "sequence": item_idx,
            })

        num_speakers = max(1, len(speaker_set))

        elapsed = time.time() - t0
        logger.info(
            f"转写完成: {len(segments)} 段, {num_speakers} 说话人, {elapsed:.1f}s"
        )

        return {
            "segments": segments,
            "num_speakers": num_speakers,
            "duration": elapsed,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("转写失败")
        raise HTTPException(500, str(e))
    finally:
        Path(raw.name).unlink(missing_ok=True)
        Path(wav_path).unlink(missing_ok=True)
        gc.collect()


@app.post("/api/embeddings")
async def extract_embedding(file: UploadFile = File(...)):
    """
    纯声纹提取 — 用于注册。
    返回 CAM++ spk_embedding 向量。
    """
    if not _models_loaded:
        _load_models()

    import soundfile as sf
    import tempfile

    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    raw = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    raw.write(await file.read())
    raw.close()

    wav_path = raw.name + ".wav"
    if not _audio_to_wav(raw.name, Path(wav_path)):
        Path(raw.name).unlink(missing_ok=True)
        raise HTTPException(500, "音频格式转换失败")

    try:
        result = _spk_model.generate(input=wav_path)
        embedding = None
        if result and len(result) > 0:
            emb_data = result[0].get("spk_embedding")
            if emb_data is not None:
                if hasattr(emb_data, "tolist"):
                    emb_list = emb_data.tolist()
                    if isinstance(emb_list, list) and len(emb_list) == 1 and isinstance(emb_list[0], list):
                        emb_list = emb_list[0]
                    embedding = emb_list
                elif isinstance(emb_data, list):
                    embedding = emb_data

        if not embedding:
            raise HTTPException(422, "无法提取声纹特征")

        wav, sr = sf.read(wav_path, dtype="float32")
        duration = float(len(wav) / sr) if sr > 0 else 0.0

        logger.info(f"CAM++ 提取 {len(embedding)}-dim embedding, 时长 {duration:.1f}s")
        return {"embedding": embedding, "duration": duration}

    finally:
        Path(raw.name).unlink(missing_ok=True)
        Path(wav_path).unlink(missing_ok=True)
