import io
import queue
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from logging import Logger, getLogger
from time import sleep
from typing import Optional

import pygame
import vlc
import yt_dlp
from pydantic import BaseModel
from pytube import Youtube

from .common import BreezeBaseClass
from .websockets import Notifier, Updates


class VideoAction(BaseModel):
    url: str


@dataclass
class Chapter:
    title: str
    time: int

    @property
    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "time": self.time}


class Video:
    def __init__(self, url: str) -> None:
        self.url = url
        self.yt = Youtube(url)

        self.title = self.yt.title
        self.thumbnail = self.yt.thumbnail_url
        self.length = self.yt.length

        self.streams = self.yt.streams.filter(only_audio=True).first()
        self.stream_data = self.stream.stream_to_buffer().read

    @property
    def chapters(self) -> list[Chapter]:
        if self.yt.metadata:
            return [
                Chapter(title=chapter.title, time=chapter.start_time)
                for chapter in self.yt.metadata.chapters
            ]
        return []

    @property
    def to_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "thumbnail": self.thumbnail,
            "length": self.length,
            "chapters": [chapter.to_dict for chapter in self.chapters],
        }


class PlaybackManager(BreezeBaseClass):
    def __init__(self, parent_logger: None | Logger, notifier: Notifier) -> None:
        super().__init__("playback", parent_logger)

        self.player = vlc.MediaPlayer()

        self.queue: queue.SimpleQueue[Video] = []
        self.current_song: Optional[Video] = None

        self.is_playing = False
        self.duration = 0

        notifier.register_callback(self.get_progress_update)
        notifier.register_callback(self.get_queue_update)

    def get_progress_update(self) -> Updates:
        if self.is_playing:
            return {"progress": self.elapsed}
        return {}

    def get_queue_update(self) -> Updates:
        return {"queue": self.show_queue}

    @contextmanager
    def song_error(self):
        try:
            if not self.current_song:
                self.shift_queue
            if self.current_song:
                yield
            else:
                raise BufferError("No song currently exists to play!")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
        finally:
            pass

    def _load_(self, video: Video) -> None:
        self.info(f"Loading {video} into memory")
        audio = video.stream_data
        media = vlc.Media(io.BytesIO(audio))
        self.player.set_media(media)

    def set_song(self, video: Video) -> None:
        self._load_(video)
        self.current_song = video

    def set_song_url(self, url: str) -> None:
        self.set_song(Video(url))

    @property
    def _stop_(self) -> None:
        self.debug("Halting player")
        self.player.stop()

    @property
    def play(self) -> None:
        self.debug("Starting player")
        if self.is_playing:
            self.info("No song currently playing")
            return
        if not self.current_song:
            self.play_from_queue
        with self.song_error():
            self.debug(f"Playing {self.current_song}")
            self.player.play()
            self.is_playing = True

    @property
    def pause(self) -> None:
        self.debug("Stopping player")
        if not self.is_playing:
            self.info("No song currently playing")
            return
        with self.song_error():
            self.debug(f"Pausing {self.current_song}")
            self.player.pause()
            self.is_playing = False

    def set_time(self, seconds: float) -> None:
        with self.song_error():
            self.info(f"Skipping to {seconds}s")
            self.player.set_time(seconds * 1000)

    @property
    def elapsed(self) -> float:
        if self.current_song:
            elapsed = self.player.get_time() / 1000
            self.debug(f"Currently at {elapsed}s")
            return elapsed
        return 0

    @property
    def duration(self) -> float:
        if self.current_song:
            duration = self.player.get_length() / 1000
            self.debug(f"Current song is {duration}s long")
            return duration
        return 0

    @property
    def skip_next(self) -> None:
        with self.song_error():
            current_time = self.elapsed * 1000
            chapters = self.current_song.chapters
            if not chapters:
                self.warn("Current song has no chapters.")
                return

            for chapter in chapters:
                if chapter.time > current_time:
                    self.set_time(chapter.time)
                    break
            else:
                self.skip_queue

    @property
    def skip_prev(self) -> None:
        self.info("Skipping to previous chapter.")
        with self.song_error():
            current_time = self.elapsed * 1000
            chapters = self.current_song.chapters
            if not chapters:
                self.warn("Current song has no chapters.")
                return

            previous_chapter = 0
            for chapter in chapters:
                if chapter.time >= current_time:
                    self.set_time(previous_chapter)
                    break
                previous_chapter = chapter.time
            else:
                self.skip_queue

    @property
    def shift_queue(self) -> None:
        if not self.current_song:
            if self.queue.empty:
                self.error("No song in queue!")
                return
            video = self.queue.get()
            self.set_song(video)

    @property
    def play_from_queue(self) -> None:
        self.info("Playing next song from queue.")
        video = self.queue.get()
        self.set_song(video)

    @property
    def skip_queue(self) -> None:
        self.info("Skipping to next song in queue.")
        playing = self.is_playing
        if playing:
            self.pause
        self._stop_
        self.play_from_queue
        if playing:
            self.play

    def queue_video(self, video: Video) -> Video:
        self.info(f"Adding {video} to queue.")
        self.queue.put(video)
        self.shift_queue
        return video

    def queue_video_url(self, url: str) -> Video:
        self.info(f"Adding {url} to queue.")
        video = Video(url)
        return self.queue_video(video)

    @property
    def show_queue(self) -> list[dict[str, str]]:
        return [video.to_dict for video in self.queue]

    @property
    def show_current(self) -> dict[str, str]:
        with self.song_error():
            return self.current_song.to_dict
