from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def safe_relative_path(value: str) -> str:
    if not value or "\\" in value:
        raise ValueError("Paths must be non-empty POSIX relative paths.")
    posix = PurePosixPath(value)
    if posix.is_absolute() or PureWindowsPath(value).is_absolute():
        raise ValueError("Absolute paths are not allowed in a job manifest.")
    if any(part in ("", ".", "..") for part in posix.parts):
        raise ValueError("Path traversal is not allowed.")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobInput(StrictModel):
    source_video: str | None = None
    base_video: str | None = None
    edl: str | None = None
    timeline: str | None = None
    asset_manifest: str | None = None

    @field_validator("source_video", "base_video", "edl", "timeline", "asset_manifest")
    @classmethod
    def validate_paths(cls, value: str | None) -> str | None:
        return safe_relative_path(value) if value is not None else None

    @model_validator(mode="after")
    def validate_input_choice(self) -> "JobInput":
        if bool(self.source_video) == bool(self.base_video):
            raise ValueError("Specify exactly one of source_video or base_video.")
        if self.edl and not self.source_video:
            raise ValueError("edl can only be used with source_video.")
        return self


class OutputSettings(StrictModel):
    width: int = Field(default=1080, ge=360, le=2160)
    height: int = Field(default=1920, ge=640, le=3840)
    fps: int = Field(default=30, ge=15, le=60)
    video_codec: Literal["h264"] = "h264"
    pixel_format: Literal["yuv420p"] = "yuv420p"
    audio_codec: Literal["aac"] = "aac"


class RenderSettings(StrictModel):
    crf: int = Field(default=18, ge=0, le=51)
    preset: Literal["ultrafast", "fast", "medium", "slow"] = "medium"
    concurrency: int = Field(default=2, ge=1, le=8)


class JobManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    job_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    title: str = Field(default="Untitled render", max_length=200)
    input: JobInput
    output: OutputSettings = Field(default_factory=OutputSettings)
    render: RenderSettings = Field(default_factory=RenderSettings)


class EDLClip(StrictModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    keep_audio: bool = True

    @model_validator(mode="after")
    def validate_range(self) -> "EDLClip":
        if self.end <= self.start:
            raise ValueError("EDL end must be greater than start.")
        return self


class EDLDocument(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    segments: list[EDLClip] = Field(min_length=1)


class DuckingRange(StrictModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    volume: float = Field(default=0.3, ge=0, le=1)

    @model_validator(mode="after")
    def validate_range(self) -> "DuckingRange":
        if self.end <= self.start:
            raise ValueError("Ducking range end must be greater than start.")
        return self


class RemoteAssetSpec(StrictModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    kind: Literal["music", "sfx", "meme", "broll"]
    url: str = Field(min_length=8, max_length=4096)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    required: bool = True
    max_bytes: int | None = Field(default=None, ge=1, le=536870912)
    # Audio placement is in output-timeline seconds. Meme/B-roll placement belongs in timeline.json.
    start: float = Field(default=0, ge=0)
    end: float | None = Field(default=None, gt=0)
    volume: float | None = Field(default=None, ge=0, le=2)
    fade_in: float = Field(default=0, ge=0, le=30)
    fade_out: float = Field(default=0, ge=0, le=30)
    loop: bool = False
    ducking_ranges: list[DuckingRange] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def validate_direct_url_shape(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ("https", "http") or not parsed.hostname:
            raise ValueError("Asset URL must be an absolute HTTP(S) URL.")
        if parsed.username or parsed.password:
            raise ValueError("Credentials must not be embedded in asset URLs.")
        if parsed.fragment:
            raise ValueError("Asset URLs must not contain fragments.")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("Asset URL has an invalid port.") from exc
        return value

    @model_validator(mode="after")
    def validate_asset_options(self) -> "RemoteAssetSpec":
        if self.end is not None and self.end <= self.start:
            raise ValueError("Asset end must be greater than start.")
        if self.kind not in ("music", "sfx"):
            if self.volume is not None or self.fade_in or self.fade_out or self.loop or self.ducking_ranges:
                raise ValueError("Audio timing and mix settings are only valid for music/SFX assets.")
        if self.kind != "music" and self.ducking_ranges:
            raise ValueError("Ducking ranges are only valid for music assets.")
        if self.kind == "sfx" and self.loop:
            raise ValueError("SFX assets cannot loop.")
        if self.end is not None and self.fade_in + self.fade_out > self.end - self.start:
            raise ValueError("Audio fade durations cannot exceed the scheduled track duration.")
        return self


class AssetManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    assets: list[RemoteAssetSpec] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "AssetManifest":
        ids = [asset.id for asset in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("Asset IDs must be unique within asset_manifest.json.")
        return self


class TimelineCue(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    type: Literal["caption", "bubble", "zoom", "flash", "meme", "broll"]
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str | None = Field(default=None, max_length=500)
    asset_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    position: Literal["top", "center", "bottom"] = "bottom"
    scale: float = Field(default=1.08, ge=1.0, le=1.3)
    x: float | None = Field(default=None, ge=0, le=100)
    y: float | None = Field(default=None, ge=0, le=100)
    width: float | None = Field(default=None, gt=0, le=100)
    height: float | None = Field(default=None, gt=0, le=100)
    opacity: float = Field(default=1, ge=0, le=1)
    fit: Literal["cover", "contain", "fill"] = "contain"
    style: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_range(self) -> "TimelineCue":
        if self.end <= self.start:
            raise ValueError("Timeline cue end must be greater than start.")
        if self.type in ("caption", "bubble") and not self.text:
            raise ValueError(f"{self.type} cue requires text.")
        if self.type in ("meme", "broll") and not self.asset_id:
            raise ValueError(f"{self.type} cue requires asset_id.")
        return self


class TimelineDocument(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    layers: list[TimelineCue] = Field(default_factory=list)
