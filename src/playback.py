import asyncio
from dataclasses import dataclass
from datetime import timedelta
from logging import Logger
from typing import Any, Optional

import vlc
import yt_dlp

from .common import BreezeBaseClass
from .websockets import Notifier, Updates


@dataclass
class Chapter:
    title: str
    time: int

    @property
    def to_dict(self) -> dict[str, str | int]:
        return {"title": self.title, "time": self.time}

    def __str__(self) -> str:
        return f"<< Chapter {self.time} at {self.time} >>"


class Video:
    def __init__(self, url: str) -> None:
        self.url = url
        self.title = "Unknown"
        self.duration = 0
        self.thumbnail = "Unknown"
        self.chapters: list[Chapter] = []

        self.current_chapter: int = 0

        self.ydl_opts = {"no_warnings": True, "noplaylist": True}

        self.get_info()

    def get_info(self) -> None:
        self.chapters = []
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            if info := ydl.extract_info(self.url, download=False):
                self.title = info["title"]
                self.duration = info["duration"]
                self.thumbnail = info["thumbnail"]
                self.chapters = self.get_chapters(info)

    def audio_url(self) -> str:
        """Ensure the audio url cannot expire."""
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            if info := ydl.extract_info(self.url, download=False):
                return self.get_audio(info)
        return "Unknown"

    def get_audio(self, info: dict[str, Any]) -> str:
        if audio_formats := [
            formats for formats in info["formats"] if formats.get("acodec") == "opus"
        ]:
            best_audio = max(audio_formats, key=lambda x: x["abr"])
            return best_audio["url"]
        else:
            print("No audio streams found.")
        return ""

    def get_chapters(self, info: dict[str, Any]) -> list[Chapter]:
        found = []
        if chapters := info.get("chapters"):
            for chapter in chapters:
                title = chapter.get("title")
                start = chapter.get("start_time")
                if start is not None and title:
                    found.append(Chapter(title=title, time=start))
        return found

    def __str__(self) -> str:
        return f"<< Video: {self.title} at {self.url} >>"

    @property
    def to_dict(self) -> dict[str, Any]:
        info = {
            "title": self.title,
            "thumbnail": self.thumbnail,
            "duration": self.duration,
        }
        if chapters := self.chapters:
            info["chapters"] = [chapter.to_dict for chapter in chapters]
        return info

    @property
    def chapterless_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.to_dict.items() if k != "chapters"}

    @property
    def has_chapters(self) -> bool:
        return self.chapters != []

    @property
    def next_chapter(self) -> int:
        return max(len(self.chapters), self.current_chapter + 1)

    @property
    def last_chapter(self) -> int:
        return min(0, self.current_chapter - 1)


class PlaybackManager(BreezeBaseClass):
    def __init__(self, parent_logger: None | Logger, notifier: Notifier) -> None:
        super().__init__("playback", parent_logger)

        self.queue: list[Video] = []

        self.chapter_task: Optional[asyncio.Task] = None

        self._initialise_vlc_()
        self._previous_volume_ = self.volume

        notifier.register_callback(self.get_status)

    def _initialise_vlc_(self) -> None:
        self.vlc_instance = vlc.Instance("--no-xlib")
        self.player = self.vlc_instance.media_player_new()
        events = self.player.event_manager()
        events.event_attach(
            vlc.EventType.MediaPlayerEncounteredError, self._log_vlc_error_
        )
        events.event_attach(vlc.EventType.MediaPlayerEndReached, self._vlc_ended_song_)

        self.volume = self.read_config("volume", 100)

    def _log_vlc_error_(self, event: vlc.Event) -> None:
        self.log(self.logger.getChild("vlc").error, "VLC experienced an error")

    def _vlc_ended_song_(self, event: vlc.Event) -> None:
        self.log(
            self.logger.getChild("vlc").debug, "VLC reached song completion"
        )
        # It's easier to just create a new VLC instance than handle the error
        self._initialise_vlc_()
        self.skip_queue()
        self.play()

    def _load_video_(self, video: Video) -> None:
        self.player.stop()
        media = self.vlc_instance.media_new(video.audio_url())
        self.player.set_media(media)

    # callbacks and updates
    async def start(self, chapter_interval: timedelta = timedelta(seconds=1)) -> None:
        await self.start_chapter_loop(chapter_interval.total_seconds())

    async def start_chapter_loop(self, interval: float = 1) -> None:
        if self.chapter_task and not self.chapter_task.done():
            self.log(self.logger.warn, "Chapter Scanning task active")
            return
        self.log(self.logger.info, "Started chapter scanning")
        self.chapter_task = asyncio.create_task(
            self.chapter_scanning_loop(interval),
            name="Chapter scanning",
        )

    async def chapter_scanning_loop(self, interval: float = 1) -> None:
        self.log(
            self.logger.info,
            f"Starting chapter scanning loop with interval {interval}s",
        )
        try:
            while True:
                if self.has_song:
                    song = self.current_song
                    if song and song.has_chapters:
                        chapters = song.chapters
                        current = song.current_chapter

                        if chapters[current].time < self.elapsed:
                            for idx, c in enumerate(chapters[current:]):
                                if c.time > self.elapsed:
                                    song.current_chapter = idx - 1
                            else:
                                song.current_chapter = len(song.chapters)
                        else:
                            for idx, c in enumerate(chapters[:current][::-1]):
                                if c.time < self.elapsed:
                                    song.current_chapter = idx
                            else:
                                song.current_chapter = 0

                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            self.log(self.logger.info, "Chapter scanning loop cancelled")
        except Exception as e:
            self.log(self.logger.error, f"Error during chapter scanning: {e}")

    def get_status(self) -> Updates:
        info: Updates = {
            #  values
            "elapsed": self.elapsed,
            "duration": self.duration,
            "volume": self.volume,
            # booleans
            "playing": self.is_playing,
            # videos
            "queue": self.queue_dict,
        }
        if song := self.current_song:
            info["chapters"] = song.has_chapters
            info["current"] = song.chapterless_dict
            if song.has_chapters:
                info["current_chapter"] = song.chapters[song.current_chapter].to_dict
        return info

    # Queue interactions
    @property
    def is_playing(self) -> bool:
        return self.has_song and self.player.is_playing()

    @property
    def has_song(self) -> bool:
        return len(self.queue) > 0

    @property
    def current_song(self) -> Optional[Video]:
        if self.has_song:
            return self.queue[0]
        return None

    @property
    def current_chapter(self) -> Optional[Chapter]:
        if song := self.current_song:
            return song.chapters[song.current_chapter]
        return None

    @property
    def queue_dict(self) -> list[dict[str, Any]]:
        return [video.chapterless_dict for video in self.queue[1:]]

    def load_from_queue(self) -> None:
        self._load_video_(self.queue[0])

    def add_to_queue(self, url: str) -> Video:
        video = Video(url)
        self.queue.append(video)
        return video

    # playback interaction
    @property
    def volume(self) -> int:
        return self.player.audio_get_volume()

    @volume.setter
    def volume(self, vol: int) -> None:
        self.player.audio_set_volume(min(100, max(0, vol)))

    def play(self) -> None:
        self.player.play()

    def pause(self) -> None:
        self.player.pause()

    @property
    def elapsed(self) -> float:
        if self.has_song:
            return self.player.get_time() / 1000
        return 0.0

    @elapsed.setter
    def elapsed(self, seconds: float) -> None:
        if self.has_song:
            self.player.set_time(seconds * 1000)

    @property
    def duration(self) -> float:
        if song := self.current_song:
            return song.duration
        return 0.0

    def skip_next_chapter(self) -> None:
        if song := self.current_song:
            if song.has_chapters:
                this_chapter = song.current_chapter
                next_chapter = song.next_chapter

                if this_chapter == next_chapter:
                    self.skip_queue()
                else:
                    self.elapsed = song.chapters[next_chapter].time

    def skip_last_chapter(self) -> None:
        if song := self.current_song:
            if song.has_chapters:
                this_chapter = song.current_chapter
                last_chapter = song.last_chapter

                if this_chapter == last_chapter:
                    # skip back if we're close to the start of the current
                    if self.elapsed + 2 > song.chapters[this_chapter].time:
                        self.elapsed = song.chapters[last_chapter].time
                    # otherwise skip to the strt of the current
                    else:
                        self.elapsed = song.chapters[this_chapter].time
                else:
                    self.elapsed = song.chapters[last_chapter].time

    def skip_queue(self) -> None:
        playing = self.is_playing
        removed = self.queue.pop(0)
        self.log(self.logger.debug, "Removed video from queue", removed)
        self.load_from_queue()
        if playing and self.has_song:
            self.play()
