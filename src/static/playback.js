export function initialisePlayback(socket) {
    const videoForm = document.getElementById("VideoForm");
    const playPauseButton = document.getElementById("play-pause");
    const skipPreviousButton = document.getElementById("skip-previous");
    const skipNextButton = document.getElementById("skip-next");
    const skipFullButton = document.getElementById("skip-full");
    const progressElement = document.getElementById("progress");
    const queueList = document.getElementById("queue-list");

    const currentTitle = document.getElementById("current-title");
    const currentThumb = document.getElementById("current-thumbnail");
    const currentChapter = document.getElementById("current-chapter");
    const currentElapsed = document.getElementById("elapsed-time");
    const currentDuration = document.getElementById("total-time");

    let isPlaying = false;
    let chapterEnable = false;

    videoForm.addEventListener("submit", handleVideoFormSubmit);
    playPauseButton.addEventListener("click", handlePlayPause);
    skipPreviousButton.addEventListener("click", () => sendMessage("prev_chapter"));
    skipNextButton.addEventListener("click", () => sendMessage("next_chapter"));
    skipFullButton.addEventListener("click", () => sendMessage("next_video"));

    socket.addEventListener("message", handleWebSocketMessage);

    function handleWebSocketMessage(event) {
        const message = JSON.parse(event.data);

        if (message.elapsed !== undefined) {
            currentElapsed.textContent = toTimeString(message.elapsed);
        };

        if (message.duration !== undefined) {
            currentElapsed.textContent = toTimeString(message.duration);
        };

        if (message.elapsed !== undefined && message.duration !== undefined) {
            const elapsed = message.elapsed;
            const duration = message.duration;

            currentElapsed.textContent = toTimeString(elapsed);
            currentDuration.textContent = toTimeString(duration);

            if (duration !== 0) {
                progressElement.value = (elapsed / duration) * 100;
            }
            else {
                progressElement.value = 0;
            };
        };

        if (message.current !== undefined) {
            const current = message.current;
            if (current === false) {
                currentTitle.textContent = "Now playing: Nothing (Queue a video to start)";
                currentThumb.src = "";
            }
            else {
                currentTitle.textContent = `Now playing: ${message.current.title}`;
                currentThumb.src = message.current.thumbnail;
            };
        };

        if (message.queue !== undefined) {
            buildQueue(message.queue);
        };

        if (message.playing !== undefined) {
            isPlaying = message.playing;
            playPauseButton.textContent = isPlaying ? "⏸️" : "▶";
        };

        if (message.chapters !== undefined) {
            chapterEnable = message.chapters;
            setDisabled(skipPreviousButton, chapterEnable);
            setDisabled(skipNextButton, chapterEnable);
        };

        if (message.current_chapter !== undefined) {
            const chapter = message.current_chapter;
            if (chapter === false) {
                currentChapter.textContent = "";
            }
            else {
                currentChapter.textContent = chapter.title;
            };
        };
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
    };

    function handlePlayPause() {
        sendMessage(isPlaying ? "pause" : "play");
        isPlaying = !isPlaying;
        playPauseButton.textContent = isPlaying ? "⏸️" : "▶";
    };

    function setDisabled(elem, enable) {
        const enabled = !elem.hasAttribute("disabled");
        if ((enabled && !enable) || (!enabled && enable)) {
            elem.toggleAttribute("disabled");
        };
    };

    function sendMessage(action) {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(action);
        };
    };

    function buildQueue(queue) {
        const maxQueueLength = 9;
        queueList.innerHTML = "";

        queue.slice(0, maxQueueLength).forEach(video => {
            const videoRow = document.createElement("tr");

            const thumbCol = document.createElement("td");
            const titleCol = document.createElement("td");
            const thumbnail = document.createElement("img");

            thumbnail.style = "height:72px; width:128px;";
            thumbnail.src = video.thumbnail;
            titleCol.textContent = video.title + " (" + toTimeString(video.duration) + ")";

            thumbCol.appendChild(thumbnail);
            videoRow.appendChild(thumbCol);
            videoRow.appendChild(titleCol);
            queueList.appendChild(videoRow);
        });

        if (queue.length > maxQueueLength) {
            const videoRow = document.createElement("tr");
            const titleCol = document.createElement("td");

            const len = queue.length - maxQueueLength;
            titleCol.textContent = `... Queue contains ${len} more item${len === 1 ? "" : "s"} ...`;

            videoRow.appendChild(document.createElement("td"));
            videoRow.appendChild(titleCol);
            queueList.appendChild(videoRow);
        };
    };

    function toTimeString(seconds) {
        var date = new Date(0);
        date.setSeconds(Math.max(0, seconds));
        var timeString = date.toISOString().substring(11, 19);
        return timeString;
    };
};
