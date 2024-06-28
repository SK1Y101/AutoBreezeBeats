document.addEventListener("DOMContentLoaded", () => {
    const deviceList = document.getElementById("device-list");
    const weather = document.getElementById("weather");
    const autoplay = document.getElementById("autoplay");
    const sinkReset = document.getElementById("reset-sink");

    autoplay.addEventListener("click", autoPlayToggle);
    sinkReset.addEventListener("click", setSink);

    let socket = null;

    initializeWebSocket();

    window.addEventListener("unload", closeWebSocket);

    function initializeWebSocket() {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        socket = new WebSocket(wsUrl);

        socket.onopen = () => console.log("WebSocket connection established.");
        socket.onmessage = handleWebSocketMessage;
        socket.onerror = error => console.error("WebSocket error:", error);
        socket.onclose = event => {
            if (event.wasClean) {
                console.log(`WebSocket connection closed cleanly, code=${event.code}, reason=${event.reason}`);
            } else {
                console.error("WebSocket connection closed unexpectedly.");
            }
        };
    };

    function closeWebSocket() {
        if (socket) {
            socket.close();
        }
    };

    function handleWebSocketMessage(event) {
        const message = JSON.parse(event.data);

        if (message.devices !== undefined) {
            buildDevices(message.devices);
        }

        // TODO: This is technically the wrong place, but I don't want to open another socket
        if (message.weather !== undefined) {
            weather.textContent = message.weather.summary;
        }

        if (message.autoplay !== undefined) {
            if (message.autoplay) {
                autoplay.classList.add("connected");
                autoplay.classList.remove("disconnected");
            }
            else {
                autoplay.classList.add("disconnected");
                autoplay.classList.remove("connected");
            }
        }
    };

    function buildDevices(devices) {
        deviceList.innerHTML = "";
        const deviceTable = document.createElement("ul");
    
        devices.forEach(device => {
            const deviceItem = document.createElement("button");
            const devicePlay = document.createElement("button");
            deviceItem.dataset.address = device.address;
            devicePlay.dataset.address = device.address;
    
            deviceItem.textContent = device.name + " - " + device.address;
            devicePlay.textContent = "Set as playback device"
    
            if (device.connected) {
                deviceItem.classList.add("connected");
            }
            else {
                deviceItem.classList.add("disconnected");
            }
    
            if (device.primary) {
                devicePlay.classList.add("connected");
            }
            else {
                devicePlay.classList.add("disconnected");
            }
    
            deviceItem.addEventListener("click", toggleDevice);
            devicePlay.addEventListener("click", setSink);
    
            deviceTable.appendChild(deviceItem);
            deviceTable.appendChild(devicePlay);
        });
    
        deviceList.replaceChildren(deviceTable);
    };

    async function setSink() {
        const addr = this.dataset??false ? this.dataset.address : null;
        fetch("/devices/set-sink", {
            method:"PUT",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({address: addr}),
        })
        .then(response => {
            console.log(response);
            if (!response.ok) {
                console.error("Could not set sink")
            }
        })
        .catch(error => console.error("Could not set sink", error));
    }

    async function autoPlayToggle() {
        fetch("/toggle-autoplay", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ toggle: true }),
        })
            .then(response => {
                console.log(response);
                if (!response.ok) {
                    console.error("Could not toggle autoplay")
                }
            })
            .catch(error => console.error("Could not toggle autoplay", error));
    };

    async function toggleDevice() {
        const addr = this.dataset.address;
        const action = this.classList.contains("disconnected") ? "connect" : "disconnect";

        await fetch(`/devices/${action}`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({address: addr}),
        })
        .then(response => {
            console.log(response);
            if (response.ok) {
                if (action === "connect") {
                    this.classList.remove("connected");
                    this.classList.add("disconnected");
                } else {
                    this.classList.remove("disconnected");
                    this.classList.add("connected");
                };
            } else {
                console.error(`Failed to toggle connection for ${addr}`);
            };
        })
        .catch(error => console.error('Connection failed:', error))
    };
});