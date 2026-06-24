"""
FunASR 统一语音服务 — ASR + 说话人分离 + CAM++ 声纹 embedding.

端点:
  GET  /health              健康检查
  POST /api/transcribe      完整转写 (VAD → paraformer ASR → CAM++ embedding → 说话人聚类)
  POST /api/embeddings      纯声纹提取 (注册用，CAM++ 单次推理)

启动: uvicorn main:app --host 0.0.0.0 --port 8005
"""

import gc
import logging
import os
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

# ── 聚类质量控制参数 ──────────────────────────────────────
# 合并相邻 VAD 段的最大间隔（秒）。增大可减少碎片。
_MERGE_MAX_GAP = 2.0          # 原值 3.0s → 降低以减少不同说话人被合并
# 片段合并后最小持续时长（秒），短于此值直接丢弃，不参与 embedding 提取。
# CAM++ 需要 1.5s+ 语音才能输出稳定向量，0.5s 太短会引入噪声。
_MERGE_MIN_DURATION = 1.5     # 原值 0.5s
# 丢弃短片段后，剩余用于聚类的 embedding 数量下限。
_MIN_EMBEDDINGS_FOR_CLUSTERING = 2
# CAM++ embedding 间的余弦距离上限（用于过滤异常值）。超过此距离认为是噪声。
_OUTLIER_DISTANCE_THRESHOLD = 0.65  # 保留，仅用于日志记录（已停用）

# ── OOM 防护：限制单次 ASR 调用处理的片段最大时长 ──
# Paraformer 在 CPU 上处理 30s 音频约需 4-6GB RSS（临时分配），
# 加上模型权重 ~4GB、音频 ~0.5GB，峰值可控制在 10GB 限制内。
_MAX_SEGMENT_DURATION = 30.0       # 子片段最大持续时长（秒）
_SUB_SEGMENT_MIN_DURATION = 1.0    # 子片段最短持续时长（秒，CAM++ 需要足够语音帧）

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


def _merge_vad_segments(segments: list[dict]) -> list[dict]:
    """合并相邻 VAD 段（间隔 < _MERGE_MAX_GAP 秒且合并后 duration >= _MERGE_MIN_DURATION）。

    注意：过短的片段会导致 CAM++ embedding 不稳定，合并后低于 _MERGE_MIN_DURATION 的
    片段会被丢弃，以提升后续说话人聚类的质量。
    """
    if not segments:
        return []
    merged = [dict(segments[0])]
    for seg in segments[1:]:
        gap = seg["start"] - merged[-1]["end"]
        if gap <= _MERGE_MAX_GAP:
            merged[-1]["end"] = seg["end"]
        else:
            dur = merged[-1]["end"] - merged[-1]["start"]
            if dur < _MERGE_MIN_DURATION:
                merged[-1] = dict(seg)
            else:
                merged.append(dict(seg))
    dur = merged[-1]["end"] - merged[-1]["start"]
    if dur < _MERGE_MIN_DURATION and len(merged) > 1:
        merged.pop()
    return merged


def _split_long_segments(
    segments: list[dict],
    max_dur: float = _MAX_SEGMENT_DURATION,
) -> tuple[list[dict], int]:
    """将超过 max_dur 的片段等长切分为子段，防止 CPU ASR 推理 OOM。

    Args:
        segments: VAD 合并后的片段列表 [{"start": s, "end": s}, ...]
        max_dur: 子片段最大持续时长（秒）

    Returns:
        (expanded_segments, split_count):
            expanded_segments — 切分后的子段列表（原顺序，不超 max_dur）
            split_count — 被切分的原始片段数量
    """
    result: list[dict] = []
    split_count = 0
    for seg in segments:
        dur = seg["end"] - seg["start"]
        if dur <= max_dur:
            result.append(seg)
        else:
            n = int(np.ceil(dur / max_dur))
            chunk_dur = dur / n
            for j in range(n):
                result.append({
                    "start": seg["start"] + j * chunk_dur,
                    "end": seg["start"] + (j + 1) * chunk_dur,
                })
            split_count += 1
            logger.info(
                f"长片段切分: {seg['start']:.1f}s–{seg['end']:.1f}s "
                f"({dur:.1f}s → {n}×{chunk_dur:.1f}s)"
            )
    return result, split_count


# ────────── 内存监控 ──────────

def _mem_mb() -> float:
    """返回当前进程 RSS（MB）"""
    try:
        with open(f"/proc/{os.getpid()}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        return -1.0

def _log_mem(tag: str) -> None:
    logger.info(f"[MEM] {tag}: rss={_mem_mb():.0f}MB")

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
    global _vad

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
        _log_mem("开始转写")

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
        else:
            # 合并相邻段（使用全局质量控制参数）
            vad_segments = _merge_vad_segments(vad_segments)
        logger.info(f"VAD: {len(vad_segments)} 段")
        _log_mem("VAD 完成")

        # ── VAD 模型用完卸载，释放内存给 ASR/CAM++ ──
        del vad_result
        _vad = None
        gc.collect()
        _log_mem("VAD 卸载后")

        # ── Step 2: 一次性加载音频，后续切片全部 in-memory，避免 N 次磁盘读取导致 OOM ──
        wav_full, sr = sf.read(wav_path, dtype="float32")
        if len(wav_full.shape) > 1:
            wav_full = wav_full.mean(axis=1)

        # ── Step 2.5: 长片段切分（防止 CPU ASR 推理 OOM）──
        _log_mem("长片段切分前")
        vad_segments, split_count = _split_long_segments(vad_segments)
        if split_count:
            logger.info(
                f"长片段切分完成: {len(vad_segments)} 段 "
                f"({split_count} 个原始段被切分, max={_MAX_SEGMENT_DURATION}s)"
            )
        _log_mem("长片段切分后")

        # ── Step 3: 每段 ASR + CAM++ ──────────────────────────────
        segments = []
        embeddings = []
        _log_mem("ASR/CAM++ 循环开始")

        for i, seg in enumerate(vad_segments):
            # 跳过过短片段（CAM++ 在 < _SUB_SEGMENT_MIN_DURATION s 语音上不稳定）
            seg_dur = seg["end"] - seg["start"]
            if seg_dur < _SUB_SEGMENT_MIN_DURATION:
                logger.debug(f"跳过过短片段 {i}: {seg_dur:.2f}s < {_SUB_SEGMENT_MIN_DURATION}s")
                continue

            # in-memory 切片（wav_full 已在 Step 2 一次性加载）
            start_idx = max(0, int(seg["start"] * sr))
            end_idx = min(len(wav_full), int(seg["end"] * sr))
            if start_idx >= end_idx:
                continue
            sliced = wav_full[start_idx:end_idx]
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
                            if isinstance(emb, list) and len(emb) == 1 and isinstance(emb[0], list):
                                emb = emb[0]
                        elif isinstance(emb_data, list):
                            emb = emb_data

                # segments 和 embeddings 必须严格同步（索引一一对应），否则后续聚类索引会错位
                if text and emb:
                    segments.append({
                        "speaker_label": "",
                        "text": text,
                        "start_time": seg["start"],
                        "end_time": seg["end"],
                        "embedding": emb,
                        "sequence": i,
                    })
                    embeddings.append(emb)
            finally:
                Path(slice_path.name).unlink(missing_ok=True)
                # 每 5 个子段 GC 一次，释放 ASR 推理中间 tensor
                if (i + 1) % 5 == 0:
                    gc.collect()
                    _log_mem(f"ASR 子段 {i+1}/{len(vad_segments)} gc")

        logger.info(f"ASR+Embedding: {len(segments)} 个有效段（已过滤 < {_SUB_SEGMENT_MIN_DURATION}s 片段）")
        _log_mem("ASR/CAM++ 完成")

        # ── Step 3: 说话人聚类 ──────────────────────────────────
        # 使用 Silhouette Score 自动选择最优说话人数（不需硬编码上限）
        num_speakers = 1
        if len(embeddings) >= _MIN_EMBEDDINGS_FOR_CLUSTERING:
            emb_matrix = np.array(embeddings)
            n = len(embeddings)
            max_k = min(8, n - 1)  # 最多检测 8 人，不少于 n-1

            if max_k <= 1:
                num_speakers = 1
                labels = np.zeros(n, dtype=int)
            else:
                from sklearn.metrics import silhouette_score

                best_k = 1
                best_score = -1.0
                best_labels = np.zeros(n, dtype=int)

                # 预计算余弦距离矩阵（AgglomerativeClustering 需要）
                for k_candidate in range(2, max_k + 1):
                    clustering = AgglomerativeClustering(
                        n_clusters=k_candidate, metric="cosine", linkage="average"
                    )
                    candidate_labels = clustering.fit_predict(emb_matrix)

                    # Silhouette 需要 ≥2 个簇，每个簇至少 2 个样本
                    unique_labels = set(candidate_labels)
                    if len(unique_labels) < 2:
                        continue
                    if any(np.sum(candidate_labels == lbl) < 2 for lbl in unique_labels):
                        continue

                    score = silhouette_score(emb_matrix, candidate_labels, metric="cosine")
                    if score > best_score:
                        best_score = score
                        best_k = k_candidate
                        best_labels = candidate_labels.copy()

                # 如果最佳分数太低（< 0.05），退回到 1 说话人（聚类无意义）
                if best_score < 0.05:
                    num_speakers = 1
                    labels = np.zeros(n, dtype=int)
                    logger.info(
                        f"Silhouette 分数过低 ({best_score:.4f} < 0.05)，"
                        f"回退为 1 说话人"
                    )
                else:
                    num_speakers = best_k
                    labels = best_labels
                    logger.info(
                        f"Silhouette 自动选 k={best_k} (score={best_score:.4f}, "
                        f"搜索范围 2–{max_k})"
                    )

            # 回填标签（segments 和 embeddings 严格同步，直接按顺序对应）
            for k, seg in enumerate(segments):
                seg["speaker_label"] = f"SPEAKER_{labels[k]:02d}"

            logger.info(
                f"说话人聚类: {n} 片段 → {num_speakers} 人 "
                f"(阈值: gap={_MERGE_MAX_GAP}s, min_dur={_MERGE_MIN_DURATION}s)"
            )
        else:
            logger.warning(
                f"有效片段 < {_MIN_EMBEDDINGS_FOR_CLUSTERING}，跳过聚类，全部标记为 SPEAKER_00"
            )
            for seg in segments:
                seg["speaker_label"] = "SPEAKER_00"

        # ── 最终输出 ──
        for i, s in enumerate(segments):
            s["sequence"] = i

        elapsed = time.time() - t0
        _log_mem(f"转写完成 ({elapsed:.1f}s)")
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
