"""
SmartBasket — Audio Peaks
Detecta picos de energía de audio en el video (gritos, silbatos, reacciones).
No transcribe ni usa speech-to-text.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from loguru import logger

from basketball_highlights.schemas import AudioPeak


def extract_audio(video_path: str | Path, wav_path: str | Path) -> str:
    """
    Extrae el audio del video como archivo WAV mono 16kHz.
    
    Args:
        video_path: Ruta al video de entrada.
        wav_path: Ruta del WAV de salida.
    
    Returns:
        Ruta del WAV generado.
    """
    video_path = Path(video_path)
    wav_path = Path(wav_path)
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",                   # sin video
        "-acodec", "pcm_s16le",  # PCM 16-bit
        "-ar", "16000",          # 16 kHz
        "-ac", "1",              # mono
        "-loglevel", "error",
        str(wav_path),
    ]
    logger.info(f"Extrayendo audio: {video_path.name} → {wav_path.name}")
    subprocess.run(cmd, check=True)
    logger.info(f"  → Audio extraído: {wav_path}")
    return str(wav_path)


def detect_audio_peaks(
    wav_path: str | Path,
    window_seconds: float = 1.0,
    peak_percentile: float = 90.0,
) -> list[AudioPeak]:
    """
    Detecta picos de energía de audio usando RMS por ventana temporal.
    
    Args:
        wav_path: Ruta al archivo WAV.
        window_seconds: Tamaño de ventana en segundos.
        peak_percentile: Percentil sobre el que se considera un pico.
    
    Returns:
        Lista de AudioPeak con timestamp, energía y flag is_peak.
    """
    import soundfile as sf

    wav_path = Path(wav_path)
    if not wav_path.exists():
        raise FileNotFoundError(f"WAV no encontrado: {wav_path}")

    logger.info(f"Analizando audio: {wav_path.name}")
    audio, sample_rate = sf.read(str(wav_path), dtype="float32")

    # Si es stereo, convertir a mono
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    window_samples = int(window_seconds * sample_rate)
    num_windows = len(audio) // window_samples

    energies = []
    timestamps = []

    for i in range(num_windows):
        start = i * window_samples
        end = start + window_samples
        window = audio[start:end]
        rms = float(np.sqrt(np.mean(window ** 2)))
        energies.append(rms)
        timestamps.append(i * window_seconds)

    if not energies:
        logger.warning("No se detectó audio en el archivo")
        return []

    energies_arr = np.array(energies)
    threshold = float(np.percentile(energies_arr, peak_percentile))
    # Normalizar energías a [0, 1]
    max_e = energies_arr.max()
    if max_e > 0:
        normalized = energies_arr / max_e
    else:
        normalized = energies_arr

    peaks = []
    for ts, energy, norm in zip(timestamps, energies, normalized):
        is_peak = energy >= threshold
        peaks.append(AudioPeak(
            timestamp=round(ts, 3),
            energy=round(float(norm), 4),
            is_peak=is_peak,
        ))

    num_peaks = sum(1 for p in peaks if p.is_peak)
    logger.info(
        f"  → {len(peaks)} ventanas analizadas | "
        f"{num_peaks} picos detectados (percentil {peak_percentile})"
    )
    return peaks
