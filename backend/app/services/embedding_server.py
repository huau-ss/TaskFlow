"""
独立声纹 Embedding 服务（纯 numpy + scipy，无需 torch）

基于 MFCC 特征提取说话人特征向量（256 维）。
CPU 运行，无需 GPU。

启动：python -m app.services.embedding_server
端口：8003
"""

import logging
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, UploadFile
from scipy.signal import resample_poly
from scipy.fft import dct

logger = logging.getLogger(__name__)

app = FastAPI(title="Voice Embedding Service", version="1.0")

# ============== MFCC 声纹特征提取 ==============

SAMPLE_RATE = 16000
N_MFCC = 40       # MFCC 系数数
N_FILTERS = 80    # Mel 滤波器数
FRAME_LEN = 0.025 # 帧长 25ms
FRAME_STEP = 0.010 # 帧移 10ms
EMBEDDING_DIM = 256


def _hz_to_mel(hz: float) -> float:
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel: float) -> float:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _mel_filterbank(sr: int, n_fft: int, n_filters: int) -> np.ndarray:
    """创建 Mel 滤波器组"""
    low_mel = _hz_to_mel(0)
    high_mel = _hz_to_mel(sr / 2)
    mel_points = np.linspace(low_mel, high_mel, n_filters + 2)
    hz_points = np.array([_mel_to_hz(m) for m in mel_points])
    bin_points = np.floor((n_fft + 1) * hz_points / sr).astype(int)

    fbank = np.zeros((n_filters, n_fft // 2 + 1))
    for i in range(n_filters):
        left = bin_points[i]
        center = bin_points[i + 1]
        right = bin_points[i + 2]
        for j in range(left, center):
            if center != left:
                fbank[i, j] = (j - left) / (center - left)
        for j in range(center, right):
            if right != center:
                fbank[i, j] = (right - j) / (right - center)
    return fbank


def _pre_emphasis(signal: np.ndarray, coeff: float = 0.97) -> np.ndarray:
    """预加重"""
    return np.append(signal[0], signal[1:] - coeff * signal[:-1])


def extract_embedding(audio_path: str) -> tuple[list[float], float]:
    """
    从音频文件提取声纹 embedding 向量。

    返回 (embedding_list, duration_seconds)
    """
    # 读取音频
    wav, sr = sf.read(audio_path, dtype="float32")

    # 立体声转单声道
    if len(wav.shape) > 1:
        wav = wav.mean(axis=1)

    # 重采样到 16kHz
    if sr != SAMPLE_RATE:
        gcd = np.gcd(SAMPLE_RATE, sr)
        wav = resample_poly(wav, SAMPLE_RATE // gcd, sr // gcd)

    duration = float(len(wav) / SAMPLE_RATE)

    # 预加重
    wav = _pre_emphasis(wav)

    # 分帧
    frame_length = int(FRAME_LEN * SAMPLE_RATE)
    frame_step = int(FRAME_STEP * SAMPLE_RATE)
    n_frames = max(1, (len(wav) - frame_length) // frame_step + 1)

    frames = np.zeros((n_frames, frame_length))
    for i in range(n_frames):
        start = i * frame_step
        end = start + frame_length
        if end <= len(wav):
            frames[i] = wav[start:end]

    # 加窗 (Hamming)
    frames *= np.hamming(frame_length)

    # FFT
    n_fft = 512
    mag_spectrum = np.abs(np.fft.rfft(frames, n=n_fft))
    power_spectrum = (mag_spectrum ** 2) / n_fft

    # Mel 滤波器组
    fbank = _mel_filterbank(SAMPLE_RATE, n_fft, N_FILTERS)
    mel_features = np.dot(power_spectrum, fbank.T)
    mel_features = np.where(mel_features == 0, np.finfo(float).eps, mel_features)
    log_mel = np.log(mel_features)

    # MFCC (DCT)
    mfcc = dct(log_mel, type=2, axis=1, norm="ortho")[:, :N_MFCC]

    # 生成固定长度的 embedding
    # 方法：对 MFCC 做时间维度统计（均值 + 标准差 + 最大值 + 最小值）
    mean = np.mean(mfcc, axis=0)         # 40
    std = np.std(mfcc, axis=0)           # 40
    max_val = np.max(mfcc, axis=0)       # 40
    min_val = np.min(mfcc, axis=0)       # 40
    # 一阶差分统计
    delta = np.diff(mfcc, axis=0)
    if len(delta) > 0:
        delta_mean = np.mean(delta, axis=0)   # 40
        delta_std = np.std(delta, axis=0)     # 40
    else:
        delta_mean = np.zeros(N_MFCC)
        delta_std = np.zeros(N_MFCC)

    # 拼接：40*6 = 240，再补 16 维到 256
    raw = np.concatenate([mean, std, max_val, min_val, delta_mean, delta_std])

    # 用 DCT 扩展到 EMBEDDING_DIM
    padded = np.pad(raw, (0, EMBEDDING_DIM - len(raw)))
    embedding = dct(padded, type=2, norm="ortho")

    # L2 归一化
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    return embedding.tolist(), duration


# ============== FastAPI 路由 ==============

@app.get("/health")
async def health():
    return {"status": "ok", "model": "mfcc-speaker", "device": "cpu", "embedding_dim": EMBEDDING_DIM}


@app.post("/api/embeddings")
async def extract_embeddings(file: UploadFile = File(...)):
    """
    从上传的音频文件中提取说话人 embedding 向量。
    返回 256 维归一化特征向量。
    """
    content = await file.read()
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    wav_path = None

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # 如果不是 WAV 或 soundfile 无法直接读取，用 ffmpeg 转换为 16kHz mono WAV
        wav_path = tmp_path + ".wav"
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0 and Path(wav_path).exists():
            embedding, duration = extract_embedding(wav_path)
        else:
            # ffmpeg 失败时尝试直接读取（可能已经是 WAV）
            embedding, duration = extract_embedding(tmp_path)

        return {"embedding": embedding, "duration": duration}
    except Exception as e:
        logger.error(f"Embedding extraction failed: {e}")
        raise
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if wav_path:
            Path(wav_path).unlink(missing_ok=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
