"""
SmartBasket — CLI
Comandos del pipeline usando Typer.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import track
from rich.table import Table
from loguru import logger

from basketball_highlights.config import get_config
from basketball_highlights.utils import setup_logging, get_game_id, save_json, load_json, format_duration
from basketball_highlights.schemas import VideoReport

app = typer.Typer(
    name="basketball-highlights",
    help="🏀 SmartBasket — Agente local de highlights de basketball juvenil",
    add_completion=False,
)
console = Console()


def _print_banner():
    console.print(Panel.fit(
        "[bold cyan]🏀 SmartBasket — Basketball Highlight Agent[/bold cyan]\n"
        "[dim]Pipeline local con YOLO + VLM[/dim]",
        border_style="cyan",
    ))


@app.command("analyze")
def analyze(
    video_path: str = typer.Argument(..., help="Ruta al video del partido (.mp4)"),
    config_dir: str = typer.Option("/app/configs", "--config-dir", "-c", help="Directorio de configs YAML"),
    no_vlm: bool = typer.Option(False, "--no-vlm", help="Desactivar VLM (modo rápido heurístico)"),
    base_dir: str = typer.Option("/app", "--base-dir", help="Directorio base del proyecto"),
    log_level: str = typer.Option("INFO", "--log-level"),
):
    """
    Ejecuta el pipeline completo de análisis de highlights.
    
    Pasos: metadata → frames → audio → scenes → YOLO → candidatos → scoring → clips → [VLM] → reel
    """
    setup_logging(log_level)
    _print_banner()
    start_ts = time.time()

    from basketball_highlights.video_io import get_video_metadata, validate_ffmpeg, ensure_output_dirs
    from basketball_highlights.frame_sampler import sample_frames, compute_motion_scores
    from basketball_highlights.audio_peaks import extract_audio, detect_audio_peaks
    from basketball_highlights.scene_detection import detect_scenes
    from basketball_highlights.yolo_detector import YOLODetector
    from basketball_highlights.court_geometry import get_hoop_boxes_from_detections, get_manual_hoop_regions
    from basketball_highlights.candidate_generator import generate_candidates
    from basketball_highlights.scorer import rank_candidates
    from basketball_highlights.clipper import cut_candidate_clips
    from basketball_highlights.reel_builder import build_reel

    video_path = Path(video_path)
    if not video_path.exists():
        console.print(f"[red]❌ Video no encontrado: {video_path}[/red]")
        raise typer.Exit(1)

    cfg = get_config(config_dir)
    game_id = get_game_id(video_path)
    dirs = ensure_output_dirs(base_dir, game_id)

    # ─── Validar FFmpeg ────────────────────────────────────────────────────
    console.print("[cyan]→ Validando FFmpeg...[/cyan]")
    validate_ffmpeg()

    # ─── Metadata ──────────────────────────────────────────────────────────
    console.print("[cyan]→ Obteniendo metadata del video...[/cyan]")
    meta = get_video_metadata(str(video_path))
    duration = meta["duration"]
    console.print(f"  Duración: [bold]{format_duration(duration)}[/bold] | "
                  f"{meta['width']}x{meta['height']} | {meta['fps']} fps")

    # ─── Frame sampling ────────────────────────────────────────────────────
    console.print("[cyan]→ Extrayendo frames...[/cyan]")
    frames = sample_frames(
        video_path=str(video_path),
        output_dir=str(dirs["frames"]),
        fps=cfg.video.get("sample_fps_general", 2),
    )
    console.print(f"  {len(frames)} frames extraídos")

    # ─── Motion scores ─────────────────────────────────────────────────────
    console.print("[cyan]→ Calculando motion scores...[/cyan]")
    motion_scores = compute_motion_scores(frames)

    # ─── Audio peaks ───────────────────────────────────────────────────────
    console.print("[cyan]→ Analizando audio...[/cyan]")
    wav_path = dirs["audio"] / f"{game_id}.wav"
    extract_audio(str(video_path), str(wav_path))
    audio_peaks = detect_audio_peaks(
        str(wav_path),
        window_seconds=1.0,
        peak_percentile=cfg.thresholds.get("audio_peak_percentile", 90),
    )
    n_audio_peaks = sum(1 for p in audio_peaks if p.is_peak)
    console.print(f"  {n_audio_peaks} picos de audio detectados")

    # ─── Scene detection ───────────────────────────────────────────────────
    console.print("[cyan]→ Detectando escenas...[/cyan]")
    scenes = detect_scenes(str(video_path))
    console.print(f"  {len(scenes)} escenas detectadas")

    # ─── YOLO detections ───────────────────────────────────────────────────
    console.print("[cyan]→ Ejecutando YOLO...[/cyan]")
    yolo_cfg = cfg.yolo
    detector = YOLODetector(
        model_path=str(cfg.get_yolo_model_path()),
        device=yolo_cfg.get("device", "cuda"),
        conf=cfg.thresholds.get("yolo_confidence", 0.25),
        imgsz=yolo_cfg.get("imgsz", 640),
        fallback_path=str(cfg.resolve_model_path("fallback_yolo_model")),
    )
    detections = detector.detect_frames(frames)
    save_json([d.model_dump() for d in detections],
              dirs["detections"] / f"{game_id}_yolo.json")

    # ─── Court geometry ────────────────────────────────────────────────────
    hoop_boxes = get_hoop_boxes_from_detections(detections)
    if not hoop_boxes:
        hoop_boxes = get_manual_hoop_regions(cfg.court.get("manual_hoop_regions", {}))
    if not hoop_boxes:
        console.print("  [yellow]⚠ No se detectaron aros. Usando heurísticas sin geometría de cancha.[/yellow]")

    # ─── Candidates ────────────────────────────────────────────────────────
    console.print("[cyan]→ Generando candidatos...[/cyan]")
    candidates = generate_candidates(
        game_id=game_id,
        video_path=str(video_path.resolve()),
        video_duration=duration,
        detections=detections,
        audio_peaks=audio_peaks,
        scenes=scenes,
        motion_scores=motion_scores,
        hoop_boxes=hoop_boxes,
        config={**cfg.video, **cfg.thresholds},
    )

    # ─── Scoring ───────────────────────────────────────────────────────────
    console.print("[cyan]→ Calculando scores...[/cyan]")
    candidates = rank_candidates(
        candidates=candidates,
        weights=cfg.weights,
        penalties=cfg.penalties,
        min_score=cfg.thresholds.get("min_candidate_score", 5.5),
    )

    # Guardar candidatos (antes de VLM)
    candidates_path = dirs["candidates"] / f"{game_id}_candidates.json"
    save_json([c.model_dump() for c in candidates], candidates_path)
    console.print(f"  {len(candidates)} candidatos → [bold]{candidates_path}[/bold]")

    # ─── Clip cutting ──────────────────────────────────────────────────────
    console.print("[cyan]→ Recortando clips...[/cyan]")
    top_k = cfg.output.get("top_k_clips", 20)
    candidates_to_cut = candidates[:top_k]
    candidates_to_cut = cut_candidate_clips(
        candidates=candidates_to_cut,
        output_dir=str(dirs["clips"]),
        use_stream_copy=cfg.ffmpeg.get("use_stream_copy", True),
        video_codec=cfg.ffmpeg.get("video_codec", "libx264"),
        preset=cfg.ffmpeg.get("preset", "veryfast"),
        crf=cfg.ffmpeg.get("crf", 20),
    )

    # ─── VLM labeling (opcional) ──────────────────────────────────────────
    use_vlm = not no_vlm and cfg.use_vlm()
    if use_vlm:
        console.print("[cyan]→ Clasificando con VLM (Qwen2.5-VL)...[/cyan]")
        from basketball_highlights.vlm_labeler import VLMLabeler
        vlm_cfg = cfg.vlm
        labeler = VLMLabeler(
            model_id=cfg.models.get("vlm_model", "Qwen/Qwen2.5-VL-3B-Instruct"),
            model_cache_dir=cfg.models.get("vlm_model_path", "/app/models/vlm"),
            device=vlm_cfg.get("device", "cuda"),
            quantization=cfg.models.get("vlm_quantization"),
            max_frames=vlm_cfg.get("max_frames_per_clip", 12),
            max_width=vlm_cfg.get("frame_max_width", 640),
            max_new_tokens=vlm_cfg.get("max_new_tokens", 512),
            temperature=vlm_cfg.get("temperature", 0.1),
        )
        candidates_to_cut = labeler.label_candidates(
            candidates=candidates_to_cut,
            max_clips=cfg.models.get("vlm_max_clips", 40),
        )
        labeled_path = dirs["candidates"] / f"{game_id}_candidates_labeled.json"
        save_json([c.model_dump() for c in candidates_to_cut], labeled_path)
        console.print(f"  Candidatos etiquetados → [bold]{labeled_path}[/bold]")
    else:
        console.print("  [dim]VLM desactivado, usando solo scoring heurístico[/dim]")

    # ─── Reel ─────────────────────────────────────────────────────────────
    console.print("[cyan]→ Construyendo reel...[/cyan]")
    reel_path = dirs["reels"] / f"{game_id}_top{cfg.output.get('reel_top_k', 10)}.mp4"
    try:
        build_reel(
            candidates=candidates_to_cut,
            output_path=str(reel_path),
            top_k=cfg.output.get("reel_top_k", 10),
            mode=cfg.output.get("reel_mode", "score"),
        )
        console.print(f"  Reel → [bold]{reel_path}[/bold]")
    except Exception as e:
        console.print(f"  [yellow]⚠ No se pudo construir el reel: {e}[/yellow]")
        reel_path = None

    # ─── Reporte final ────────────────────────────────────────────────────
    elapsed = time.time() - start_ts
    vlm_count = sum(1 for c in candidates_to_cut if c.vlm_reviewed)
    avg_score = sum(c.score for c in candidates_to_cut) / len(candidates_to_cut) if candidates_to_cut else 0

    report = VideoReport(
        video=video_path.name,
        duration_seconds=duration,
        num_candidates=len(candidates),
        num_clips_exported=len(candidates_to_cut),
        num_vlm_highlights=vlm_count,
        average_score=round(avg_score, 2),
        reel_path=str(reel_path) if reel_path else None,
        processing_time_seconds=round(elapsed, 1),
    )
    report_path = dirs["reports"] / f"{game_id}_report.json"
    save_json(report.model_dump(), report_path)

    # Tabla de resultados
    table = Table(title="📊 Reporte SmartBasket", show_header=True, header_style="bold cyan")
    table.add_column("Métrica")
    table.add_column("Valor", justify="right")
    table.add_row("Duración del partido", format_duration(duration))
    table.add_row("Candidatos detectados", str(report.num_candidates))
    table.add_row("Clips exportados", str(report.num_clips_exported))
    table.add_row("Revisados con VLM", str(report.num_vlm_highlights))
    table.add_row("Score promedio", f"{report.average_score:.2f}")
    table.add_row("Tiempo de procesamiento", format_duration(elapsed))
    console.print(table)

    console.print(Panel.fit(
        f"[green]✅ Pipeline completado![/green]\n\n"
        f"Candidatos: [bold]{candidates_path}[/bold]\n"
        f"Clips: [bold]{dirs['clips']}[/bold]\n"
        f"Reel: [bold]{reel_path or 'no generado'}[/bold]\n\n"
        f"[dim]Para revisar: streamlit run reviewer_app.py[/dim]",
        border_style="green",
    ))


@app.command("candidates")
def candidates_cmd(
    video_path: str = typer.Argument(..., help="Ruta al video del partido"),
    config_dir: str = typer.Option("/app/configs", "--config-dir", "-c"),
    base_dir: str = typer.Option("/app", "--base-dir"),
):
    """Solo genera candidatos sin recortar clips ni usar VLM."""
    analyze(video_path, config_dir, no_vlm=True, base_dir=base_dir)


@app.command("cut")
def cut_cmd(
    video_path: str = typer.Argument(..., help="Ruta al video"),
    candidates_json: str = typer.Argument(..., help="JSON de candidatos"),
    config_dir: str = typer.Option("/app/configs", "--config-dir", "-c"),
    base_dir: str = typer.Option("/app", "--base-dir"),
):
    """Recorta clips desde un JSON de candidatos existente."""
    setup_logging("INFO")
    from basketball_highlights.clipper import cut_candidate_clips
    cfg = get_config(config_dir)
    game_id = get_game_id(video_path)
    
    data = load_json(candidates_json)
    from basketball_highlights.schemas import CandidateSegment
    candidates = [CandidateSegment(**d) for d in data]
    
    output_dir = Path(base_dir) / "videos" / "clips" / game_id
    candidates = cut_candidate_clips(candidates, str(output_dir))
    save_json([c.model_dump() for c in candidates], candidates_json)
    console.print(f"[green]✅ {len(candidates)} clips exportados[/green]")


@app.command("label")
def label_cmd(
    candidates_json: str = typer.Argument(..., help="JSON de candidatos con clips"),
    config_dir: str = typer.Option("/app/configs", "--config-dir", "-c"),
):
    """Clasifica clips candidatos con el VLM local."""
    setup_logging("INFO")
    from basketball_highlights.vlm_labeler import VLMLabeler
    from basketball_highlights.schemas import CandidateSegment
    cfg = get_config(config_dir)
    
    data = load_json(candidates_json)
    candidates = [CandidateSegment(**d) for d in data]
    
    labeler = VLMLabeler(
        model_id=cfg.models.get("vlm_model", "Qwen/Qwen2.5-VL-3B-Instruct"),
        model_cache_dir=cfg.models.get("vlm_model_path", "/app/models/vlm"),
        device=cfg.vlm.get("device", "cuda"),
    )
    candidates = labeler.label_candidates(candidates)
    
    out_path = Path(candidates_json).with_suffix("").as_posix() + "_labeled.json"
    save_json([c.model_dump() for c in candidates], out_path)
    console.print(f"[green]✅ Candidatos etiquetados → {out_path}[/green]")


@app.command("reel")
def reel_cmd(
    candidates_json: str = typer.Argument(..., help="JSON de candidatos"),
    output: str = typer.Option("/app/videos/reels/reel_final.mp4", "--output", "-o"),
    top_k: int = typer.Option(10, "--top-k"),
    mode: str = typer.Option("score", "--mode", help="score | chronological"),
    config_dir: str = typer.Option("/app/configs", "--config-dir", "-c"),
):
    """Construye un reel con los mejores clips."""
    setup_logging("INFO")
    from basketball_highlights.reel_builder import build_reel
    from basketball_highlights.schemas import CandidateSegment
    
    data = load_json(candidates_json)
    candidates = [CandidateSegment(**d) for d in data]
    
    reel_path = build_reel(candidates, output, top_k=top_k, mode=mode)
    console.print(f"[green]✅ Reel generado → {reel_path}[/green]")


@app.command("review")
def review_cmd():
    """Abre la UI de revisión (Streamlit). Usar: http://localhost:8501"""
    console.print("[cyan]Para abrir el reviewer, ejecuta desde el contenedor reviewer:[/cyan]")
    console.print("  [bold]streamlit run /app/src/basketball_highlights/reviewer_app.py[/bold]")
    console.print("  O accede directamente a: [link]http://localhost:8501[/link]")


if __name__ == "__main__":
    app()
