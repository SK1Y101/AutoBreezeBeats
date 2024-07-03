import asyncio
import logging
from datetime import timedelta

# import rich
import yaml
from fastapi import FastAPI, Form, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .devices import (
    ConnectError,
    DeviceAction,
    DeviceManager,
    DisconnectError,
    SinkAction,
    SinkError,
)
from .host_device import get_device_details
from .playback import PlaybackManager
from .weather import ToggleAction, WeatherManager
from .websockets import WebSocketManager

application_details = {"title": "AutoBreezeBeats", "version": "0.4"}
initial_settings = {
    "volume": 50
}

with open("src/logging_conf.yaml", "r") as f:
    logging_config = yaml.safe_load(f)
logging.config.dictConfig(logging_config)
log = logging.getLogger(application_details["title"])

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="src/static"), name="static")
templates = Jinja2Templates(directory="src/templates")

ws_manager = WebSocketManager(log)
device_manager = DeviceManager(log, ws_manager.notifier)
playback_manager = PlaybackManager(log, ws_manager.notifier)
weather_manager = WeatherManager(log, ws_manager.notifier, playback_manager)


@app.on_event("startup")
async def startup() -> None:
    await device_manager.start(scanning_interval=timedelta(seconds=1))
    await playback_manager.start(skipping_interval=timedelta(seconds=0.25))
    await weather_manager.start(fetch_weather_interval=timedelta(minutes=2))
    await ws_manager.start(websocket_interval=timedelta(seconds=0.5))

    playback_manager.set_volume(initial_settings.get("volume", 50))


@app.on_event("shutdown")
async def shutdown() -> None:
    pass


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "application": application_details,
            "host": get_device_details(),
            "initial_settings": initial_settings,
        },
    )


@app.get("/devices")
async def list_devices() -> list[dict[str, str | bool]]:
    return device_manager.list_devices


@app.post("/devices/connect")
async def bluetooth_connect(action: DeviceAction):
    address = action.address
    log.info(f"request to connect {address} recieved")
    if not (device_manager.connect_device(address)):
        raise ConnectError(address)
    log.info(f"Successfully connected to {address}")
    return {"status": "Connected"}


@app.post("/devices/disconnect")
async def bluetooth_disconnect(action: DeviceAction):
    address = action.address
    log.info(f"request to disconnect {address} recieved")
    if not (device_manager.disconnect_device(address)):
        raise DisconnectError(address)
    log.info(f"Successfully disconnected from {address}")
    return {"status": "Disconnected"}


@app.put("/devices/set-sink")
async def bluetooth_sink(action: SinkAction):
    if address := action.address:
        log.info(f"Set {address} as new playback device")
        if not device_manager.set_sink(address):
            raise SinkError(f"Could not set sink to {address}")
        return {"message": f"{address} set as new sink"}
    else:
        log.info("Set default as playback device")
        if not device_manager.unset_sinks():
            raise SinkError("Could not set sink to default")
        return {"message": "default set as new sink"}


@app.post("/video")
async def load_video(url: str = Form(...)):
    log.info(f"Request to add {url} recieved")
    video = playback_manager.queue_video_url(url)
    return video.to_dict


@app.post("/toggle-autoplay")
async def toggle_autoplay(data: ToggleAction):
    log.info("Request to toggle autoplay recieved")
    if weather_manager.autoplaying:
        weather_manager.autoplaying = False
    else:
        weather_manager.autoplaying = True


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    async for data in ws_manager.recieve_data(websocket):
        match data:
            case "play":
                playback_manager.play()
            case "pause":
                playback_manager.pause()
            case "next_chapter":
                playback_manager.skip_next()
            case "prev_chapter":
                playback_manager.skip_prev()
            case "next_video":
                playback_manager.skip_queue()
            case _:
                if data.startswith("volume:"):
                    playback_manager.set_volume(int(data.split(":")[1]))
                else:
                    ws_manager.logger.warn(f"Unknown data {data}")


if __name__ == "__main__":
    import uvicorn

    try:
        uvicorn.run(app, log_config=logging_config)
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received, shutting down gracefully")
    finally:
        log.info(f"Setting volume to {playback_manager._previous_volume_}")
        playback_manager.set_volume(playback_manager._previous_volume_)
        tasks = asyncio.all_tasks()
        for task in tasks:
            log.info(f"Cancelling {task.get_name()}")
            task.cancel()
        asyncio.get_event_loop().run_until_complete(
            asyncio.gather(*tasks, return_exceptions=True)
        )
        log.info(f"Closing {application_details['name']}")
