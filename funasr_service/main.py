"""
FunASR 统一语音服务 — ASR + 说话人分离 + CAM++ 声纹 embedding.

端点:
  GET  /health              健康检查
  POST /api/transcribe      完整转写 (VAD → paraformer ASR → CAM++ embedding → 说话人聚类)
  POST /api/embeddings      纯声纹提取 (注册用，CAM++ 单次推理)

启动: uvicorn main:app --host 0.0.0.0 --port 8005
"""

import logging
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, HTTPException, UploadFile
from funasr import AutoModel
from sklearn.cluster import AgglomerativeClustering

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="FunASR Service", version="2.0")

# ── 模型路径 ──
VAD_MODEL = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
ASR_MODEL = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
SPK_MODEL = "iic/speech_campplus_sv_zh-cn_16k-common"

# ── 延迟加载 ──
_vad: AutoModel | None = None
_asr: AutoModel | None = None
_spk: AutoModel | None = None
_models_loaded = False
_load_error: str | None = None


def _load_models():
    global _vad, _asr, _spk, _models_loaded, _load_error
    if _models_loaded:
        return
    try:
        logger.info("加载 VAD 模型...")
        _vad = AutoModel(model=VAD_MODEL, device="cpu", disable_update=True)
        logger.info("加载 ASR 模型 (paraformer)...")
        _asr = AutoModel(model=ASR_MODEL, device="cpu", ncpu=4, disable_update=True)
        logger.info("加载 CAM++ 声纹模型...")
        _spk = AutoModel(model=SPK_MODEL, device="cpu", disable_update=True)
        _models_loaded = True
        logger.info("所有模型加载完成")
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
        "models": {"vad": VAD_MODEL, "asr": ASR_MODEL, "spk": SPK_MODEL},
        "device": "cpu",
        "error": _load_error,
    }


# ────────── 辅助 ──────────


def _audio_to_wav(src: str | Path, dst: Path) -> bool:
    """用 ffmpeg 转为 16kHz mono WAV。返回是否成功。"""
    import subprocess
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", "-f", "wav", str(dst)],
        capture_output=True, timeout=60,
    )
    return r.returncode == 0


def _merge_vad_segments(segments: list[dict], max_gap: float = 2.0, min_dur: float = 0.5) -> list[dict]:
    """合并相邻 VAD 段（间隔 < max_gap 秒且 duration >= min_dur）。"""
    if not segments:
        return []
    merged = [dict(segments[0])]
    for seg in segments[1:]:
        gap = seg["start"] - merged[-1]["end"]
        if gap <= max_gap:
            merged[-1]["end"] = seg["end"]
        else:
            # 跳过过短的非语音段
            dur = merged[-1]["end"] - merged[-1]["start"]
            if dur < min_dur:
                merged[-1] = seg  # 替换
            else:
                merged.append(dict(seg))
    # 检查最后一个
    dur = merged[-1]["end"] - merged[-1]["start"]
    if dur < min_dur and len(merged) > 1:
        merged.pop()
    return merged


# ────────── API ──────────


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """
    完整转写 pipeline：
    1. VAD 检测语音段
    2. 合并相邻段
    3. 每个段切片 → paraformer ASR → CAM++ embedding
    4. 说话人聚类
    """
    if not _models_loaded:
        _load_models()

    t0 = time.time()

    # 保存上传文件
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    raw = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    raw.write(await file.read())
    raw.close()

    wav_path = raw.name + ".wav"
    if not _audio_to_wav(raw.name, Path(wav_path)):
        Path(raw.name).unlink(missing_ok=True)
        raise HTTPException(500, "音频格式转换失败")

    try:
        # ── Step 1: VAD ──
        vad_result = _vad.generate(input=wav_path)
        vad_segments: list[dict] = []
        if vad_result and len(vad_result) > 0:
            # VAD 返回 [{"value": [[start_ms, end_ms], ...], ...}]
            vad_data = vad_result[0]
            intervals = vad_data.get("value", [])
            for iv in intervals:
                if len(iv) >= 2 and iv[1] > iv[0]:
                    vad_segments.append({
                        "start": iv[0] / 1000.0,
                        "end": iv[1] / 1000.0,
                    })

        if not vad_segments:
            # 没有检测到语音 → 整段处理
            wav, sr = sf.read(wav_path, dtype="float32")
            dur = len(wav) / sr if sr > 0 else 0
            vad_segments = [{"start": 0.0, "end": dur}]

        # 合并相邻段
        merged = _merge_vad_segments(vad_segments)
        logger.info(f"VAD: {len(vad_segments)} 段 → 合并为 {len(merged)} 段")

        # ── Step 2: 每段 ASR + CAM++ ──
        segments = []
        embeddings = []

        for i, seg in enumerate(merged):
            # 截取音频
            wav, sr = sf.read(wav_path, dtype="float32")
            if len(wav.shape) > 1:
                wav = wav.mean(axis=1)
            start_idx = max(0, int(seg["start"] * sr))
            end_idx = min(len(wav), int(seg["end"] * sr))
            if start_idx >= end_idx:
                continue
            sliced = wav[start_idx:end_idx]
            slice_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            sf.write(slice_path.name, sliced.astype("float32"), sr)
            slice_path.close()

            try:
                # ASR
                asr_result = _asr.generate(input=slice_path.name)
                text = ""
                if asr_result and len(asr_result) > 0:
                    text = (asr_result[0].get("text") or "").strip()

                # CAM++ embedding
                spk_result = _spk.generate(input=slice_path.name)
                emb = []
                if spk_result and len(spk_result) > 0:
                    emb_data = spk_result[0].get("spk_embedding")
                    if emb_data is not None:
                        if hasattr(emb_data, "tolist"):
                            emb = emb_data.tolist()
                            # 可能是 [[...]] 二维
                            if isinstance(emb, list) and len(emb) == 1 and isinstance(emb[0], list):
                                emb = emb[0]
                        elif isinstance(emb_data, list):
                            emb = emb_data

                if text:
                    segments.append({
                        "speaker_label": "",  # 聚类后填充
                        "text": text,
                        "start_time": seg["start"],
                        "end_time": seg["end"],
                        "embedding": emb,
                        "sequence": i,
                    })
                    if emb:
                        embeddings.append(emb)
            finally:
                Path(slice_path.name).unlink(missing_ok=True)

        logger.info(f"ASR+Embedding: {len(segments)} 个有效段")

        # ── Step 3: 说话人聚类 ──
        num_speakers = 1
        if len(embeddings) >= 2 and len(embeddings) == len(segments):
            emb_matrix = np.array(embeddings)
            n_segments = len(segments)

            # 启发式：短会议（< 3 分钟）大概率 2 人，强制 2 聚类
            if n_segments >= 3:
                num_speakers = min(2, n_segments)
            else:
                num_speakers = 1

            clustering = AgglomerativeClustering(
                n_clusters=num_speakers, metric="cosine", linkage="average"
            )
            labels = clustering.fit_predict(emb_matrix)
            for i, seg in enumerate(segments):
                seg["speaker_label"] = f"SPEAKER_{labels[i]:02d}"
        else:
            for seg in segments:
                seg["speaker_label"] = "SPEAKER_00"

        # ── 最终输出 ──
        for i, s in enumerate(segments):
            s["sequence"] = i

        elapsed = time.time() - t0
        logger.info(f"转写完成: {len(segments)} 段, {num_speakers} 说话人, {elapsed:.1f}s")

        return {
            "segments": segments,
            "num_speakers": num_speakers,
            "duration": elapsed,
        }

    except Exception as e:
        logger.exception("转写失败")
        raise HTTPException(500, str(e))
    finally:
        Path(raw.name).unlink(missing_ok=True)
        Path(wav_path).unlink(missing_ok=True)


@app.post("/api/embeddings")
async def extract_embedding(file: UploadFile = File(...)):
    """
    纯声纹提取 — 用于注册。
    返回 CAM++ spk_embedding 向量。
    """
    if not _models_loaded:
        _load_models()

    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    raw = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    raw.write(await file.read())
    raw.close()

    wav_path = raw.name + ".wav"
    if not _audio_to_wav(raw.name, Path(wav_path)):
        Path(raw.name).unlink(missing_ok=True)
        raise HTTPException(500, "音频格式转换失败")

    try:
        result = _spk.generate(input=wav_path)
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
