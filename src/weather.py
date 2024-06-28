from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import Enum
from logging import Logger
from typing import Any, Optional, Type

import requests

from .common import DEFAULT_INTERVAL, BreezeBaseClass, load_data
from .playback import PlaybackManager
from .websockets import Notifier, Updates


def current_time() -> datetime:
    return datetime.now(UTC)


class TimePeriod(Enum):
    # dawn = "dawn"
    morning = "morning"
    day = "day"
    # dusk = "dusk"
    evening = "evening"
    night = "night"


class WeatherType(Enum):
    clear = "clear"
    clouds = "clouds"
    drizzle = "drizzle"
    rain = "rain"
    thunderstorm = "thunderstorm"
    snow = "snow"
    mist = "mist"
    # conditions we don't use but might recieve
    dust = "mist"
    atmosphere = "mist"


@dataclass
class Weather:
    weather: str
    description: str
    temperature: float
    sunrise: int | float
    sunset: int | float

    def __str__(self) -> str:
        return f"<< Weather {self.weather} at {self.time_of_day.name} >>"

    @property
    def local_sunrise(self) -> datetime:
        return datetime.fromtimestamp(self.sunrise, UTC)

    @property
    def local_sunset(self) -> datetime:
        return datetime.fromtimestamp(self.sunset, UTC)

    @property
    def time_of_day(self) -> TimePeriod:
        now = current_time()
        sunrise = self.local_sunrise
        sunset = self.local_sunset
        midday = sunrise + (sunset - sunrise) / 2

        if now <= sunrise - timedelta(minutes=30):
            return TimePeriod.night
        elif now <= sunrise + timedelta(minutes=30):
            return TimePeriod.morning  # TimePeriod.dawn
        elif now <= midday:
            return TimePeriod.morning
        elif now <= sunset - timedelta(minutes=30):
            return TimePeriod.day
        elif now <= sunset + timedelta(minutes=30):
            return TimePeriod.night  # TimePeriod.dusk
        elif now <= sunset + timedelta(hours=2):
            return TimePeriod.evening
        else:
            return TimePeriod.night

    @property
    def type_of_weather(self) -> WeatherType:
        return WeatherType(self.weather.lower().split()[0])

    @property
    def summary(self) -> str:
        return f"{self.time_of_day.value} {self.type_of_weather.value}"

    @property
    def to_dict(self) -> dict[str, Any]:
        return {
            "weather": self.weather,
            "summary": self.summary,
            "description": self.description,
            "temperature": self.temperature,
            "sunrise": self.local_sunrise.astimezone().isoformat(),
            "sunset": self.local_sunset.astimezone().isoformat(),
            "tod": self.time_of_day.name,
        }


class WeatherManager(BreezeBaseClass):
    def __init__(
        self,
        parent_logger: None | Logger,
        notifier: Notifier,
        playback_manager: PlaybackManager,
    ) -> None:
        super().__init__("weather", parent_logger)

        self.notifier = notifier
        self.weather_task: None | asyncio.Task = None
        self.autoplay_task: None | asyncio.Task = None

        self.playback_manager = playback_manager
        self.playback_timeout = 20

        self.weather: Weather | None = None

        self.get_config()

        date = current_time().date()

        self.default_weather = Weather(
            "Clear sky",
            "Default weather",
            21,
            datetime.combine(date, time(6, 0, 0)).timestamp(),
            datetime.combine(date, time(18, 0, 0)).timestamp(),
        )

        notifier.register_callback(self.get_current_weather)

        self.log(
            self.logger.info,
            f"Weather Initialised at ({self.lat}, {self.lon})"
            f" songs: {len(self.song_mapping)}",
        )

    async def start(
        self,
        auto_playback_interval: timedelta = DEFAULT_INTERVAL,
        fetch_weather_interval: timedelta = DEFAULT_INTERVAL,
    ) -> None:
        await self.start_fetch_weather(fetch_weather_interval.total_seconds())
        await self.automate_playback(auto_playback_interval.total_seconds())

    async def automate_playback(self, auto_playback_interval: float = 1) -> None:
        if self.autoplay_task and not self.autoplay_task.done():
            self.log(self.logger.warn, "Auto Playback task already active")
            return
        self.log(self.logger.info, "Started auto playback")
        self.autoplay_task = asyncio.create_task(
            self.playback_update_loop(auto_playback_interval),
            name="Playback automation",
        )

    async def playback_update_loop(self, auto_playback_interval: float = 1) -> None:
        self.log(
            self.logger.info,
            f"Starting autoplayback loop with interval {auto_playback_interval}s",
        )
        try:
            start_time = current_time()
            while True:
                queue_time = (current_time() - start_time).total_seconds()
                # if it's been empty for the timeout length, queue a song
                if queue_time > self.playback_timeout:
                    self.log(
                        self.logger.debug,
                        f"Queue empty time ({queue_time}) exceeds"
                        f" playback timeout ({self.playback_timeout}).",
                    )
                    self.queue_appropriate_song()
                    start_time = current_time()
                # Reset the timer if a song is in the queue
                if self.playback_manager.queue.qsize() > 0:
                    start_time = current_time()
                else:
                    self.log(
                        self.logger.debug,
                        f"Queue empty for {queue_time:.2f}s",
                    )
                await asyncio.sleep(auto_playback_interval)
        except asyncio.CancelledError:
            self.log(self.logger.info, "Autoplayback loop cancelled")
        except Exception as e:
            self.log(self.logger.error, f"Error during autoplayback: {e}")

    async def start_fetch_weather(self, fetch_weather_interval: float = 1) -> None:
        if self.weather_task and not self.weather_task.done():
            self.log(self.logger.warn, "Weather task already active")
            return
        self.log(self.logger.info, "Started weather task")
        self.weather_task = asyncio.create_task(
            self.fetch_weather_loop(fetch_weather_interval), name="Send weather data"
        )

    async def fetch_weather_loop(self, fetch_weather_interval: float = 1) -> None:
        self.log(
            self.logger.info,
            f"Starting weather update loop with interval {fetch_weather_interval}s",
        )
        try:
            while True:
                self.fetch_weather_from_api()
                await asyncio.sleep(fetch_weather_interval)
        except asyncio.CancelledError:
            self.log(self.logger.info, "Weather loop cancelled")
        except Exception as e:
            self.log(self.logger.error, f"Error during weather: {e}")

    def fetch_from_api(self, url: str) -> Optional[Any]:
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            self.log(self.logger.error, f"Error fetching data: {e}")
            return None

    def get_config(self) -> None:
        conf = load_data("config.yaml")["weather"]
        self.api_key = conf["api_key"]

        # default to london GB
        lat: int = conf["location"].get("latitude", 51.5073219)
        lon: int = conf["location"].get("longitude", -0.1276474)

        if "city" in conf["location"]:
            city = conf["location"]["city"]
            country = conf["location"]["country"]
            if locations := self.fetch_from_api(
                "http://api.openweathermap.org/geo/1.0/direct?"
                f"q={city},{country}&limit=1&appid={self.api_key}"
            ):
                loc_dict = locations[0]
                lat = loc_dict["lat"]
                lon = loc_dict["lon"]
        self.lat, self.lon = lat, lon

        songs = load_data("stored_songs.yaml")["songs"]
        self.song_mapping = {
            song["song_url"]: {"weather": song["weather"], "time": song["time"]}
            for song in songs
        }

    def fetch_weather_from_api(self) -> None:
        if weather_dict := self.fetch_from_api(
            "https://api.openweathermap.org/data/2.5/weather?"
            f"lat={self.lat}&lon={self.lon}&appid={self.api_key}"
            "&units=metric"
        ):
            self.log(self.logger.debug, weather_dict)
            self.weather = Weather(
                weather=weather_dict["weather"][0]["main"],
                description=weather_dict["weather"][0]["description"],
                temperature=weather_dict["main"]["temp"],
                sunrise=weather_dict["sys"]["sunrise"],
                sunset=weather_dict["sys"]["sunset"],
            )

    @property
    def weather_now(self) -> Weather:
        return self.weather or self.default_weather

    def get_current_weather(self) -> Updates:
        log = self.logger.getChild("weather_update")
        if weather := self.weather:
            log.debug(weather)
            return {"weather": weather.to_dict}
        log.debug("Sending default weather")
        return {"weather": self.default_weather.to_dict}

    def queue_appropriate_song(self) -> None:
        """
        Determine all the songs that fit the weather/time.
        If nothing exactly fits, only fit the weather.
        Otherwise, fit the time only.
        """
        weather = self.weather_now
        type_of_weather = weather.type_of_weather.value
        time_of_day = weather.time_of_day.value
        self.log(self.logger.info, f"Queuing song for {weather.summary}")

        def index_of(value: str, enum: Type[Enum]) -> int:
            return [enum(e).value for e in enum].index(enum[value].value)

        def distance_to(target: int, values: list[str] | None, enum: Type[Enum]) -> int:
            if values is None:
                return 0
            return min(abs(index_of(value, enum) - target) for value in values)

        time_idx = index_of(time_of_day, TimePeriod)
        weather_idx = index_of(type_of_weather, WeatherType)

        ranking: dict[int, list[str]] = {}
        for url, song in self.song_mapping.items():
            # distance from current weather/time
            time_dist = distance_to(time_idx, song["time"], TimePeriod)
            weather_dist = distance_to(weather_idx, song["weather"], WeatherType)
            # prioritise correct weather over correct time
            rank = weather_dist * 10 + time_dist
            if rank in ranking:
                ranking[rank].append(url)
            else:
                ranking[rank] = [url]

        ranking = dict(sorted(ranking.items()))
        self.log(self.logger.debug, "Song rank:", ranking)

        shuffle_size = 5

        to_play = ranking.get(0, [])
        if not to_play:
            self.logger.debug(f"No songs perfectly match {weather.summary}")
        # ensure we have a couple of songs to shuffle
        if len(to_play) < shuffle_size:
            weathers = []
            for weather_type in list(WeatherType):
                if weather_type.value not in weathers:
                    weathers.append(weather_type.value)
            skip = 10
            for _rank, songs in ranking.items():
                if len(to_play) >= shuffle_size:
                    break
                to_play.extend(songs)
                if _rank >= skip:
                    upper = weather_idx + skip // 10
                    lower = weather_idx - skip // 10

                    msg = ["Relaxing weather match to include"]
                    if upper < len(weathers):
                        msg += [weathers[upper]]
                    if lower > 0:
                        if len(msg) > 1:
                            msg += ["and"]
                        msg += [weathers[lower]]
                    self.logger.debug(" ".join(msg))
                    skip += 10

        self.log(self.logger.debug, f"Songs to shuffle for {weather.summary}", to_play)
        chosen_song = random.choice(to_play)

        if self.playback_manager.current_song is None:
            self.playback_manager.set_song_url(chosen_song)
            self.playback_manager.play()
        else:
            self.playback_manager.queue_video_url(chosen_song)
