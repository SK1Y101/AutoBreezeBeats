import io
import queue
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from logging import Logger
from typing import Any, Generator, Optional

import vlc
import yt_dlp
from pytube import YouTube

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
        self.yt = YouTube(url)

        self.title = self.yt.title
        self.thumbnail = self.yt.thumbnail_url
        self.duration = self.yt.length

        self.stream = self.yt.streams.filter(only_audio=True).first()

        buffer = io.BytesIO()
        self.stream.stream_to_buffer(buffer)
        buffer.seek(0)
        self.stream_data = buffer.read()

    def __str__(self) -> str:
        return f"<< Video: {self.title} at {self.url} >>"

    @cached_property
    def chapters(self) -> list[Chapter]:
        chapters = []
        with yt_dlp.YoutubeDL({}) as ydl:
            if info := ydl.extract_info(self.url, download=False):
                if chapters := info.get("chapters"):
                    for chapter in chapters:
                        title = chapter.get("title")
                        start = chapter.get("start_time")
                        if start is not None and title:
                            chapters.append(Chapter(title=title, time=start))
        return chapters

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


class PlaybackManager(BreezeBaseClass):
    def __init__(self, parent_logger: None | Logger, notifier: Notifier) -> None:
        super().__init__("playback", parent_logger)

        self.player = vlc.MediaPlayer()

        self.queue: queue.Queue[Video] = queue.Queue()
        self.current_song: Optional[Video] = None

        self.is_playing = False

        notifier.register_callback(self.get_progress_update)
        notifier.register_callback(self.get_queue_update)

    @property
    def _queue_(self) -> list[Video]:
        return self.queue.queue

    def get_progress_update(self) -> Updates:
        self.logger.info(f"Request queue update: {self.current_song}")
        if self.is_playing:
            return {"progress": self.elapsed, "duration": self.duration}
        return {}

    def get_queue_update(self) -> Updates:
        queue = self.show_queue
        self.logger.info(f"Request queue update: {queue}")
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
        audio = video.stream_data
        with tempfile.NamedTemporaryFile() as tmp_file:
            tmp_file.write(audio)
            tmp_file.flush()
            media = vlc.Media(tmp_file.name)
            self.player.set_media(media)
        self.logger.info(f"Loaded {video} into player")

    def set_song(self, video: Video) -> None:
        self._load_(video)
        self.current_song = video

    def set_song_url(self, url: str) -> None:
        self.set_song(Video(url))

    @property
    def _stop_(self) -> None:
        self.logger.info("Halting player")
        self.player.stop()

    @property
    def play(self) -> None:
        self.logger.info("Starting player")
        if self.is_playing:
            self.logger.info("No song currently playing")
            return
        if not self.current_song:
            self.play_from_queue
        with self.song_error() as current_song:
            self.logger.info(f"Playing {current_song}")
            self.player.play()
            self.is_playing = True

    @property
    def pause(self) -> None:
        self.logger.info("Stopping player")
        if not self.is_playing:
            self.logger.info("No song currently playing")
            return
        with self.song_error() as current_song:
            self.logger.info(f"Pausing {current_song}")
            self.player.pause()
            self.is_playing = False

    def set_time(self, seconds: float) -> None:
        with self.song_error():
            self.logger.info(f"Skipping to {seconds}s")
            self.player.set_time(seconds * 1000)

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
            duration = self.player.get_length() / 1000
            self.logger.info(f"Current song is {duration}s long")
            return duration
        return 0

    @property
    def skip_next(self) -> None:
        with self.song_error() as current_song:
            current_time = self.elapsed * 1000
            chapters = current_song.chapters
            if not chapters:
                self.logger.warn("Current song has no chapters.")
                return

            for chapter in chapters:
                if chapter.time > current_time:
                    self.set_time(chapter.time)
                    break
            else:
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
        return [
            {k: v for k, v in video.to_dict.items() if k != "chapters"}
            for video in self._queue_
        ]

    @property
    def show_current(self) -> dict[str, str]:
        with self.song_error() as current_song:
            return current_song.to_dict
