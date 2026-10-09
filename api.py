from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import asyncio
from pathlib import Path
from dataclasses import replace

from Utilities.config import load_settings
from Crawler.crawler import CrawlEngine
from Exporter.sqlite_repository import SQLiteRepository
from Exporter.search_service import SearchService

app = FastAPI(title="CrawlMind Web UI")

# Serve frontend
frontend_path = Path(__file__).parent / "frontend"
frontend_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=frontend_path), name="static")

class CrawlRequest(BaseModel):
    url: str
    max_depth: int = 1
    max_pages: int = 100
    enable_js_rendering: bool = False
    enable_llm: bool = False

# Global state to track crawl status
current_crawl_status = {"status": "idle", "run_id": None, "stats": {}}
active_connections = set()

async def broadcast_status():
    for conn in list(active_connections):
        try:
            await conn.send_json(current_crawl_status)
        except Exception:
            active_connections.discard(conn)

async def run_crawl_task(req: CrawlRequest):
    global current_crawl_status
    current_crawl_status["status"] = "running"
    current_crawl_status["stats"] = {"message": "Initializing..."}
    asyncio.create_task(broadcast_status())
    
    settings = load_settings()
    settings = replace(
        settings, 
        max_depth=req.max_depth,
        max_pages=req.max_pages,
        enable_js_rendering=req.enable_js_rendering,
        enable_llm=req.enable_llm
    )
    
    try:
        async with SQLiteRepository(settings.database_path) as repo:
            engine = CrawlEngine(settings, repo, [])
            
            async def _update_stats():
                while current_crawl_status["status"] == "running":
                    if hasattr(engine, "_stats") and engine._stats:
                        current_crawl_status["stats"] = engine._stats.to_dict()
                        await broadcast_status()
                    await asyncio.sleep(1)
            
            updater_task = asyncio.create_task(_update_stats())
            
            try:
                result = await engine.run([req.url])
                current_crawl_status["run_id"] = result.run_id
                current_crawl_status["stats"] = result.stats
                current_crawl_status["status"] = "completed"
                await broadcast_status()
            finally:
                updater_task.cancel()
    except Exception as e:
        current_crawl_status["status"] = f"error: {str(e)}"
        await broadcast_status()

@app.get("/")
async def index():
    return FileResponse(frontend_path / "index.html")

@app.post("/api/crawl")
async def start_crawl(req: CrawlRequest, background_tasks: BackgroundTasks):
    global current_crawl_status
    if current_crawl_status["status"] == "running":
        return {"error": "Crawl already running"}
    
    background_tasks.add_task(run_crawl_task, req)
    return {"message": "Crawl started"}

@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    try:
        await websocket.send_json(current_crawl_status)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.discard(websocket)

@app.get("/api/status")
async def get_status():
    return current_crawl_status

@app.get("/api/search")
async def search(q: str):
    settings = load_settings()
    async with SQLiteRepository(settings.database_path) as repo:
        search_svc = SearchService(repo._db)
        results = await search_svc.search(q, limit=10)
        
        out = []
        for r in results:
            out.append({
                "url": r["final_url"],
                "title": r.get("title", ""),
                "score": r["rank"]
            })
        return {"results": out}
