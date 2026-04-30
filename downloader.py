"""
YouTube → MP3 다운로더 (Stage 1 & 2)

사용법:
  py downloader.py --url "https://youtu.be/..."   # 단일 영상 다운로드
  py downloader.py                                 # config.json의 모든 플리 배치 실행
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import yt_dlp

CONFIG_PATH = Path(__file__).parent / "config.json"
LOG_PATH = Path(__file__).parent / "logs" / "downloader.log"


def setup_logging():
    LOG_PATH.parent.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


logger = logging.getLogger(__name__)


def load_config(config_path: Path) -> dict:
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)

    base = config_path.parent
    cfg["_state_file"] = base / cfg["state_file"]
    cfg["_singles_folder"] = base / cfg["singles_folder"]

    for pl in cfg.get("playlists", []):
        pl["_folder"] = base / pl["folder"]

    return cfg


def load_downloaded_ids(state_file: Path) -> set:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    if not state_file.exists():
        state_file.touch()
        return set()
    with open(state_file, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def save_downloaded_id(state_file: Path, video_id: str) -> None:
    with open(state_file, "a", encoding="utf-8") as f:
        f.write(video_id + "\n")


def build_ydl_opts(output_dir: Path, config: dict) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": config["audio_quality"],
            },
            {"key": "FFmpegMetadata"},
        ],
    }

    ffmpeg_path = config.get("ffmpeg_path", "")
    if ffmpeg_path and Path(ffmpeg_path).exists():
        opts["ffmpeg_location"] = str(Path(ffmpeg_path).parent)
    elif ffmpeg_path:
        logger.warning(
            "ffmpeg_path '%s'를 찾을 수 없습니다. "
            "PATH에 ffmpeg가 있으면 계속 진행됩니다.",
            ffmpeg_path,
        )

    return opts


def get_playlist_video_ids(playlist_url: str, config: dict) -> list:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "ignoreerrors": True,
    }
    ffmpeg_path = config.get("ffmpeg_path", "")
    if ffmpeg_path and Path(ffmpeg_path).exists():
        opts["ffmpeg_location"] = str(Path(ffmpeg_path).parent)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)

    if not info or "entries" not in info:
        return []

    return [
        {"id": entry["id"], "title": entry.get("title", entry["id"]), "url": entry.get("url", f"https://www.youtube.com/watch?v={entry['id']}")}
        for entry in info["entries"]
        if entry and entry.get("id")
    ]


def download_single(url: str, output_dir: Path, config: dict, downloaded_ids: set) -> dict | None:
    # 먼저 영상 ID만 조회 (다운로드 없음)
    probe_opts = {
        "quiet": True,
        "no_warnings": True,
    }
    ffmpeg_path = config.get("ffmpeg_path", "")
    if ffmpeg_path and Path(ffmpeg_path).exists():
        probe_opts["ffmpeg_location"] = str(Path(ffmpeg_path).parent)

    try:
        with yt_dlp.YoutubeDL(probe_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        logger.error("URL 조회 실패 '%s': %s", url, e)
        return None
    except yt_dlp.utils.ExtractorError as e:
        logger.error("URL 파싱 실패 '%s': %s", url, e)
        return None

    if not info:
        return None

    video_id = info.get("id")
    title = info.get("title", video_id)

    if video_id in downloaded_ids:
        logger.info("스킵 (이미 다운로드됨): [%s] %s", video_id, title)
        return None

    # 실제 다운로드
    opts = build_ydl_opts(output_dir, config)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.PostProcessingError as e:
        logger.error(
            "후처리 실패 (ffmpeg 확인 필요) '%s': %s\n"
            "config.json의 ffmpeg_path를 확인하세요.",
            title,
            e,
        )
        return None
    except yt_dlp.utils.DownloadError as e:
        logger.error("다운로드 실패 '%s': %s", title, e)
        return None

    state_file = config["_state_file"]
    save_downloaded_id(state_file, video_id)
    downloaded_ids.add(video_id)

    logger.info("다운로드 완료: [%s] %s → %s", video_id, title, output_dir)
    return {"id": video_id, "title": title, "folder": str(output_dir)}


def download_playlist(playlist_cfg: dict, config: dict, downloaded_ids: set) -> list:
    url = playlist_cfg["url"]
    output_dir = playlist_cfg["_folder"]
    name = playlist_cfg.get("name", url)

    logger.info("플리 확인 중: %s", name)

    try:
        all_videos = get_playlist_video_ids(url, config)
    except Exception as e:
        logger.error("플리 조회 실패 '%s': %s", name, e)
        return []

    new_videos = [v for v in all_videos if v["id"] not in downloaded_ids]
    logger.info("플리 '%s': 전체 %d곡, 신규 %d곡", name, len(all_videos), len(new_videos))

    results = []
    for video in new_videos:
        result = download_single(video["url"], output_dir, config, downloaded_ids)
        if result:
            results.append(result)

    return results


def run_batch(config: dict) -> list:
    downloaded_ids = load_downloaded_ids(config["_state_file"])
    logger.info("배치 시작 - 기존 다운로드: %d곡", len(downloaded_ids))

    all_new = []
    for playlist_cfg in config.get("playlists", []):
        new_tracks = download_playlist(playlist_cfg, config, downloaded_ids)
        all_new.extend(new_tracks)

    logger.info("배치 완료 - 신규 다운로드: %d곡", len(all_new))
    return all_new


def main():
    setup_logging()

    parser = argparse.ArgumentParser(description="YouTube → MP3 다운로더")
    parser.add_argument("--url", help="단일 영상 URL (생략 시 config.json 플리 배치 실행)")
    args = parser.parse_args()

    config = load_config(CONFIG_PATH)

    if args.url:
        downloaded_ids = load_downloaded_ids(config["_state_file"])
        output_dir = config["_singles_folder"]
        result = download_single(args.url, output_dir, config, downloaded_ids)
        if result:
            print(f"완료: {result['title']}")
        else:
            print("다운로드 실패 또는 이미 다운로드된 파일입니다.")
    else:
        new_tracks = run_batch(config)
        if new_tracks:
            print(f"\n신규 다운로드 {len(new_tracks)}곡:")
            for t in new_tracks:
                print(f"  - {t['title']}")
        else:
            print("신규 곡 없음.")


if __name__ == "__main__":
    main()
