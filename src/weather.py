from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import Enum
from logging import Logger
from typing import Any, Optional, Type

import requests
from pydantic import BaseModel

from .common import DEFAULT_INTERVAL, BreezeBaseClass, current_time, load_data
from .playback import PlaybackManager
from .websockets import Notifier, Updates


class ToggleAction(BaseModel):
    toggle: bool = False


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
            return TimePeriod.evening  # TimePeriod.dusk
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

        self.autoplaying: bool = True
        self.shuffle_sample_size = 5
        self.auto_queue_length = 4

        self.playback_manager = playback_manager
        self.playback_timeout = 10

        self.weather: Weather | None = None
        self.song_mapping: dict[str, dict[str, list[str]]] = {}

        self.song_store = "stored_songs.yaml"

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
        notifier.register_callback(self.get_autoplay_status)

        self.log(
            self.logger.info,
            f"Weather Initialised at ({self.lat}, {self.lon})"
            f" songs: {len(self.song_mapping)}",
        )

    async def start(
        self,
        weather_autoplay_interval: timedelta = DEFAULT_INTERVAL,
        fetch_weather_interval: timedelta = DEFAULT_INTERVAL,
    ) -> None:
        await self.start_fetch_weather(fetch_weather_interval.total_seconds())
        await self.automate_playback(weather_autoplay_interval.total_seconds())

    async def automate_playback(self, weather_autoplay_interval: float = 1) -> None:
        if self.autoplay_task and not self.autoplay_task.done():
            self.log(self.logger.warn, "Auto Playback task already active")
            return
        self.log(self.logger.info, "Started auto playback")
        self.autoplay_task = asyncio.create_task(
            self.playback_update_loop(weather_autoplay_interval),
            name="Playback automation",
        )

    async def playback_update_loop(self, weather_autoplay_interval: float = 1) -> None:
        self.log(
            self.logger.info,
            f"Starting autoplayback loop with interval {weather_autoplay_interval}s",
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
                    await self.queue_appropriate_song()
                    start_time = current_time()

                if not self.autoplaying:
                    start_time = current_time()

                # Reset the timer if a song is in the queue
                if self.playback_manager.queue.qsize() >= self.auto_queue_length:
                    start_time = current_time()
                else:
                    msg = (
                        f"Queue shorter than wanted for {queue_time:.2f}s"
                        if self.autoplaying
                        else "Autoplaying halted"
                    )
                    self.log(self.logger.debug, msg)
                await asyncio.sleep(weather_autoplay_interval)
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

        self.get_songs()

    def get_songs(self, quiet: bool = False) -> None:
        if song_config := load_data(self.song_store, quiet=True):
            songs = song_config["songs"]
            self.song_mapping = {
                song["song_url"]: {
                    "name": song["name"],
                    "weather": song["weather"],
                    "time": song["time"],
                }
                for song in songs
                if song.get("song_url", None)
            }
            if not quiet:
                self.log(
                    self.logger.debug, "Loaded songs from store:", self.song_mapping
                )
        else:
            self.log(self.logger.debug, f"No songs defined in {self.song_store}!")

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

    def get_autoplay_status(self) -> Updates:
        log = self.logger.getChild("autoplay_update")
        log.debug(f"Autoplaying {self.autoplaying and bool(self.song_mapping)}")
        return {"autoplay": self.autoplaying and bool(self.song_mapping)}

    async def queue_appropriate_song(self) -> None:
        """
        Determine all the songs that fit the weather/time.
        If nothing exactly fits, only fit the weather.
        Otherwise, fit the time only.
        """
        self.get_songs(quiet=True)
        if not self.song_mapping:
            return

        def index_of(value: str, enum: Type[Enum]) -> int:
            return [enum(e).value for e in enum].index(enum[value].value)

        def distance_to(target: int, values: list[str] | None, enum: Type[Enum]) -> int:
            if values is None:
                return 0
            return min(abs(index_of(value, enum) - target) for value in values)

        weather = self.weather_now
        weathers: list[str] = []

        ranking: dict[int, list[list[str]]] = {}
        type_of_weather = weather.type_of_weather.value
        time_of_day = weather.time_of_day.value
        self.log(self.logger.info, f"Queuing song for {weather.summary}")

        time_idx = index_of(time_of_day, TimePeriod)
        weather_idx = index_of(type_of_weather, WeatherType)
        for weather_type in list(WeatherType):
            if weather_type.value not in weathers:
                weathers.append(weather_type.value)

        alread_queued = [video.url for video in self.playback_manager._whole_queue_]
        for url, song in self.song_mapping.items():
            # don't queue songs that already exist
            if url in alread_queued:
                continue
            this_song = [url, str(song["name"])]
            # distance from current weather/time
            time_dist = distance_to(time_idx, song["time"], TimePeriod)
            weather_dist = distance_to(weather_idx, song["weather"], WeatherType)
            # prioritise correct weather over correct time
            rank = weather_dist * 10 + time_dist
            if rank in ranking:
                ranking[rank].append(this_song)
            else:
                ranking[rank] = [this_song]

        ranking = dict(sorted(ranking.items()))

        if 0 not in ranking:
            self.logger.debug(f"No songs perfectly match {weather.summary}")

        skip = 10
        song_listing: list[list[str]] = []
        rank_listing: list[int] = []
        for _rank, songs in ranking.items():
            if len(song_listing) >= self.shuffle_sample_size:
                break
            song_listing.extend(songs)
            rank_listing.extend([_rank] * len(songs))
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

        self.log(
            self.logger.debug, f"Songs to shuffle for {weather.summary}", *song_listing
        )
        [[chosen_song_url, _]] = random.choices(
            song_listing, [1 + max(rank_listing) - weight for weight in rank_listing]
        )

        if self.playback_manager.current_song is None:
            self.playback_manager.set_song_url(chosen_song_url)
            self.playback_manager.play()
        else:
            self.playback_manager.queue_video_url(chosen_song_url)
