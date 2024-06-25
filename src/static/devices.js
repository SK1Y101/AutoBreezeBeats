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
}

async function fetchDevices() {
    const response = await fetch("/devices");
    const devices = await response.json();
    const deviceList = document.getElementById("device-list");
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
}

document.addEventListener("DOMContentLoaded", () => {
    setInterval(fetchDevices, 2500);
});
