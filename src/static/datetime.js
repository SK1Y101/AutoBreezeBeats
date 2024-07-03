export function initialiseDateTime(socket) {
    setdate();
    setInterval(setdate, 1000);

    socket.addEventListener("message", handleWebSocketMessage);

    function handleWebSocketMessage(event) {
        const message = JSON.parse(event.data);

        if (message.weather !== undefined) {
            document.getElementById("weather").textContent = message.weather.summary;
        };
    };

    function setdate() {
        var date = new Date();
        var displayTime = date.toLocaleTimeString("en-GB");
        document.getElementById("datetime").innerHTML = displayTime;
    };
};
