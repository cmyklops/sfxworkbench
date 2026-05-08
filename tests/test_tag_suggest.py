"""Tests for report-only tag suggestions."""

from __future__ import annotations

import json
from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.models import RelatedSoundFile, RelatedSoundGroup, UcsCatalog, UcsCatalogProvenance, UcsEntry
from wavwarden.tag_plan import apply_tag_plan, build_tag_plan, review_tag_plan, write_tag_plan
from wavwarden.tag_suggest import (
    build_tag_suggestion_report,
    suggest_from_filename,
    suggest_from_group,
    suggest_from_path,
    suggest_from_ucs_stem,
    write_tag_suggestion_report,
)


def _sample_catalog() -> UcsCatalog:
    return UcsCatalog(
        tool_version="test",
        provenance=UcsCatalogProvenance(
            source_url="https://universalcategorysystem.com/",
            source_path="/tmp/_categorylist.csv",
            source_format="soundminer_csv",
            release_version="v8.2.1",
            imported_at="2026-01-01T00:00:00+00:00",
            attribution="test",
            entry_count=2,
        ),
        entries=[
            UcsEntry(cat_short="AMB", category="AMBIENCE", subcategory="RAIN", cat_id="AMBRain"),
            UcsEntry(cat_short="SFX", category="SOUND EFFECT", subcategory="GUNSHOT", cat_id="SFXGunshot"),
        ],
    )


# ---------------------------------------------------------------------------
# Pure suggestor unit tests
# ---------------------------------------------------------------------------


def test_ucs_stem_emits_category_subcategory_description_take() -> None:
    suggestions = suggest_from_ucs_stem("SFX_GUNSHOT_PISTOL_01")
    by_field = {s.field: s for s in suggestions}

    assert by_field["category"].value == "SFX"
    assert by_field["category"].source == "ucs_stem"
    assert by_field["subcategory"].value == "GUNSHOT"
    # Description is the human-readable form: title-cased subcategory + remainder.
    assert by_field["description"].value == "Gunshot Pistol"
    assert by_field["take_number"].value == "01"
    assert all(s.confidence == 0.75 for s in suggestions)


def test_ucs_stem_uses_catalog_match_when_available() -> None:
    suggestions = suggest_from_ucs_stem("SFX_GUNSHOT_PISTOL_01", catalog=_sample_catalog())
    by_field = {s.field: s for s in suggestions}

    assert by_field["category"].value == "SOUND EFFECT"
    assert by_field["category"].source == "ucs_catalog"
    assert by_field["category"].method == "ucs_catalog_match"
    assert by_field["category"].confidence == 0.95
    assert by_field["subcategory"].value == "GUNSHOT"
    assert "cat_id:SFXGunshot" in by_field["category"].evidence
    assert by_field["take_number"].source == "ucs_stem"


def test_ucs_stem_with_only_subcategory_and_take() -> None:
    suggestions = suggest_from_ucs_stem("AMB_RAIN_03")
    by_field = {s.field: s for s in suggestions}

    assert by_field["subcategory"].value == "RAIN"
    assert by_field["description"].value == "Rain"
    assert by_field["take_number"].value == "03"


def test_non_ucs_stem_returns_no_ucs_suggestions() -> None:
    assert suggest_from_ucs_stem("just_a_name") == []
    assert suggest_from_ucs_stem("Metal Hit 01") == []


def test_filename_strips_take_number_and_expands_abbreviation() -> None:
    suggestions = suggest_from_filename("AMB_FOREST_NIGHT_02")
    by_field: dict[str, list] = {}
    for s in suggestions:
        by_field.setdefault(s.field, []).append(s)

    take = by_field["take_number"][0]
    assert take.value == "02"
    assert take.source == "filename"

    description = by_field["description"][0]
    # AMB expands to Ambience, Forest and Night title-cased.
    assert description.value == "Ambience Forest Night"
    assert description.method == "abbreviation_expansion"
    assert description.confidence == 0.65


def test_filename_without_abbreviation_uses_lower_confidence() -> None:
    suggestions = suggest_from_filename("Metal Hit 04")
    descriptions = [s for s in suggestions if s.field == "description"]
    assert descriptions
    assert descriptions[0].value == "Metal Hit"
    assert descriptions[0].method == "title_case"
    assert descriptions[0].confidence == 0.55


def test_filename_skip_description_still_emits_take() -> None:
    suggestions = suggest_from_filename("Metal Hit 04", skip_description=True)
    fields = {s.field for s in suggestions}
    assert fields == {"take_number"}


def test_filename_take_via_take_prefix_token() -> None:
    suggestions = suggest_from_filename("Pistol_Take_07")
    take_values = [s.value for s in suggestions if s.field == "take_number"]
    assert take_values == ["07"]


def test_path_emits_one_description_per_meaningful_folder(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    file_path = root / "Footsteps" / "Concrete" / "step.wav"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"")

    suggestions = suggest_from_path(file_path, root)
    values = [s.value for s in suggestions]
    assert values == ["Footsteps", "Concrete"]
    assert all(s.field == "description" for s in suggestions)
    assert all(s.source == "path" for s in suggestions)
    assert all(s.confidence == 0.50 for s in suggestions)


def test_path_filters_low_value_wrappers(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    file_path = root / "Sounds" / "Ambience" / "rain.wav"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"")

    suggestions = suggest_from_path(file_path, root)
    values = [s.value for s in suggestions]
    # "Sounds" is filtered as a low-value wrapper.
    assert "Sounds" not in values
    assert "Ambience" in values


def test_path_strips_leading_sort_prefix(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    file_path = root / "01_Ambience" / "forest.wav"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"")

    suggestions = suggest_from_path(file_path, root)
    values = [s.value for s in suggestions]
    assert values == ["Ambience"]


def test_path_outside_root_returns_empty(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    other = tmp_path / "other" / "file.wav"
    other.parent.mkdir()
    other.write_bytes(b"")

    assert suggest_from_path(other, root) == []


def test_group_channel_set_emits_channel_position() -> None:
    group = RelatedSoundGroup(
        group_id=1,
        parent_path="/lib/Ambiences",
        inferred_stem="Forest",
        reason="channel_set",
        confidence="high",
        file_count=2,
        markers=["L", "R"],
    )
    file_l = RelatedSoundFile(path="/lib/Ambiences/Forest L.wav", filename="Forest L.wav", marker="L")
    file_r = RelatedSoundFile(path="/lib/Ambiences/Forest R.wav", filename="Forest R.wav", marker="R")

    left = suggest_from_group(file_l, group)
    right = suggest_from_group(file_r, group)

    left_channel = next(s for s in left if s.field == "channel_position")
    right_channel = next(s for s in right if s.field == "channel_position")
    assert left_channel.value == "Left"
    assert right_channel.value == "Right"
    assert left_channel.confidence == 0.85
    assert any(s.field == "description" and s.value == "Forest" for s in left)


def test_group_numbered_sequence_emits_take_number() -> None:
    group = RelatedSoundGroup(
        group_id=1,
        parent_path="/lib/Impacts",
        inferred_stem="Metal Hit",
        reason="numbered_sequence",
        confidence="high",
        file_count=3,
        markers=["01", "02", "03"],
    )
    member = RelatedSoundFile(path="/lib/Impacts/Metal Hit 02.wav", filename="Metal Hit 02.wav", marker="02")

    suggestions = suggest_from_group(member, group)
    take = next(s for s in suggestions if s.field == "take_number")
    assert take.value == "02"
    assert take.source == "group"
    description = next(s for s in suggestions if s.field == "description")
    assert description.value == "Metal Hit"


# ---------------------------------------------------------------------------
# Orchestrator integration tests
# ---------------------------------------------------------------------------


def _seed_files(tmp_db: Path, files: list[dict]) -> None:
    conn = get_connection(tmp_db)
    for item in files:
        path = Path(item["path"])
        conn.execute(
            """
            INSERT INTO files (
                path, filename, stem, extension, size_bytes, mtime, md5,
                sample_rate, bit_depth, channels, duration_s, scanned_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(path),
                path.name,
                path.stem,
                path.suffix.lower(),
                item.get("size", 100),
                0.0,
                item.get("md5"),
                item.get("sample_rate", 48000),
                item.get("bit_depth", 24),
                item.get("channels", 2),
                item.get("duration_s", 1.0),
                "2026",
            ),
        )
    conn.commit()
    conn.close()


def test_report_combines_ucs_path_group_evidence(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Impacts" / "Metal"
    folder.mkdir(parents=True)
    _seed_files(
        tmp_db,
        [
            {"path": folder / "SFX_HIT_01.wav", "md5": "A"},
            {"path": folder / "SFX_HIT_02.wav", "md5": "B"},
            {"path": folder / "SFX_HIT_03.wav", "md5": "C"},
        ],
    )

    report = build_tag_suggestion_report(root, tmp_db)

    assert report.summary.files_considered == 3
    assert report.summary.files_with_suggestions == 3
    # Each file gets: ucs(category, subcategory, description, take) +
    # group(description, take_number) + path(Impacts, Metal). No filename
    # description (UCS already covered it). 8 suggestions per file.
    sources_used = set(report.summary.by_source.keys())
    assert {"ucs_stem", "group", "path"}.issubset(sources_used)
    fields = set(report.summary.by_field.keys())
    assert {"category", "subcategory", "description", "take_number"}.issubset(fields)


def test_report_can_use_explicit_ucs_catalog(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Ambience"
    folder.mkdir(parents=True)
    _seed_files(tmp_db, [{"path": folder / "AMB_RAIN_01.wav", "md5": "A"}])

    catalog_path = tmp_path / "ucs_catalog.json"
    catalog_path.write_text(json.dumps(_sample_catalog().model_dump()), encoding="utf-8")

    report = build_tag_suggestion_report(root, tmp_db, ucs_catalog_path=catalog_path)

    assert report.ucs_catalog_path == str(catalog_path.resolve())
    assert report.ucs_catalog_release_version == "v8.2.1"
    assert report.summary.by_source["ucs_catalog"] == 3
    suggestion = next(s for s in report.entries[0].suggestions if s.field == "category")
    assert suggestion.value == "AMBIENCE"
    assert suggestion.confidence == 0.95


def test_report_min_confidence_filters_low_confidence(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "MyFolder"
    folder.mkdir(parents=True)
    _seed_files(tmp_db, [{"path": folder / "Just A Name.wav", "md5": "A"}])

    report = build_tag_suggestion_report(root, tmp_db, min_confidence=0.6)

    # Path (0.50) and filename description (0.55) get filtered out.
    for entry in report.entries:
        assert all(s.confidence >= 0.6 for s in entry.suggestions)


def test_report_limit_truncates_entries(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Lib"
    folder.mkdir(parents=True)
    _seed_files(
        tmp_db,
        [
            {"path": folder / "Alpha.wav", "md5": "A"},
            {"path": folder / "Beta.wav", "md5": "B"},
            {"path": folder / "Gamma.wav", "md5": "C"},
        ],
    )

    limited = build_tag_suggestion_report(root, tmp_db, limit=1)
    unlimited = build_tag_suggestion_report(root, tmp_db, limit=0)

    assert limited.summary.files_with_suggestions == 3
    assert len(limited.entries) == 1
    assert len(unlimited.entries) == 3


def test_report_skips_files_outside_root(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()
    _seed_files(
        tmp_db,
        [
            {"path": root / "AMB_FOREST_01.wav", "md5": "A"},
            {"path": other / "AMB_DESERT_01.wav", "md5": "B"},
        ],
    )

    report = build_tag_suggestion_report(root, tmp_db)

    paths = [entry.path for entry in report.entries]
    assert any(p.endswith("AMB_FOREST_01.wav") for p in paths)
    assert not any(p.endswith("AMB_DESERT_01.wav") for p in paths)


def test_report_validates_min_confidence_range(tmp_path: Path, tmp_db: Path) -> None:
    import pytest

    root = tmp_path / "library"
    root.mkdir()

    with pytest.raises(ValueError):
        build_tag_suggestion_report(root, tmp_db, min_confidence=-0.1)
    with pytest.raises(ValueError):
        build_tag_suggestion_report(root, tmp_db, min_confidence=1.5)
    with pytest.raises(ValueError):
        build_tag_suggestion_report(root, tmp_db, limit=-1)


def test_write_tag_suggestion_report_round_trip(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Impacts"
    folder.mkdir(parents=True)
    _seed_files(tmp_db, [{"path": folder / "SFX_HIT_01.wav", "md5": "A"}])

    report = build_tag_suggestion_report(root, tmp_db)
    out = tmp_path / "reports" / "tags.json"
    write_tag_suggestion_report(report, out, quiet=True)

    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert payload["tool"] == "wavwarden"
    assert payload["root"] == str(root.resolve())
    assert payload["entries"][0]["path"].endswith("SFX_HIT_01.wav")
    assert payload["summary"]["files_with_suggestions"] == 1


def test_tag_plan_review_and_db_apply(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Impacts"
    folder.mkdir(parents=True)
    audio = folder / "SFX_HIT_01.wav"
    audio.write_bytes(b"not really audio")
    _seed_files(tmp_db, [{"path": audio, "md5": "A", "size": len(audio.read_bytes())}])

    plan = build_tag_plan(root, db_path=tmp_db, min_confidence=0.7)

    assert plan.target == "db"
    assert plan.summary.candidate_entries > 0
    assert plan.summary.approved_entries == 0
    assert all(entry.review_status == "pending" for entry in plan.entries)
    assert any(entry.field == "category" and entry.proposed_value == "SFX" for entry in plan.entries)

    plan_path = tmp_path / "tag_plan.json"
    write_tag_plan(plan, plan_path, quiet=True)
    review = review_tag_plan(plan_path, approve_all=True, quiet=True)

    assert review.total_entries == plan.summary.candidate_entries
    assert review.approved_entries == plan.summary.candidate_entries

    dry_run = apply_tag_plan(plan_path, db_path=tmp_db, require_reviewed=True, quiet=True)
    assert dry_run.dry_run is True
    assert dry_run.applied == plan.summary.add_entries

    log_path = tmp_path / "tag_apply_log.json"
    applied = apply_tag_plan(
        plan_path,
        db_path=tmp_db,
        dry_run=False,
        require_reviewed=True,
        log_path=log_path,
        quiet=True,
    )

    assert applied.applied == plan.summary.add_entries
    assert applied.errors == []
    assert log_path.exists()
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT field, value, source FROM accepted_tags ORDER BY field, value").fetchall()
    apply_logs = conn.execute("SELECT COUNT(*) FROM tag_apply_log").fetchone()[0]
    conn.close()
    assert ("category", "SFX", "ucs_stem") in [(row["field"], row["value"], row["source"]) for row in rows]
    assert apply_logs == 1

    second = apply_tag_plan(
        plan_path,
        db_path=tmp_db,
        dry_run=False,
        require_reviewed=True,
        log_path=tmp_path / "second_tag_apply_log.json",
        quiet=True,
    )
    assert second.applied == 0
    assert second.skipped == plan.summary.candidate_entries


def test_summary_confidence_buckets_are_sorted(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Impacts"
    folder.mkdir(parents=True)
    _seed_files(
        tmp_db,
        [
            {"path": folder / "SFX_HIT_01.wav", "md5": "A"},
            {"path": folder / "SFX_HIT_02.wav", "md5": "B"},
        ],
    )

    report = build_tag_suggestion_report(root, tmp_db)
    # Buckets must be a stable sorted dict so JSON output is deterministic.
    keys = list(report.summary.by_confidence_bucket.keys())
    assert keys == sorted(keys)
