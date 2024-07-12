import { initialiseDateTime } from './datetime.js';
import { initialiseDevices } from './devices.js';
import { initialisePlayback } from './playback.js';

document.addEventListener("DOMContentLoaded", () => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    const socket = new WebSocket(wsUrl);

    socket.onopen = () => console.log("Opened websocket");
    socket.onerror = error => console.error("WebSocket error:", error);
    socket.onclose = event => {
        if (event.wasClean) {
            console.log(`Closed socket: ${event.code} ${event.reason}`);
        }
        else {
            console.error("WebSocket closed unexpectedly.");
        }
    };

    initialiseDateTime(socket);
    initialiseDevices(socket);
    initialisePlayback(socket);

    function closeSocket() {
        if (socket) {
            socket.close();
        };
    };

    window.addEventListener("unload", closeSocket);
    window.addEventListener("beforeunload", closeSocket);
});
