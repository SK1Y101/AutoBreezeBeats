document.addEventListener("DOMContentLoaded", () => {
    const videoForm = document.getElementById("VideoForm");
    const playPauseButton = document.getElementById("play-pause");
    const skipPreviousButton = document.getElementById("skip-previous");
    const skipNextButton = document.getElementById("skip-next");
    const skipFullButton = document.getElementById("skip-full");
    const progressElement = document.getElementById("progress");
    const queueList = document.getElementById("queue-list");

    let socket = null;
    let isPlaying = false;

    videoForm.addEventListener("submit", handleVideoFormSubmit);
    playPauseButton.addEventListener("click", handlePlayPause);
    skipPreviousButton.addEventListener("click", () => sendMessage("prev_chapter"));
    skipNextButton.addEventListener("click", () => sendMessage("next_chapter"));
    skipFullButton.addEventListener("click", () => sendMessage("next_video"));

    initializeWebSocket();

    window.addEventListener("unload", closeWebSocket);

    function toTimeString(seconds) {
        var date = new Date(0);
        date.setSeconds(seconds);
        var timeString = date.toISOString().substring(11, 19);
        return timeString;
    };

    function handleVideoFormSubmit(event) {
        event.preventDefault();
        const formData = new FormData(videoForm);
        const url = "/video";

        fetch(url, {
            method: "POST",
            body: formData,
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error("Network error when adding new video to queue!");
                }
                return response.json();
            })
            .then(data => {
                console.log("Video queued successfully:", data);
            })
            .catch(error => {
                console.error("Error adding video to queue:", error);
            });
    }

    function handlePlayPause() {
        sendMessage(isPlaying ? "pause" : "play");
        isPlaying = !isPlaying;
        playPauseButton.textContent = isPlaying ? "⏸️" : "▶";
    }

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
    }

    function handleWebSocketMessage(event) {
        const message = JSON.parse(event.data);

        if (message.progress !== undefined && message.duration !== undefined) {
            const progress = message.progress;
            const duration = message.duration;
            progressElement.value = (progress / duration) * 100;
        }

        if (message.queue !== undefined) {
            buildQueue(message.queue);
        }
    }

    function sendMessage(action) {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(action);
        }
    }

    function closeWebSocket() {
        if (socket) {
            socket.close();
        }
    }

    function buildQueue(queue) {
        queueList.innerHTML = "";

        queue.slice(0,10).forEach(video => {
            const videoRow = document.createElement("tr");

            const thumbCol = document.createElement("td");
            const titleCol = document.createElement("td");
            const thumbnail = document.createElement("img");

            thumbnail.style = "height:72px; width:128px;";
            thumbnail.src = video.thumbnail;
            titleCol.textContent = video.title + " ("+toTimeString(video.duration)+")";

            thumbCol.appendChild(thumbnail);
            videoRow.appendChild(thumbCol);
            videoRow.appendChild(titleCol);
            queueList.appendChild(videoRow);
        });

        if (queue.length > 10) {
            const videoRow = document.createElement("tr");
            const titleCol = document.createElement("td");

            const len = queue.length - 10;
            titleCol.textContent = `... Queue contains ${len} more item${len === 1 ? "" : "s"} ...`;

            videoRow.appendChild( document.createElement("td"));
            videoRow.appendChild(titleCol);
            queueList.appendChild(videoRow);
        };
    }
});
