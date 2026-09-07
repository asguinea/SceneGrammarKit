from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scene_grammar_kit.real_cases.open_images import (
    OpenImagesError,
    download_cached,
    filter_candidates,
    load_bounding_boxes,
    load_class_names,
    load_human_labels,
    load_image_metadata,
    official_image_url,
)


def test_official_metadata_parsing_and_attribution(tmp_path: Path) -> None:
    path = tmp_path / "images.csv"
    path.write_text(
        "ImageID,Subset,OriginalURL,OriginalLandingURL,License,"
        "AuthorProfileURL,Author,Title,OriginalSize,OriginalMD5,"
        "Thumbnail300KURL,Rotation\n"
        "0123456789abcdef,validation,https://example.invalid/original.jpg,"
        "https://example.invalid/landing,"
        "https://creativecommons.org/licenses/by/2.0/,,Ada,Facade,,,,\n",
        encoding="utf-8",
    )
    item = load_image_metadata(path)["0123456789abcdef"]
    assert item.author == "Ada"
    assert item.title == "Facade"
    assert item.attribution_complete
    assert item.official_mirror_url.endswith("/validation/0123456789abcdef.jpg")


def test_class_map_and_positive_human_labels(tmp_path: Path) -> None:
    classes = tmp_path / "classes.csv"
    labels = tmp_path / "labels.csv"
    classes.write_text(
        "LabelName,DisplayName\n/m/building,Building\n/m/car,Car\n",
        encoding="utf-8",
    )
    labels.write_text(
        "ImageID,Source,LabelName,Confidence\n"
        "0123456789abcdef,verification,/m/car,1\n"
        "0123456789abcdef,verification,/m/building,1\n"
        "0123456789abcdef,verification,/m/ignored,0\n",
        encoding="utf-8",
    )
    result = load_human_labels(labels, load_class_names(classes))
    assert result == {"0123456789abcdef": ("Building", "Car")}


def test_selected_bounding_boxes_are_parsed_without_full_dataset(
    tmp_path: Path,
) -> None:
    boxes = tmp_path / "boxes.csv"
    boxes.write_text(
        "ImageID,Source,LabelName,Confidence,XMin,XMax,YMin,YMax,"
        "IsOccluded,IsTruncated,IsGroupOf,IsDepiction,IsInside\n"
        "0123456789abcdef,xclick,/m/car,1,0.1,0.2,0.3,0.4,1,0,0,0,0\n"
        "0000000000000000,xclick,/m/car,1,0,1,0,1,0,0,0,0,0\n",
        encoding="utf-8",
    )
    result = load_bounding_boxes(
        boxes,
        image_ids=("0123456789abcdef",),
    )
    assert tuple(result) == ("0123456789abcdef",)
    assert result["0123456789abcdef"][0].is_occluded
    assert result["0123456789abcdef"][0].x_min == 0.1


def test_candidate_filter_rejects_incomplete_or_disallowed_rights(
    tmp_path: Path,
) -> None:
    path = tmp_path / "images.csv"
    path.write_text(
        "ImageID,Subset,OriginalURL,OriginalLandingURL,License,Author,Title\n"
        "0000000000000001,validation,https://x/a.jpg,https://x/a,"
        "https://creativecommons.org/licenses/by/2.0/,A,A\n"
        "0000000000000002,validation,https://x/b.jpg,https://x/b,"
        "https://creativecommons.org/licenses/by-nd/2.0/,B,B\n"
        "0000000000000003,validation,https://x/c.jpg,https://x/c,"
        "https://creativecommons.org/licenses/by/2.0/,,C\n",
        encoding="utf-8",
    )
    metadata = load_image_metadata(path)
    matches = filter_candidates(
        metadata,
        {key: ("Building",) for key in metadata},
        required_any=("Building", "Road"),
    )
    assert matches == ("0000000000000001",)


def test_cache_download_and_sha_validation(tmp_path: Path) -> None:
    data = b"official fixture bytes"
    digest = hashlib.sha256(data).hexdigest()
    calls: list[str] = []

    def opener(url: str) -> bytes:
        calls.append(url)
        return data

    target = tmp_path / "cache" / "fixture.csv"
    url = "https://storage.googleapis.com/openimages/v7/fixture.csv"
    assert download_cached(url, target, expected_sha256=digest, opener=opener) == target
    assert download_cached(url, target, expected_sha256=digest, opener=opener) == target
    assert calls == [url]
    assert target.read_bytes() == data


def test_cache_rejects_bad_digest_and_nonofficial_url(tmp_path: Path) -> None:
    with pytest.raises(OpenImagesError, match="SHA-256 mismatch"):
        download_cached(
            "https://storage.googleapis.com/openimages/v7/fixture.csv",
            tmp_path / "fixture.csv",
            expected_sha256="0" * 64,
            opener=lambda _: b"wrong",
        )
    with pytest.raises(OpenImagesError, match="non-official"):
        download_cached(
            "https://example.invalid/fixture.csv",
            tmp_path / "fixture.csv",
            opener=lambda _: b"unused",
        )


@pytest.mark.parametrize("value", ("bad", "../escape", "G" * 16))
def test_official_image_url_rejects_unsafe_ids(value: str) -> None:
    with pytest.raises(OpenImagesError, match="invalid"):
        official_image_url(value)
