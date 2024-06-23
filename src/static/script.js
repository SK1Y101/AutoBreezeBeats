setdate = function() {
    var date = new Date();
    var displayTime = date.toLocaleTimeString("en-GB"
    );

    document.getElementById('datetime').innerHTML = displayTime;
}

window.onload = function() {
    setdate()
    setInterval(function(){
        setdate()
    }, 1000);
}