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
    end: int

    @property
    def to_dict(self) -> dict[str, str | int]:
        return {"title": self.title, "time": self.time}

    def __str__(self) -> str:
        return f"<< Chapter {self.title} at {self.time} >>"


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
                end = chapter.get("end_time")
                if start is not None and title:
                    found.append(Chapter(title=title, time=start, end=end))
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


class PlaybackManager(BreezeBaseClass):
    def __init__(self, parent_logger: None | Logger, notifier: Notifier) -> None:
        super().__init__("playback", parent_logger)

        self.queue: list[Video] = []

        self.chapter_task: Optional[asyncio.Task] = None

        self._initialise_vlc_()
        self._previous_volume_ = self.volume
        self._post_init_vlc_()

        notifier.register_callback(self.get_status)

    def _initialise_vlc_(self) -> None:
        self.vlc_instance = vlc.Instance("--no-xlib")
        self.player = self.vlc_instance.media_player_new()
        events = self.player.event_manager()
        events.event_attach(
            vlc.EventType.MediaPlayerEncounteredError, self._log_vlc_error_
        )
        events.event_attach(vlc.EventType.MediaPlayerEndReached, self._vlc_ended_song_)

    def _post_init_vlc_(self) -> None:
        self.player.audio_set_volume(self.read_config("volume", 100))

    def _log_vlc_error_(self, event: vlc.Event) -> None:
        self.log(
            self.logger.getChild("vlc").error, "VLC experienced an error, skipping"
        )
        self._vlc_ended_song_(event)

    def _vlc_ended_song_(self, event: vlc.Event) -> None:
        self.log(self.logger.getChild("vlc").debug, "VLC reached song completion")
        # It's easier to just create a new VLC instance than handle the error
        self._initialise_vlc_()
        self._post_init_vlc_()
        self.skip_queue()
        self.play()

    def _load_video_(self, video: Video) -> None:
        self.write_config("volume", self.volume)
        self.player.stop()
        media = self.vlc_instance.media_new(video.audio_url())
        self.player.set_media(media)
        self.volume = self.read_config("volume", 100)

    # callbacks and updates
    def stop(self) -> None:
        self.write_config("volume", self.volume)
        self.volume = self._previous_volume_
        self.player.stop()

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
                if (song := self.current_song) and song.has_chapters:
                    chapters = song.chapters
                    cchapter = song.current_chapter
                    current = chapters[cchapter]
                    time = self.elapsed

                    if time >= current.end:
                        for idx, c in enumerate(chapters[cchapter:]):
                            if c.end > time:
                                cchapter = song.current_chapter + idx
                                break
                        else:
                            cchapter = len(chapters)
                    elif time < current.time:
                        for idx, c in enumerate(chapters[cchapter::-1]):
                            if c.time < time:
                                cchapter = song.current_chapter - idx
                                break
                        else:
                            cchapter = 0

                    self.current_song.current_chapter = cchapter

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
            # booleans
            "playing": self.is_playing,
            # videos
            "queue": self.queue_dict,
            "chapter": False,
            "current": False,
        }
        if self.is_playing:
            info["volume"] = self.volume
        if song := self.current_song:
            info["current"] = song.chapterless_dict
            if song.has_chapters:
                info["chapter"] = song.chapters[song.current_chapter].to_dict
        return info

    # Queue interactions
    @property
    def is_playing(self) -> bool:
        return bool(self.has_song and self.player.is_playing())

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
        if self.queue:
            self._load_video_(self.queue[0])

    def add_to_queue(self, url: str) -> Video:
        video = Video(url)
        self.queue.append(video)
        if not self.player.get_media():
            self.load_from_queue()
        return video

    # playback interaction
    @property
    def volume(self) -> int:
        return self.player.audio_get_volume()

    @volume.setter
    def volume(self, vol: int) -> None:
        _vol_ = min(100, max(0, vol))
        self.logger.debug(f"setting volume to {_vol_}")
        self.player.audio_set_volume(_vol_)

    def play(self) -> None:
        self.player.play()

    def pause(self) -> None:
        self.player.pause()

    @property
    def elapsed(self) -> float:
        if self.has_song:
            return max(0, self.player.get_time() / 1000)
        return 0.0

    @elapsed.setter
    def elapsed(self, seconds: float) -> None:
        if self.has_song:
            self.player.set_time(int(seconds * 1000))

    @property
    def duration(self) -> float:
        if song := self.current_song:
            return song.duration
        return 0.0

    def skip_next_chapter(self) -> None:
        if song := self.current_song:
            if song.has_chapters:
                this_chapter = song.current_chapter
                next_chapter = min(len(song.chapters) - 1, this_chapter + 1)

                if this_chapter == next_chapter:
                    self.skip_queue()
                else:
                    self.elapsed = song.chapters[next_chapter].time

    def skip_last_chapter(self) -> None:
        if song := self.current_song:
            if song.has_chapters:
                this_chapter = song.current_chapter
                last_chapter = max(0, this_chapter - 1)

                # skip back if we're close to the start of the current
                if song.chapters[this_chapter].time + 5 > self.elapsed:
                    self.elapsed = song.chapters[last_chapter].time
                # otherwise skip to the start of the current
                else:
                    self.elapsed = song.chapters[this_chapter].time

    def skip_queue(self) -> None:
        playing = self.is_playing
        removed = self.queue.pop(0)
        self.log(self.logger.debug, "Removed video from queue", removed)
        self.load_from_queue()
        if playing and self.has_song:
            self.play()
