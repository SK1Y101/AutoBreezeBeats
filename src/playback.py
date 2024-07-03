import asyncio
import queue
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from logging import Logger
from typing import Any, Generator, Optional

import vlc
import yt_dlp

from .common import BreezeBaseClass, current_time
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


class PlaybackManager(BreezeBaseClass):
    def __init__(self, parent_logger: None | Logger, notifier: Notifier) -> None:
        super().__init__("playback", parent_logger)

        self._configure_vlc_()

        self.skipping_task: None | asyncio.Task = None

        self.queue: queue.Queue[Video] = queue.Queue()
        self.current_song: Optional[Video] = None

        notifier.register_callback(self.get_current_song_update)
        notifier.register_callback(self.get_queue_update)

    def _configure_vlc_(self) -> None:
        self.vlc_instance = vlc.Instance("--no-xlib")

        self.player = self.vlc_instance.media_player_new()
        self._previous_volume_ = self.player.audio_get_volume()
        self.set_volume(100)

        events = self.player.event_manager()
        events.event_attach(
            vlc.EventType.MediaPlayerEncounteredError, self.handle_vlc_event
        )
        events.event_attach(vlc.EventType.MediaPlayerEndReached, self.handle_vlc_event)

    def handle_vlc_event(self, event: vlc.Event) -> None:
        if event.type == vlc.EventType.MediaPlayerEncounteredError:
            self.log(
                self.logger.error,
                "VLC Experienced an error, skipping to next song in the queue",
            )
            self.skip_queue()
        if event.type == vlc.EventType.MediaPlayerEndReached:
            self.log(
                self.logger.warn, "Reached end of song without triggering skipping loop"
            )
            self.skip_queue()
            if self.current_song:
                self.play()

    async def start(self, skipping_interval: timedelta) -> None:
        await self.start_skipping_loop(skipping_interval.total_seconds())

    async def start_skipping_loop(self, skipping_interval: float = 1) -> None:
        if self.skipping_task and not self.skipping_task.done():
            self.log(self.logger.warn, "playback skipping task already active")
            return
        self.log(self.logger.info, "Started playback skipping")
        self.skipping_task = asyncio.create_task(
            self.song_skipping_loop(skipping_interval),
            name="Playback skipping",
        )

    async def song_skipping_loop(self, skipping_interval: float = 1) -> None:
        self.log(
            self.logger.info,
            f"Starting playback skipping loop with interval {skipping_interval}s",
        )
        try:
            elapsed = 0.0
            skip_time = current_time()
            while True:
                if self.is_playing:
                    if self.duration - self.elapsed <= 1.0:
                        self.logger.debug("Reached end of song, skipping.")
                        self.skip_queue()

                    if self.elapsed != elapsed:
                        skip_time = current_time()

                    stuck_length = (current_time() - skip_time).total_seconds()

                    if stuck_length > 10:
                        self.logger.debug("Song stuck for 10s, skipping")
                        self.skip_queue()

                elapsed = self.elapsed
                await asyncio.sleep(skipping_interval)
        except asyncio.CancelledError:
            self.log(self.logger.info, "playback skipping loop cancelled")
        except Exception as e:
            self.log(self.logger.error, f"Error during playback skipping: {e}")

    @property
    def _queue_(self) -> list[Video]:
        return self.queue.queue

    @property
    def _whole_queue_(self) -> list[Video]:
        if self.current_song:
            return [self.current_song] + list(self._queue_)
        return list(self._queue_)

    @property
    def _all_(self) -> list[Video]:
        songs = self._queue_
        if self.current_song:
            songs.insert(0, self.current_song)
        return songs

    def get_current_song_update(self) -> Updates:
        info = {
            "playing": self.is_playing,
            "elapsed": self.elapsed,
            "duration": self.duration,
            "current": False,
            "chapters": False,
            "current_chapter": False,
        }
        if self.current_song:
            self.logger.getChild("song_update").debug(self.current_song)
            info["current"] = (
                self.current_song.chapterless_dict  # type:ignore [assignment]
            )
            info["chapters"] = self.current_song.chapters != []
            if chapter := self.current_chapter:
                info["current_chapter"] = chapter.to_dict  # type:ignore [assignment]
        return info

    def get_queue_update(self) -> Updates:
        queue = self.queue_list
        if queue:
            self.logger.getChild("queue_update").debug(queue)
        return {"queue": queue}

    @contextmanager
    def song_error(self) -> Generator[Video, None, None]:
        try:
            if not self.current_song:
                self.shift_queue()
            if self.current_song:
                yield self.current_song
            else:
                raise BufferError("No song currently exists to play!")
        except Exception as e:
            self.log(self.logger.error, f"Unexpected error: {e}")
        finally:
            pass

    def _load_(self, video: Video) -> None:
        if audio_url := self.run_with_timeout(video.audio_url):
            self.log(self.logger.info, f"Loading {video} into memory: ", audio_url)
            media = self.vlc_instance.media_new(audio_url)
            self.player.set_media(media)
            self.log(self.logger.info, f"Loaded {video} into player")
        else:
            self.skip_queue()

    def set_song(self, video: Video) -> None:
        self._load_(video)
        self.current_song = video

    def set_song_url(self, url: str) -> None:
        self.set_song(Video(url))

    def set_volume(self, volume: int) -> None:
        self.player.audio_set_volume(max(0, min(100, volume)))

    def _stop_(self) -> None:
        self.log(self.logger.info, "Halting player")
        self.player.stop()

    @property
    def is_playing(self) -> bool:
        return self.player.is_playing()

    def play(self) -> None:
        self.log(self.logger.info, "Starting player")
        if self.is_playing:
            self.log(self.logger.info, "Song already playing")
            return
        if not self.current_song:
            self.play_from_queue
        with self.song_error() as current_song:
            self.log(self.logger.info, f"Playing {current_song}")
            self.player.play()
        self.log(self.logger.info, "Play request complete")

    def pause(self) -> None:
        self.log(self.logger.info, "Stopping player")
        if not self.is_playing:
            self.log(self.logger.info, "No song currently playing")
            return
        with self.song_error() as current_song:
            self.log(self.logger.info, f"Pausing {current_song}")
            self.player.pause()
        self.log(self.logger.info, "Pause request complete")

    def set_time(self, seconds: float) -> None:
        with self.song_error():
            self.log(self.logger.info, f"Skipping to {seconds}s")
            self.player.set_time(int(seconds * 1000))
        self.log(self.logger.info, "Skip request complete")

    @property
    def elapsed(self) -> float:
        if self.current_song:
            elapsed = self.player.get_time() / 1000
            return elapsed
        return 0

    @property
    def duration(self) -> float:
        if self.current_song:
            duration = self.current_song.duration
            return duration
        return 0

    @property
    def current_chapter(self) -> Chapter | None:
        self.log(self.logger.debug, "Fetching current chapter.")
        with self.song_error():
            if current_song := self.current_song:
                if not current_song.chapters:
                    return None

                if self.elapsed == 0:
                    current_song.current_chapter = 0
                    return current_song.chapters[0]

                for idx, chapter in enumerate(current_song.chapters):
                    if chapter.time >= self.elapsed:
                        self.current_song.current_chapter = idx - 1
                        this_chapter = self.current_song.chapters[idx - 1]
                        return this_chapter
        return None

    def skip_next(self) -> None:
        if self.current_chapter and (current_song := self.current_song):
            next_idx = current_song.current_chapter + 1
            if next_idx > len(self.current_song.chapters):
                self.log(self.logger.debug, "On last chapter already, skipping")
                self.skip_queue
                return

            next_chapter = current_song.chapters[next_idx]

            self.log(self.logger.info, f"Skipping to {next_chapter.title}")
            self.set_time(next_chapter.time)

    def skip_prev(self) -> None:
        if self.current_chapter and (current_song := self.current_song):
            this_idx = current_song.current_chapter
            prev_idx = max(0, current_song.current_chapter - 1)

            this = current_song.chapters[this_idx]
            prev = current_song.chapters[prev_idx]

            if this.time + 2 > self.elapsed:
                self.log(
                    self.logger.info,
                    f"Close to start of {this.title}, Skipping back to {prev.title}",
                )
                self.set_time(prev.time)
            else:
                self.log(
                    self.logger.info, f"Skipping back to the start of {this.title}"
                )
                self.set_time(this.time)

    def shift_queue(self) -> None:
        self.log(self.logger.debug, "shifting queue")
        if self.current_song:
            self.log(
                self.logger.info,
                f"Song {self.current_song} already in queue, no shifting needed",
            )
        else:
            self.log(self.logger.info, "No current song, checking queue")
            if self.queue.qsize() == 0:
                self.log(self.logger.error, "No song in queue!")
                return
            video = self.queue.get()
            self.set_song(video)

            msg = [f"Updated current video: {video}"]
            if self.queue.qsize() > 0:
                msg.append("Current queue:")
                msg.extend(self.queue.queue)
            self.log(self.logger.info, *msg)
        self.log(self.logger.info, "Shift complete")

    def play_from_queue(self) -> None:
        self.log(self.logger.info, "Playing next song from queue.")
        if self.queue.qsize() == 0:
            self.log(self.logger.error, "No song in queue!")
            self._stop_()
            self.current_song = None
            return
        video = self.queue.get()
        self.set_song(video)

    def skip_queue(self) -> None:
        self.log(self.logger.info, "Skipping to next song in queue.")
        playing = self.is_playing
        if playing:
            self.pause()
        self.play_from_queue()
        if playing and self.current_song:
            self.play()

    def queue_video(self, video: Video) -> Video:
        self.log(self.logger.info, f"Adding {video} to queue.")
        self.queue.put(video)
        self.shift_queue()
        self.log(self.logger.info, f"Video {video} added to queue.")
        return video

    def queue_video_url(self, url: str) -> Video:
        self.log(self.logger.info, f"Adding {url} to queue.")
        video = Video(url)
        return self.queue_video(video)

    @property
    def queue_str(self) -> str:
        return ", ".join((str(video) for video in self._queue_))

    @property
    def queue_list(self) -> list[dict[str, str]]:
        return [video.chapterless_dict for video in self._queue_]

    @property
    def current_song_dict(self) -> dict[str, str]:
        with self.song_error() as current_song:
            return current_song.to_dict
