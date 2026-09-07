"""Minimal, auditable adapter for official Open Images V7 resources."""

from __future__ import annotations

import csv
import hashlib
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

OPEN_IMAGES_ANNOTATION_LICENSE = "https://creativecommons.org/licenses/by/4.0/"
ALLOWED_IMAGE_LICENSES = frozenset(
    {
        "https://creativecommons.org/licenses/by/2.0/",
        "https://creativecommons.org/licenses/by/3.0/",
        "https://creativecommons.org/licenses/by/4.0/",
    }
)
OFFICIAL_URLS = {
    "image_metadata": (
        "https://storage.googleapis.com/openimages/2018_04/validation/"
        "validation-images-with-rotation.csv"
    ),
    "class_descriptions": (
        "https://storage.googleapis.com/openimages/v7/oidv7-class-descriptions.csv"
    ),
    "human_labels": (
        "https://storage.googleapis.com/openimages/v5/"
        "validation-annotations-human-imagelabels-boxable.csv"
    ),
    "bounding_boxes": (
        "https://storage.googleapis.com/openimages/v5/validation-annotations-bbox.csv"
    ),
}
_IMAGE_ID = re.compile(r"^[0-9a-f]{16}$")


class OpenImagesError(RuntimeError):
    """A clear failure while reading or acquiring official dataset material."""


@dataclass(frozen=True, slots=True)
class OpenImagesImage:
    """Attribution-complete official Open Images image metadata."""

    image_id: str
    split: str
    original_url: str
    landing_page: str
    license_url: str
    author: str
    title: str

    @property
    def official_mirror_url(self) -> str:
        return official_image_url(self.image_id, self.split)

    @property
    def attribution_complete(self) -> bool:
        return bool(
            self.image_id
            and self.landing_page
            and self.author
            and self.license_url in ALLOWED_IMAGE_LICENSES
            and self.original_url
        )


@dataclass(frozen=True, slots=True)
class OpenImagesBoundingBox:
    """One selected official normalized bounding-box annotation."""

    image_id: str
    label_name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    is_occluded: bool
    is_truncated: bool


def load_image_metadata(path: Path) -> dict[str, OpenImagesImage]:
    """Parse the official image metadata table and preserve complete rows."""
    rows: dict[str, OpenImagesImage] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            image_id = (row.get("ImageID") or "").strip().lower()
            if not _IMAGE_ID.fullmatch(image_id):
                continue
            rows[image_id] = OpenImagesImage(
                image_id=image_id,
                split=(row.get("Subset") or "").strip().lower(),
                original_url=(row.get("OriginalURL") or "").strip(),
                landing_page=(row.get("OriginalLandingURL") or "").strip(),
                license_url=(row.get("License") or "").strip(),
                author=(row.get("Author") or "").strip(),
                title=(row.get("Title") or "").strip(),
            )
    return rows


def load_class_names(path: Path) -> dict[str, str]:
    """Load the official LabelName to DisplayName mapping."""
    result: dict[str, str] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("LabelName") or "").strip()
            value = (row.get("DisplayName") or "").strip()
            if key and value:
                result[key] = value
    return result


def load_human_labels(
    path: Path,
    class_names: Mapping[str, str],
    *,
    positive_only: bool = True,
) -> dict[str, tuple[str, ...]]:
    """Load deterministic per-image human-verified display labels."""
    labels: dict[str, set[str]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if positive_only and (row.get("Confidence") or "").strip() != "1":
                continue
            image_id = (row.get("ImageID") or "").strip().lower()
            display = class_names.get((row.get("LabelName") or "").strip())
            if _IMAGE_ID.fullmatch(image_id) and display:
                labels.setdefault(image_id, set()).add(display)
    return {key: tuple(sorted(value)) for key, value in sorted(labels.items())}


def load_bounding_boxes(
    path: Path,
    *,
    image_ids: Iterable[str] | None = None,
) -> dict[str, tuple[OpenImagesBoundingBox, ...]]:
    """Load only requested official boxes without retaining the full table."""
    selected = None if image_ids is None else {item.lower() for item in image_ids}
    boxes: dict[str, list[OpenImagesBoundingBox]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            image_id = (row.get("ImageID") or "").strip().lower()
            if selected is not None and image_id not in selected:
                continue
            if not _IMAGE_ID.fullmatch(image_id):
                continue
            try:
                box = OpenImagesBoundingBox(
                    image_id=image_id,
                    label_name=(row.get("LabelName") or "").strip(),
                    x_min=float(row["XMin"]),
                    x_max=float(row["XMax"]),
                    y_min=float(row["YMin"]),
                    y_max=float(row["YMax"]),
                    is_occluded=(row.get("IsOccluded") or "0") == "1",
                    is_truncated=(row.get("IsTruncated") or "0") == "1",
                )
            except (KeyError, ValueError) as exc:
                raise OpenImagesError(
                    f"invalid official bounding-box row: {exc}"
                ) from exc
            boxes.setdefault(image_id, []).append(box)
    return {key: tuple(value) for key, value in sorted(boxes.items())}


def load_instance_masks(
    path: Path,
    *,
    image_ids: Iterable[str] | None = None,
) -> dict[str, tuple[dict[str, str], ...]]:
    """Load selected official mask-index rows while leaving mask files external."""
    selected = None if image_ids is None else {item.lower() for item in image_ids}
    rows: dict[str, list[dict[str, str]]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            image_id = (raw.get("ImageID") or "").strip().lower()
            if selected is not None and image_id not in selected:
                continue
            if _IMAGE_ID.fullmatch(image_id):
                rows.setdefault(image_id, []).append(
                    {key: value for key, value in sorted(raw.items()) if key}
                )
    return {key: tuple(value) for key, value in sorted(rows.items())}


def filter_candidates(
    metadata: Mapping[str, OpenImagesImage],
    labels: Mapping[str, Iterable[str]],
    *,
    required_any: Iterable[str],
    preferred_split: str = "validation",
    limit: int | None = None,
) -> tuple[str, ...]:
    """Return stable, attribution-complete IDs matching resolved class names."""
    wanted = {item.casefold() for item in required_any}
    matches = [
        image_id
        for image_id, item in metadata.items()
        if item.split == preferred_split
        and item.attribution_complete
        and wanted.intersection(label.casefold() for label in labels.get(image_id, ()))
    ]
    ordered = tuple(sorted(matches))
    return ordered if limit is None else ordered[:limit]


def official_image_url(image_id: str, split: str = "validation") -> str:
    """Construct the URL used by the official CVDF subset downloader."""
    checked = image_id.strip().lower()
    if not _IMAGE_ID.fullmatch(checked):
        raise OpenImagesError(f"invalid Open Images image ID: {image_id!r}")
    checked_split = split.strip().lower()
    if checked_split not in {"train", "validation", "test"}:
        raise OpenImagesError(f"unsupported Open Images split: {split!r}")
    return f"https://open-images-dataset.s3.amazonaws.com/{checked_split}/{checked}.jpg"


def sha256_file(path: Path) -> str:
    """Return a lowercase SHA-256 digest for exact persisted bytes."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_cached(
    url: str,
    destination: Path,
    *,
    expected_sha256: str | None = None,
    refresh: bool = False,
    opener: Callable[[str], bytes] | None = None,
) -> Path:
    """Acquire one official resource atomically, cache it, and verify bytes."""
    if not (
        url.startswith("https://storage.googleapis.com/openimages/")
        or url.startswith("https://open-images-dataset.s3.amazonaws.com/")
    ):
        raise OpenImagesError("refusing non-official Open Images URL")
    target = Path(destination)
    if target.is_file() and not refresh:
        _verify_digest(target, expected_sha256)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    fetch = opener or _fetch
    try:
        data = fetch(url)
    except (OSError, urllib.error.URLError) as exc:
        raise OpenImagesError(
            f"could not reach official Open Images host for {url}: {exc}"
        ) from exc
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 and digest != expected_sha256.lower():
        raise OpenImagesError(
            f"SHA-256 mismatch for {url}: expected {expected_sha256}, got {digest}"
        )
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(target)
    return target


def _verify_digest(path: Path, expected: str | None) -> None:
    if expected and sha256_file(path) != expected.lower():
        raise OpenImagesError(f"cached SHA-256 mismatch: {path}")


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "SceneGrammarKit/0.1 Open-Images-subset-client"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()
