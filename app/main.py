import asyncio
import os
import uuid
from pathlib import Path
from typing import Optional

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse


BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = BASE_DIR / "downloads"

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


app = FastAPI(
    title="Video Downloader API",
    version="1.0.0",
)

STATIC_DIR = BASE_DIR / "app" / "static"

STATIC_DIR.mkdir(
    parents=True,
    exist_ok=True
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


class VideoRequest(BaseModel):
    url: HttpUrl


class JobResponse(BaseModel):
    id: str
    status: str


def get_info(url: str):
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }

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

    options = {
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],

        # ダウンロード形式
        "format": "bestvideo*+bestaudio/best",

        # 必要に応じてMP4へマージ
        "merge_output_format": "mp4",
    }

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
    return FileResponse(
        STATIC_DIR / "index.html"
    )


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
