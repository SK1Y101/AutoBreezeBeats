async function toggleDevice() {
    const addr = this.dataset.address;
    const action = this.dataset.connected ? "disconnect" : "connect";

    const response = await fetch(`/devices/${action}`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({address: addr}),
    });

    if (response.ok) {
        if (this.dataset.connected) {
            this.classList.remove("connected");
            this.classList.add("disconnected");
        } else {
            this.classList.remove("disconnected");
            this.classList.add("connected");
        };
    } else {
        console.error(`Failed to toggle connection for ${addr}`);
    };
}

async function fetchDevices() {
    const response = await fetch("/devices");
    const devices = await response.json();
    const deviceList = document.getElementById("device-list");
    const deviceTable = document.createElement("ul");

    devices.forEach(device => {
        const deviceItem = document.createElement("button");
        deviceItem.dataset.address = device.address;
        deviceItem.dataset.connected = device.connected;

        deviceItem.textContent = device.name + " - " + device.address;

        if (device.connected) {
            deviceItem.classList.add("connected");
        }
        else {
            deviceItem.classList.add("disconnected");
        }

        deviceItem.addEventListener("click", toggleDevice);

        deviceTable.appendChild(deviceItem);
    });

    deviceList.replaceChildren(deviceTable);
}

document.addEventListener("DOMContentLoaded", () => {
    setInterval(fetchDevices, 10000);
});
