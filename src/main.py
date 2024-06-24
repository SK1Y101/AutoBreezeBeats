from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .devices import ConnectError, DeviceAction, DisconnectError, device_manager
from .host_device import get_device_details

app = FastAPI()

app.mount("/static", StaticFiles(directory="src/static"), name="static")
templates = Jinja2Templates(directory="src/templates")

application_details = {"title": "AutoBreezeBeats", "version": "0.1"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "application": application_details,
            "host": get_device_details(),
        },
    )


@app.get("/devices")
async def list_devices() -> list[dict[str, str | bool]]:
    return device_manager.list_devices


@app.post("/devices/connect")
async def bluetooth_connect(action: DeviceAction):
    address = action.address
    print(f"request to connect {address} recieved")
    if not await device_manager.connect_device(address):
        raise ConnectError(address)
    return {"status": "Connected"}


@app.post("/devices/disconnect")
async def bluetooth_disconnect(action: DeviceAction):
    address = action.address
    print(f"request to connect {address} recieved")
    if not await device_manager.disconnect_device(address):
        raise DisconnectError(address)
    return {"status": "Disconnected"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
