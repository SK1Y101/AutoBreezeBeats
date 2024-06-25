document.getElementById("VideForm").addEventListener(
    "submit", function(event) {
        event.preventDefault();

        const formData = new FormData(this);
        const url = "/video";

        fetch(url, {
            method: "POST",
            body: formData,
        })
        .then(response => {
            if (!response.ok) {
                throw new Error("Network error when adding new video to queue!");
            };
            return response.json();
        })
        .then(data => {
            console.log("Video queued successfully:", data);
        })
        .catch(error => {
            console.error("Error adding video to queue:", error);
        });
    });