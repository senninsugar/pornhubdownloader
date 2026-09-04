import asyncio
import os
import uuid
from pathlib import Path
from typing import Optional

import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
STATIC_DIR = BASE_DIR / "app" / "static"
COOKIE_FILE = BASE_DIR / "cookies.txt"

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Video Downloader API",
    version="1.0.0",
)

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs = {}

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Sec-Fetch-Mode": "navigate",
}


class VideoRequest(BaseModel):
    url: HttpUrl


class JobResponse(BaseModel):
    id: str
    status: str


def get_ydl_base_options() -> dict:
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "http_headers": HTTP_HEADERS,
    }

    if COOKIE_FILE.exists():
        options["cookiefile"] = str(COOKIE_FILE)

    return options


def get_info(url: str):
    options = get_ydl_base_options()
    options["skip_download"] = True

    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=False)


def download_video(job_id: str, url: str):
    output_dir = DOWNLOAD_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    jobs[job_id] = {
        "status": "downloading",
        "progress": 0,
        "filename": None,
        "error": None,
    }

    def progress_hook(data):
        status = data.get("status")

        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            downloaded = data.get("downloaded_bytes", 0)

            progress = 0

            if total:
                progress = round(downloaded / total * 100, 1)

            jobs[job_id]["status"] = "downloading"
            jobs[job_id]["progress"] = progress

        elif status == "finished":
            jobs[job_id]["status"] = "processing"
            jobs[job_id]["progress"] = 100

    options = get_ydl_base_options()
    options.update({
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
        "progress_hooks": [progress_hook],
        "format": "bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
    })

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

            filename = ydl.prepare_filename(info)

            mp4_candidate = Path(filename).with_suffix(".mp4")

            if mp4_candidate.exists():
                filename = str(mp4_candidate)

            jobs[job_id]["status"] = "completed"
            jobs[job_id]["progress"] = 100
            jobs[job_id]["filename"] = filename

    except Exception as exc:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(exc)


@app.get("/")
async def root():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {
        "name": "Video Downloader API",
        "version": "1.0.0",
        "status": "online",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }


@app.post("/api/info")
async def video_info(request: VideoRequest):
    try:
        info = await asyncio.to_thread(
            get_info,
            str(request.url),
        )

        return {
            "id": info.get("id"),
            "title": info.get("title"),
            "description": info.get("description"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "uploader": info.get("uploader"),
            "channel": info.get("channel"),
            "channel_id": info.get("channel_id"),
            "view_count": info.get("view_count"),
            "upload_date": info.get("upload_date"),
            "webpage_url": info.get("webpage_url"),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


@app.post("/api/download", response_model=JobResponse)
async def start_download(request: VideoRequest):
    job_id = uuid.uuid4().hex

    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "filename": None,
        "error": None,
    }

    asyncio.create_task(
        asyncio.to_thread(
            download_video,
            job_id,
            str(request.url),
        )
    )

    return {
        "id": job_id,
        "status": "queued",
    }


@app.get("/api/status/{job_id}")
async def download_status(job_id: str):
    job = jobs.get(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    result = {
        "id": job_id,
        **job,
    }

    if job["status"] == "completed":
        filename = job.get("filename")

        if filename:
            result["download_url"] = f"/api/file/{job_id}"
            result["stream_url"] = f"/api/stream/{job_id}"

    return result


@app.get("/api/file/{job_id}")
async def download_file(job_id: str):
    job = jobs.get(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail="Download is not completed",
        )

    filename = job.get("filename")

    if not filename:
        raise HTTPException(
            status_code=404,
            detail="File not found",
        )

    path = Path(filename)

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="File no longer exists",
        )

    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type="application/octet-stream",
    )


@app.get("/api/stream/{job_id}")
async def stream_file(job_id: str, request: Request):
    job = jobs.get(job_id)

    if not job or job["status"] != "completed":
        raise HTTPException(status_code=404, detail="Video not available")

    filename = job.get("filename")
    if not filename or not Path(filename).exists():
        raise HTTPException(status_code=404, detail="File not found")

    path = Path(filename)
    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        bytes_type, bytes_range = range_header.split("=")
        start_str, end_str = bytes_range.split("-")
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1

        if start >= file_size:
            raise HTTPException(status_code=416, detail="Requested Range Not Satisfiable")

        chunk_size = (end - start) + 1

        def send_bytes():
            with open(path, "rb") as f:
                f.seek(start)
                yield f.read(chunk_size)

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size),
            "Content-Type": "video/mp4",
        }
        return StreamingResponse(send_bytes(), status_code=206, headers=headers)

    return FileResponse(path=str(path), media_type="video/mp4")


@app.get("/api/jobs")
async def list_jobs():
    return {
        "jobs": jobs
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
    )
