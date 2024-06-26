import os
import queue
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from logging import Logger
from typing import Any, Generator, Optional

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


class Video:
    def __init__(self, url: str) -> None:
        self.url = url
        self.title = "Unknown"
        self.duration = 0
        self.thumbnail = "Unknown"
        self.audio_url = "Unknown"
        self.chapters = []

        self.get_info()
    
    def get_info(self) -> None:
        self.chapters = []
        with yt_dlp.YoutubeDL({}) as ydl:
            if info := ydl.extract_info(self.url, download=False):
                self.title = info["title"]
                self.duration = info["duration"]
                self.thumbnail = info["thumbnail"]

                self.audio_url = self.get_audio(info)
                self.chapters = self.get_chapters(info)
    
    def get_audio(self, info: dict[str, str]) -> str:
        if audio_formats := [formats for formats in info["formats"] if formats.get("acodec") == "opus"]:
            best_audio = max(audio_formats, key=lambda x: x["abr"])
            return best_audio["url"]
        else:
            print("No audio streams found.")
    
    def get_chapters(self, info: dict[str, str]) -> list[Chapter]:
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

        self.vlc_instance = vlc.Instance("--no-xlib")
        self.player = self.vlc_instance.media_player_new()
        self._previous_volume_ = self.player.audio_get_volume()
        self.set_volume(100)

        self.queue: queue.Queue[Video] = queue.Queue()
        self.current_song: Optional[Video] = None

        notifier.register_callback(self.get_current_song_update)
        notifier.register_callback(self.get_queue_update)

    @property
    def _queue_(self) -> list[Video]:
        return self.queue.queue

    @property
    def _all_(self) -> list[Video]:
        songs = self._queue_
        if self.current_song:
            songs.insert(0, self.current_song)
        return songs

    def get_current_song_update(self) -> Updates:
        self.logger.getChild("song_update").debug(self.current_song)
        info = {
            "playing": self.is_playing,
            "elapsed": self.elapsed,
            "duration": self.duration,
            "current": None,
            "chapters": None,
            "current_chapter": None,
        }
        if self.current_song:
            info["current"] = self.current_song.to_dict  # type:ignore [assignment]
            info["chapters"] = self.current_song.chapters != []
            if chapter := self.current_chapter:
                info["current_chapter"] = chapter.to_dict  # type:ignore [assignment]
        return info

    def get_queue_update(self) -> Updates:
        queue = self.show_queue
        self.logger.getChild("queue_update").debug(queue)
        return {"queue": queue}

    @contextmanager
    def song_error(self) -> Generator[Video, None, None]:
        try:
            if not self.current_song:
                self.shift_queue
            if self.current_song:
                yield self.current_song
            else:
                raise BufferError("No song currently exists to play!")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
        finally:
            pass

    def _load_(self, video: Video) -> None:
        self.logger.info(f"Loading {video} into memory")
        self.logger.info(video.audio_url)
        media = self.vlc_instance.media_new(video.audio_url)
        self.player.set_media(media)
        self.logger.info(f"Loaded {video} into player")

    def set_song(self, video: Video) -> None:
        self._load_(video)
        self.current_song = video

    def set_song_url(self, url: str) -> None:
        self.set_song(Video(url))
    
    def set_volume(self, volume: int) -> None:
        self.player.audio_set_volume(max(0, min(100, volume)))

    @property
    def _stop_(self) -> None:
        self.logger.info("Halting player")
        self.player.stop()

    @property
    def is_playing(self) -> bool:
        return self.player.is_playing()

    @property
    def play(self) -> None:
        self.logger.info("Starting player")
        if self.is_playing:
            self.logger.info("Song already playing")
            return
        if not self.current_song:
            self.play_from_queue
        with self.song_error() as current_song:
            self.logger.info(f"Playing {current_song}")
            self.player.play()
        self.logger.info("Play request complete")

    @property
    def pause(self) -> None:
        self.logger.info("Stopping player")
        if not self.is_playing:
            self.logger.info("No song currently playing")
            return
        with self.song_error() as current_song:
            self.logger.info(f"Pausing {current_song}")
            self.player.pause()
        self.logger.info("Pause request complete")

    def set_time(self, seconds: float) -> None:
        with self.song_error():
            self.logger.info(f"Skipping to {seconds}s")
            self.player.set_time(seconds * 1000)
        self.logger.info("Skip request complete")

    @property
    def elapsed(self) -> float:
        if self.current_song:
            elapsed = self.player.get_time() / 1000
            self.logger.info(f"Currently at {elapsed}s")
            return elapsed
        return 0

    @property
    def duration(self) -> float:
        if self.current_song:
            duration = self.current_song.duration
            self.logger.info(f"Current song is {duration}s long")
            return duration
        return 0

    @property
    def current_chapter(self) -> Chapter | None:
        self.logger.info("Fetching current chapter.")
        with self.song_error() as current_song:
            current_time = self.elapsed
            chapters = current_song.chapters
            if not chapters:
                self.logger.warn("Current song has no chapters.")
                return None

            previous_chapter = None
            for chapter in chapters:
                if chapter.time > current_time:
                    return previous_chapter
                previous_chapter = chapter
        return None

    @property
    def skip_next(self) -> None:
        with self.song_error() as current_song:
            current_time = self.elapsed
            chapters = current_song.chapters
            if not chapters:
                self.logger.warn("Current song has no chapters.")
                return
        
            self.logger.info(f"Skipping from {current_time} to next chapter")

            for chapter in chapters:
                self.logger.debug
                if chapter.time > current_time:
                    self.set_time(chapter.time)
                    return
            self.skip_queue

    @property
    def skip_prev(self) -> None:
        self.logger.info("Skipping to previous chapter.")
        with self.song_error() as current_song:
            current_time = self.elapsed * 1000
            chapters = current_song.chapters
            if not chapters:
                self.logger.warn("Current song has no chapters.")
                return

            for chapter in chapters[::-1]:
                # if we've just skipped back, skip to the previous
                if chapter.time + 2 < current_time:
                    self.set_time(chapter.time)
                    break

    @property
    def shift_queue(self) -> None:
        self.logger.info("shifting queue")
        if self.current_song:
            self.logger.info(
                f"Song {self.current_song} already in queue, no shifting needed"
            )
        else:
            self.logger.info("No current song, checking queue")
            if self.queue.qsize() == 0:
                self.logger.error("No song in queue!")
                return
            video = self.queue.get()
            self.set_song(video)

            msg = f"Updated current video: {video}"
            if self.queue.qsize() > 0:
                msg += f"; queue: {self.list_queue}"
            self.logger.info(msg)
        self.logger.info("Shift complete")

    @property
    def play_from_queue(self) -> None:
        self.logger.info("Playing next song from queue.")
        video = self.queue.get()
        self.set_song(video)

    @property
    def skip_queue(self) -> None:
        self.logger.info("Skipping to next song in queue.")
        playing = self.is_playing
        if playing:
            self.pause
        self._stop_
        self.play_from_queue
        if playing:
            self.play

    def queue_video(self, video: Video) -> Video:
        self.logger.info(f"Adding {video} to queue.")
        self.queue.put(video)
        self.shift_queue
        self.logger.info(f"Video {video} added to queue.")
        return video

    def queue_video_url(self, url: str) -> Video:
        self.logger.info(f"Adding {url} to queue.")
        video = Video(url)
        return self.queue_video(video)

    @property
    def list_queue(self) -> str:
        return ", ".join((str(video) for video in self._queue_))

    @property
    def show_queue(self) -> list[dict[str, str]]:
        return [video.chapterless_dict for video in self._queue_]

    @property
    def show_current(self) -> dict[str, str]:
        with self.song_error() as current_song:
            return current_song.to_dict
