"""Tests for report-only tag suggestions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sfxworkbench.db import get_connection
from sfxworkbench.models import (
    RelatedSoundFile,
    RelatedSoundGroup,
    TagSuggestion,
    UcsCatalog,
    UcsCatalogProvenance,
    UcsEntry,
)
from sfxworkbench.tag_plan import apply_tag_plan, build_tag_plan, review_tag_plan, summarize_tag_plan, write_tag_plan
from sfxworkbench.tag_sidecar import build_tag_sidecar_report, import_tag_sidecar, write_tag_sidecar_report
from sfxworkbench.tag_suggest import (
    PriorCatalogIndex,
    SuggestContext,
    build_tag_suggestion_report,
    clean_tag_suggestion_text,
    normalize_and_dedupe,
    run_suggestors,
    suggest_from_filename,
    suggest_from_group,
    suggest_from_path,
    suggest_from_ucs_stem,
    suggest_synonym_keywords,
    suggest_ucs_from_prior_tags,
    write_tag_suggestion_report,
)
from sfxworkbench.ucs_catalog import save_catalog


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

    assert by_field["ucs_category"].value == "SFX"
    assert by_field["ucs_category"].source == "ucs_stem"
    assert by_field["ucs_subcategory"].value == "GUNSHOT"
    # Description is the human-readable form: title-cased ucs_subcategory + remainder.
    assert by_field["description"].value == "Gunshot Pistol"
    assert by_field["take_number"].value == "01"
    assert all(s.confidence == 0.75 for s in suggestions)


def test_ucs_stem_uses_catalog_match_when_available() -> None:
    suggestions = suggest_from_ucs_stem("SFX_GUNSHOT_PISTOL_01", catalog=_sample_catalog())
    by_field = {s.field: s for s in suggestions}

    assert by_field["ucs_category"].value == "SOUND EFFECT"
    assert by_field["ucs_category"].source == "ucs_catalog"
    assert by_field["ucs_category"].method == "ucs_catalog_match"
    assert by_field["ucs_category"].confidence == 0.95
    assert by_field["ucs_subcategory"].value == "GUNSHOT"
    assert "cat_id:SFXGunshot" in by_field["ucs_category"].evidence
    assert by_field["take_number"].source == "ucs_stem"


def test_ucs_stem_with_only_subcategory_and_take() -> None:
    suggestions = suggest_from_ucs_stem("AMB_RAIN_03")
    by_field = {s.field: s for s in suggestions}

    assert by_field["ucs_subcategory"].value == "RAIN"
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


def test_filename_word_splits_lowercase_concatenated_compound() -> None:
    """SFX libraries often ship stems like ``Afghanmeninteriorbusyc3401`` —
    descriptive compound + catalog number with no separators. Without
    word-splitting the entire string becomes a single proposed description,
    which is what surfaced in the metadata-review screenshot. Tokenize and
    suggest should recover real words.
    """
    suggestions = suggest_from_filename("Afghanmeninteriorbusyc3401")
    descriptions = [s for s in suggestions if s.field == "description"]
    assert descriptions, "filename should still produce a description suggestion"
    value = descriptions[0].value.lower()
    # The exact tokenization depends on wordninja's word-frequency list, but
    # the meaningful sub-words must appear and the raw blob must NOT.
    assert "afghan" in value
    assert "interior" in value
    assert "busy" in value
    assert "afghanmeninteriorbusy" not in value


def test_filename_word_splits_drops_catalog_number() -> None:
    """Long trailing catalog numbers should not become tags.

    They are common in vendor filenames, but unlike explicit ``Take_07`` or
    short ``_02`` suffixes they are usually catalog IDs rather than useful
    searchable metadata.
    """
    suggestions = suggest_from_filename("Boxingcrowdcheersandsh2301")
    by_field: dict[str, list] = {}
    for s in suggestions:
        by_field.setdefault(s.field, []).append(s)
    description_value = by_field["description"][0].value.lower()
    assert "boxing" in description_value
    assert "crowd" in description_value
    assert "cheers" in description_value
    assert "2301" not in description_value
    take_values = [s.value for s in by_field.get("take_number", [])]
    assert take_values == []


def test_filename_preserves_meaningful_model_numbers_and_acronyms() -> None:
    suggestions = suggest_from_filename("MKH8040 D100 WW2 Crowd Chatter 1701")
    by_field: dict[str, list] = {}
    for s in suggestions:
        by_field.setdefault(s.field, []).append(s)

    description = by_field["description"][0]
    assert description.value == "MKH8040 D100 WW2 Crowd Chatter"
    assert "1701" not in description.value
    assert "take_number" not in by_field


def test_filename_ignores_ixml_recorder_metadata_assignments() -> None:
    suggestions = suggest_from_filename(
        "sTAKE=48 sSWVER=2.63 sPROJECT= sSCENE=SFX_ "
        "sFILENAME=SFX_T48.WAV sTAPE=130208 sTRK1=Track A sTRK2=Track B sNOTE="
    )

    assert suggestions == []


def test_tag_suggestion_text_cleaner_strips_recorder_assignment_noise() -> None:
    cleaned = clean_tag_suggestion_text(
        "sTAKE=49 sSWVER=2.63 sPROJECT= sSCENE=SFX_ sFILENAME=SFX_T49.WAV sTRK1=Track A sNOTE= room tone"
    )

    assert cleaned == "room tone"


def test_filename_strips_ixml_assignments_but_keeps_terms_after_empty_note() -> None:
    suggestions = suggest_from_filename(
        "sTAKE=48 sSWVER=2.63 sPROJECT= sSCENE=SFX_ "
        "sFILENAME=SFX_T48.WAV sTAPE=130208 sTRK1=Track A sTRK2=Track B "
        "sNOTE= background atmosphere room tone"
    )

    by_field = {suggestion.field: suggestion for suggestion in suggestions}
    assert by_field["description"].value == "Background Atmosphere Room Tone"
    assert all("=" not in suggestion.value for suggestion in suggestions)


def test_assignment_noise_does_not_feed_keywords_or_ucs() -> None:
    prior = [
        TagSuggestion(
            field="description",
            value="sTAKE=49 sFILENAME=SFX_T49.WAV",
            source="filename",
            method="title_case",
            confidence=0.6,
        )
    ]
    catalog = UcsCatalog(
        tool_version="test",
        provenance=UcsCatalogProvenance(
            source_url="https://example/",
            source_path="/tmp/cat.csv",
            source_format="soundminer_csv",
            release_version="v8",
            imported_at="2026-01-01T00:00:00+00:00",
            attribution="test",
            entry_count=1,
        ),
        entries=[UcsEntry(cat_short="SFX", category="SOUND EFFECT", subcategory="TAKE", cat_id="SFXTake")],
    )

    assert suggest_synonym_keywords(prior) == []
    assert suggest_ucs_from_prior_tags(prior, catalog) == []


def test_filename_drops_timestamp_tokens_from_description() -> None:
    suggestions = suggest_from_filename("then off 0:04, 1:19, 2:47")
    by_field: dict[str, list] = {}
    for s in suggestions:
        by_field.setdefault(s.field, []).append(s)

    assert by_field["description"][0].value == "Then Off"
    assert "take_number" not in by_field


def test_filename_drops_date_sequences_from_description() -> None:
    suggestions = suggest_from_filename("Rain 2026-05-13 05/14/26 20260515 Jan 5 2024 6 Jun 2025")
    by_field: dict[str, list] = {}
    for s in suggestions:
        by_field.setdefault(s.field, []).append(s)

    assert by_field["description"][0].value == "Rain"
    assert "take_number" not in by_field


def test_filename_drops_audio_format_tokens_from_description() -> None:
    suggestions = suggest_from_filename("Metal Hit 16bit 24-bit 32 bit 44100kHz 44.1kHz 48kHz 96 kHz 44k1")
    by_field: dict[str, list] = {}
    for s in suggestions:
        by_field.setdefault(s.field, []).append(s)

    assert by_field["description"][0].value == "Metal Hit"
    assert "take_number" not in by_field


def test_filename_word_split_preserves_existing_structure() -> None:
    """Already-separated stems must pass through unchanged. Word-splitting
    only kicks in for lowercase alphabetic tokens of 8+ chars.
    """
    suggestions = suggest_from_filename("AMB_RAIN_01")
    description = next(s for s in suggestions if s.field == "description")
    assert description.value == "Ambience Rain"


def test_synonym_keywords_from_description_suggestions() -> None:
    base = suggest_from_filename("Car Crash 01")

    suggestions = suggest_synonym_keywords(base)

    assert {s.field for s in suggestions} == {"keyword"}
    assert {s.value for s in suggestions} == {"vehicle impact", "auto collision", "wreck", "impact", "collision"}
    assert all(s.source == "synonym" for s in suggestions)
    assert all(s.method == "controlled_synonym_map" for s in suggestions)
    assert any("matched:car crash" in s.evidence for s in suggestions)


def test_synonym_keywords_match_plural_and_verb_forms() -> None:
    base = suggest_from_filename("Cars Crashing 01")

    suggestions = suggest_synonym_keywords(base)

    values = {s.value for s in suggestions}
    assert {"vehicle impact", "auto collision", "wreck", "impact", "collision"} <= values


def test_synonym_keywords_include_common_sfx_terms() -> None:
    base = suggest_from_filename("Door Slam 01")

    suggestions = suggest_synonym_keywords(base)

    values = {s.value for s in suggestions}
    assert {"open close", "hinge", "impact", "bang", "hit"} <= values


def test_synonym_keywords_cover_common_library_terms() -> None:
    base = suggest_from_filename("Ufo Servo Flutter Tractor Safe Vault Punch Heartbeat")

    suggestions = suggest_synonym_keywords(base)

    values = {s.value for s in suggestions}
    assert {"alien", "robotic", "flapping", "farm vehicle", "lock", "impact", "pulse"} <= values


def test_synonym_keywords_can_limit_count_and_depth() -> None:
    base = suggest_from_filename("Car Crash 01")

    limited = suggest_synonym_keywords(base, synonym_limit=3)
    shallow = suggest_synonym_keywords(base, synonym_depth=1)
    shallow_limited = suggest_synonym_keywords(base, synonym_limit=1, synonym_depth=1)

    assert [s.value for s in limited] == ["vehicle impact", "auto collision", "wreck"]
    assert [s.value for s in shallow] == ["vehicle impact", "impact"]
    assert [s.value for s in shallow_limited] == ["vehicle impact"]


def test_synonym_keywords_collapse_generic_ambience_terms() -> None:
    base = suggest_from_filename("Background Atmosphere Room Tone 01")

    suggestions = suggest_synonym_keywords(base)
    values = {s.value for s in suggestions}

    assert not (values & {"ambience", "background", "atmosphere", "room tone"})
    assert values == {"interior"}


def test_ucs_catalog_can_use_prior_description_suggestions() -> None:
    prior = suggest_from_filename("Rain Light 01")

    suggestions = suggest_ucs_from_prior_tags(prior, _sample_catalog())
    by_field = {suggestion.field: suggestion for suggestion in suggestions}

    assert by_field["ucs_category"].value == "AMBIENCE"
    assert by_field["ucs_subcategory"].value == "RAIN"
    assert by_field["ucs_category"].source == "ucs_catalog"
    assert by_field["ucs_category"].method == "prior_tag_catalog_match"
    assert by_field["ucs_category"].confidence == 0.82
    assert "matched:subcategory:RAIN" in by_field["ucs_category"].evidence


def test_ucs_still_emits_for_room_tone_ambience_context() -> None:
    catalog = UcsCatalog(
        tool_version="test",
        provenance=UcsCatalogProvenance(
            source_url="https://example/",
            source_path="/tmp/cat.csv",
            source_format="soundminer_csv",
            release_version="v8",
            imported_at="2026-01-01T00:00:00+00:00",
            attribution="test",
            entry_count=1,
        ),
        entries=[
            UcsEntry(
                cat_short="AMB",
                category="AMBIENCE",
                subcategory="ROOM TONE",
                cat_id="AMBRoomtone",
                synonyms=["background atmosphere", "room tone"],
            )
        ],
    )
    prior = suggest_from_filename("Background Atmosphere Room Tone 01")

    suggestions = suggest_ucs_from_prior_tags(prior, catalog)
    by_field = {suggestion.field: suggestion for suggestion in suggestions}

    assert by_field["ucs_category"].value == "AMBIENCE"
    assert by_field["ucs_subcategory"].value == "ROOM TONE"


def test_ucs_prior_tag_suggestions_surface_ambiguous_catalog_matches_for_review() -> None:
    sample = _sample_catalog()
    catalog = sample.model_copy(
        update={
            "entries": [
                *sample.entries,
                UcsEntry(cat_short="WTR", category="WATER", subcategory="RAIN", cat_id="WTRRain"),
            ]
        }
    )
    prior = suggest_from_filename("Rain Light 01")

    suggestions = suggest_ucs_from_prior_tags(prior, catalog)
    by_field = {suggestion.field: suggestion for suggestion in suggestions}

    assert by_field["ucs_category"].value == "AMBIENCE"
    assert by_field["ucs_subcategory"].value == "RAIN"
    assert by_field["ucs_category"].confidence == 0.62
    assert any("ambiguous_alternative:WTR_RAIN:WTRRain" in item for item in by_field["ucs_category"].evidence)


def test_ucs_prior_catalog_index_matches_direct_catalog_scan() -> None:
    catalog = _sample_catalog()
    prior = suggest_from_filename("Rain Light 01")

    direct = suggest_ucs_from_prior_tags(prior, catalog)
    indexed = suggest_ucs_from_prior_tags(prior, catalog, catalog_index=PriorCatalogIndex.build(catalog))

    assert [suggestion.model_dump() for suggestion in indexed] == [suggestion.model_dump() for suggestion in direct]


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


def test_group_ignores_ixml_recorder_metadata_inferred_stem() -> None:
    group = RelatedSoundGroup(
        group_id=1,
        parent_path="/lib/Recorder",
        inferred_stem=(
            "sTAKE=48 sSWVER=2.63 sPROJECT= sSCENE=SFX_ "
            "sFILENAME=SFX_T48.WAV sTAPE=130208 sTRK1=Track A sTRK2=Track B sNOTE="
        ),
        reason="numbered_sequence",
        confidence="high",
        file_count=3,
        markers=["1", "2", "3"],
    )
    member = RelatedSoundFile(path="/lib/Recorder/SFX_T48.wav", filename="SFX_T48.wav", marker="1")

    assert suggest_from_group(member, group) == []


# ---------------------------------------------------------------------------
# Normalization + dedup
# ---------------------------------------------------------------------------


def test_filename_drops_punctuation_from_descriptions() -> None:
    """``Rain(loud)`` should tokenize as two words, not stay glued by parens."""
    suggestions = suggest_from_filename("Rain(loud)")
    by_field = {s.field: s for s in suggestions}

    assert by_field["description"].value == "Rain Loud"


def test_normalize_drops_single_letter_tokens() -> None:
    """Stray single-letter tokens (wordninja debris, lone consonants) are not useful tags."""
    suggestion = TagSuggestion(
        field="description",
        value="Busy C Crowd",
        source="filename",
        method="title_case",
        confidence=0.6,
    )

    cleaned = normalize_and_dedupe([suggestion])

    assert len(cleaned) == 1
    assert cleaned[0].value == "Busy Crowd"


def test_normalize_dedupes_same_value_by_source_priority() -> None:
    """Two suggestors emitting ``description=Rain`` collapse to the higher-priority source."""
    filename_suggestion = TagSuggestion(
        field="description",
        value="Rain",
        source="filename",
        method="title_case",
        confidence=0.99,
        evidence=["Rain_01"],
    )
    path_suggestion = TagSuggestion(
        field="description",
        value="Rain",
        source="path",
        method="folder_chain",
        confidence=0.50,
        evidence=["Rain"],
    )

    cleaned = normalize_and_dedupe([filename_suggestion, path_suggestion])

    assert len(cleaned) == 1
    winner = cleaned[0]
    assert winner.value == "Rain"
    assert winner.source == "path"
    assert any("also_from:filename:title_case" in entry for entry in winner.evidence)


def test_normalize_picks_highest_confidence_single_value() -> None:
    """Distinct values on a single-value field: winner takes the row, losers become alternatives."""
    low = TagSuggestion(
        field="description",
        value="Rain",
        source="filename",
        method="title_case",
        confidence=0.55,
    )
    high = TagSuggestion(
        field="description",
        value="Light Rain",
        source="group",
        method="group_inferred_stem",
        confidence=0.75,
    )

    cleaned = normalize_and_dedupe([low, high])

    assert len(cleaned) == 1
    winner = cleaned[0]
    assert winner.value == "Light Rain"
    assert winner.source == "group"
    assert any("alternative:Rain:filename:0.55" in entry for entry in winner.evidence)


def test_normalize_source_priority_beats_confidence_for_single_value_fields() -> None:
    low_path = TagSuggestion(
        field="description",
        value="Folder Rain",
        source="path",
        method="folder_chain",
        confidence=0.50,
    )
    high_filename = TagSuggestion(
        field="description",
        value="Filename Rain",
        source="filename",
        method="title_case",
        confidence=0.99,
    )

    cleaned = normalize_and_dedupe([high_filename, low_path])

    assert len(cleaned) == 1
    assert cleaned[0].value == "Folder Rain"
    assert cleaned[0].source == "path"
    assert any("alternative:Filename Rain:filename:0.99" in entry for entry in cleaned[0].evidence)


def test_normalize_ucs_stem_beats_ucs_catalog_for_conflicting_ucs_fields() -> None:
    stem = TagSuggestion(
        field="ucs_subcategory",
        value="RAIN",
        source="ucs_stem",
        method="ucs_heuristic",
        confidence=0.75,
    )
    catalog = TagSuggestion(
        field="ucs_subcategory",
        value="WIND",
        source="ucs_catalog",
        method="prior_tag_catalog_match",
        confidence=0.95,
    )

    cleaned = normalize_and_dedupe([catalog, stem])

    assert len(cleaned) == 1
    assert cleaned[0].value == "RAIN"
    assert cleaned[0].source == "ucs_stem"
    assert any("alternative:WIND:ucs_catalog:0.95" in entry for entry in cleaned[0].evidence)


def test_normalize_synonym_cannot_win_single_value_conflict() -> None:
    synonym = TagSuggestion(
        field="description",
        value="Robotic",
        source="synonym",
        method="controlled_synonym_map",
        confidence=1.0,
    )
    filename = TagSuggestion(
        field="description",
        value="Servo Movement",
        source="filename",
        method="title_case",
        confidence=0.55,
    )

    cleaned = normalize_and_dedupe([synonym, filename])

    assert len(cleaned) == 1
    assert cleaned[0].value == "Servo Movement"
    assert cleaned[0].source == "filename"
    assert any("alternative:Robotic:synonym:1.00" in entry for entry in cleaned[0].evidence)


def test_normalize_enforces_case_per_field() -> None:
    """UCS UPPER, keyword lower, description Title Case regardless of suggestor output."""
    ucs = TagSuggestion(
        field="ucs_subcategory",
        value="rain",
        source="ucs_catalog",
        method="prior_tag_catalog_match",
        confidence=0.82,
    )
    desc = TagSuggestion(
        field="description",
        value="LIGHT RAIN",
        source="filename",
        method="title_case",
        confidence=0.6,
    )
    keyword = TagSuggestion(
        field="keyword",
        value="HEAVY Downpour",
        source="synonym",
        method="controlled_synonym_map",
        confidence=0.5,
    )

    cleaned = normalize_and_dedupe([ucs, desc, keyword])
    by_field = {s.field: s for s in cleaned}

    assert by_field["ucs_subcategory"].value == "RAIN"
    assert by_field["description"].value == "Light Rain"
    assert by_field["keyword"].value == "heavy downpour"


def test_normalize_keeps_keyword_multivalue_distinct_values() -> None:
    """``keyword`` is multivalue: distinct values should all survive."""
    rain = TagSuggestion(
        field="keyword",
        value="rain",
        source="synonym",
        method="controlled_synonym_map",
        confidence=0.5,
    )
    downpour = TagSuggestion(
        field="keyword",
        value="downpour",
        source="synonym",
        method="controlled_synonym_map",
        confidence=0.5,
    )

    cleaned = normalize_and_dedupe([rain, downpour])

    values = sorted(s.value for s in cleaned if s.field == "keyword")
    assert values == ["downpour", "rain"]


def test_normalize_removes_assignment_junk_from_tag_values() -> None:
    desc = TagSuggestion(
        field="description",
        value="sTAKE=49 sFILENAME=SFX_T49.WAV Rain",
        source="filename",
        method="title_case",
        confidence=0.55,
    )
    keyword = TagSuggestion(
        field="keyword",
        value="sSCENE=SFX_",
        source="synonym",
        method="controlled_synonym_map",
        confidence=0.5,
    )

    cleaned = normalize_and_dedupe([desc, keyword])

    assert [(s.field, s.value) for s in cleaned] == [("description", "Rain")]


def test_ucs_synonym_fallback_emits_when_only_one_synonym_word_matches() -> None:
    """A single shared synonym token (>=3 chars) should yield a tier-0 catalog hit."""
    catalog = UcsCatalog(
        tool_version="test",
        provenance=UcsCatalogProvenance(
            source_url="https://example/",
            source_path="/tmp/cat.csv",
            source_format="soundminer_csv",
            release_version="v8",
            imported_at="2026-01-01T00:00:00+00:00",
            attribution="test",
            entry_count=1,
        ),
        entries=[
            UcsEntry(
                cat_short="AMB",
                category="AMBIENCE",
                subcategory="RAIN",
                cat_id="AMBRain",
                synonyms=["falling water"],
            ),
        ],
    )
    prior = [
        TagSuggestion(
            field="description",
            value="Water",
            source="filename",
            method="title_case",
            confidence=0.6,
        )
    ]

    suggestions = suggest_ucs_from_prior_tags(prior, catalog)
    by_field = {s.field: s for s in suggestions}

    assert by_field["ucs_category"].value == "AMBIENCE"
    assert by_field["ucs_subcategory"].value == "RAIN"
    assert by_field["ucs_category"].confidence == 0.62
    assert any("matched:synonym_token:water" in entry for entry in by_field["ucs_category"].evidence)


def test_ucs_synonym_fallback_emits_review_grade_suggestion_on_tie() -> None:
    """Ambiguous UCS catalog hits should be visible for review instead of disappearing."""
    catalog = UcsCatalog(
        tool_version="test",
        provenance=UcsCatalogProvenance(
            source_url="https://example/",
            source_path="/tmp/cat.csv",
            source_format="soundminer_csv",
            release_version="v8",
            imported_at="2026-01-01T00:00:00+00:00",
            attribution="test",
            entry_count=2,
        ),
        entries=[
            UcsEntry(
                cat_short="AMB",
                category="AMBIENCE",
                subcategory="RAIN",
                cat_id="AMBRain",
                synonyms=["soft rain"],
            ),
            UcsEntry(
                cat_short="AMB",
                category="AMBIENCE",
                subcategory="WIND",
                cat_id="AMBWind",
                synonyms=["soft wind"],
            ),
        ],
    )
    prior = [
        TagSuggestion(
            field="description",
            value="Soft",
            source="filename",
            method="title_case",
            confidence=0.6,
        )
    ]

    suggestions = suggest_ucs_from_prior_tags(prior, catalog)
    by_field = {s.field: s for s in suggestions}

    assert by_field["ucs_category"].value == "AMBIENCE"
    assert by_field["ucs_subcategory"].value == "RAIN"
    assert by_field["ucs_category"].confidence == 0.62
    assert any("ambiguous_alternative:AMB_WIND:AMBWind" in entry for entry in by_field["ucs_category"].evidence)


def test_synonym_output_does_not_feed_ucs_catalog_matching(tmp_path: Path) -> None:
    catalog = UcsCatalog(
        tool_version="test",
        provenance=UcsCatalogProvenance(
            source_url="https://example/",
            source_path="/tmp/cat.csv",
            source_format="soundminer_csv",
            release_version="v8",
            imported_at="2026-01-01T00:00:00+00:00",
            attribution="test",
            entry_count=1,
        ),
        entries=[
            UcsEntry(
                cat_short="TECH",
                category="TECHNOLOGY",
                subcategory="ROBOTIC",
                cat_id="TECHRobotic",
                synonyms=["robotic"],
            ),
        ],
    )
    file_path = tmp_path / "library" / "Servo Movement 01.wav"
    file_path.parent.mkdir()
    ctx = SuggestContext(
        file_id=1,
        path=file_path,
        filename=file_path.name,
        stem=file_path.stem,
        root=tmp_path / "library",
        catalog=catalog,
        include_synonyms=True,
    )

    suggestions = run_suggestors(ctx)

    assert not any(
        s.source == "ucs_catalog" and s.field == "ucs_subcategory" and s.value == "ROBOTIC" for s in suggestions
    )
    assert any(s.source == "synonym" and s.field == "keyword" and s.value == "robotic" for s in suggestions)


def test_ucs_prior_tag_suggestions_ignore_synonym_source() -> None:
    catalog = UcsCatalog(
        tool_version="test",
        provenance=UcsCatalogProvenance(
            source_url="https://example/",
            source_path="/tmp/cat.csv",
            source_format="soundminer_csv",
            release_version="v8",
            imported_at="2026-01-01T00:00:00+00:00",
            attribution="test",
            entry_count=1,
        ),
        entries=[
            UcsEntry(
                cat_short="TECH",
                category="TECHNOLOGY",
                subcategory="ROBOTIC",
                cat_id="TECHRobotic",
                synonyms=["robotic"],
            ),
        ],
    )
    prior = [
        TagSuggestion(
            field="keyword",
            value="robotic",
            source="synonym",
            method="controlled_synonym_map",
            confidence=0.62,
        )
    ]

    assert suggest_ucs_from_prior_tags(prior, catalog) == []


def test_ucs_prior_tag_suggestions_can_upgrade_ucs_stem_catalog_miss() -> None:
    prior = [
        TagSuggestion(
            field="ucs_category",
            value="BAD",
            source="ucs_stem",
            method="ucs_heuristic",
            confidence=0.75,
        ),
        TagSuggestion(
            field="ucs_subcategory",
            value="RAIN",
            source="ucs_stem",
            method="ucs_heuristic",
            confidence=0.75,
        ),
        TagSuggestion(
            field="description",
            value="Rain",
            source="ucs_stem",
            method="ucs_heuristic",
            confidence=0.75,
        ),
    ]

    suggestions = suggest_ucs_from_prior_tags(prior, _sample_catalog())
    by_field = {s.field: s for s in suggestions}

    assert by_field["ucs_category"].value == "AMBIENCE"
    assert by_field["ucs_category"].source == "ucs_catalog"
    assert by_field["ucs_category"].method == "prior_tag_catalog_match"


# ---------------------------------------------------------------------------
# Orchestrator integration tests
# ---------------------------------------------------------------------------


def _seed_files(tmp_db: Path, files: list[dict]) -> None:
    conn = get_connection(tmp_db)
    for item in files:
        path = Path(item["path"])
        mtime = item.get("mtime")
        if mtime is None:
            mtime = path.stat().st_mtime if path.exists() else 0.0
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
                mtime,
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
    # UCS, group, and path all propose a ``description`` for each file.
    # ``normalize_and_dedupe`` keeps the highest-priority value and folds the
    # lower-priority sources into the winner's evidence as ``alternative:`` /
    # ``also_from:`` lines, so per-file sources are not duplicated in
    # ``by_source``. We confirm the report still draws on all three by
    # inspecting the winning entry's evidence.
    sources_used = set(report.summary.by_source.keys())
    assert "ucs_stem" in sources_used
    fields = set(report.summary.by_field.keys())
    assert {"ucs_category", "ucs_subcategory", "description", "take_number"}.issubset(fields)
    description_evidence = " ".join(
        " ".join(suggestion.evidence)
        for entry in report.entries
        for suggestion in entry.suggestions
        if suggestion.field == "description"
    )
    assert "group" in description_evidence
    assert "path" in description_evidence


def test_report_scopes_windows_style_index_paths(tmp_db: Path) -> None:
    conn = get_connection(tmp_db)
    conn.executemany(
        """
        INSERT INTO files (
            path, filename, stem, extension, size_bytes, mtime, md5,
            sample_rate, bit_depth, channels, duration_s, scanned_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "C:\\Lib\\AMB_RAIN_01.wav",
                "AMB_RAIN_01.wav",
                "AMB_RAIN_01",
                ".wav",
                10,
                0.0,
                "A",
                48000,
                24,
                2,
                1.0,
                "2026",
            ),
            (
                "C:\\Lib2\\AMB_RAIN_02.wav",
                "AMB_RAIN_02.wav",
                "AMB_RAIN_02",
                ".wav",
                10,
                0.0,
                "B",
                48000,
                24,
                2,
                1.0,
                "2026",
            ),
        ],
    )
    conn.commit()
    conn.close()

    report = build_tag_suggestion_report(Path("c:/lib"), tmp_db)

    assert report.summary.files_considered == 1
    assert report.entries[0].path == "C:\\Lib\\AMB_RAIN_01.wav"


def test_report_progress_reaches_final_file_when_filters_drop_every_suggestion(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    _seed_files(
        tmp_db,
        [
            {"path": root / "AMB_RAIN_01.wav", "md5": "A"},
            {"path": root / "Car Crash 02.wav", "md5": "B"},
            {"path": root / "Metal Hit 03.wav", "md5": "C"},
        ],
    )
    events: list[tuple[str, int, int | None, str]] = []

    report = build_tag_suggestion_report(
        root,
        tmp_db,
        fields=["field_that_will_not_match"],
        progress_callback=lambda phase, completed, total, message: events.append((phase, completed, total, message)),
    )

    suggesting_events = [event for event in events if event[0] == "suggesting"]
    assert report.summary.files_considered == 3
    assert report.summary.files_with_suggestions == 0
    assert suggesting_events[-1][1:3] == (3, 3)


def test_report_can_include_synonym_keyword_suggestions(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Vehicles"
    folder.mkdir(parents=True)
    _seed_files(tmp_db, [{"path": folder / "Car Crash 01.wav", "md5": "A"}])

    default_report = build_tag_suggestion_report(root, tmp_db)
    synonym_report = build_tag_suggestion_report(root, tmp_db, include_synonyms=True)

    assert "synonym" not in default_report.summary.by_source
    assert synonym_report.summary.by_source["synonym"] == 5
    assert synonym_report.summary.by_field["keyword"] == 5
    keywords = {
        suggestion.value
        for entry in synonym_report.entries
        for suggestion in entry.suggestions
        if suggestion.source == "synonym"
    }
    assert keywords == {"vehicle impact", "auto collision", "wreck", "impact", "collision"}


def test_report_can_limit_synonym_keyword_suggestions(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Vehicles"
    folder.mkdir(parents=True)
    _seed_files(tmp_db, [{"path": folder / "Car Crash 01.wav", "md5": "A"}])

    report = build_tag_suggestion_report(
        root,
        tmp_db,
        include_synonyms=True,
        synonym_limit=2,
        synonym_depth=1,
    )

    assert report.synonym_limit == 2
    assert report.synonym_depth == 1
    assert report.summary.by_source["synonym"] == 2
    keywords = [
        suggestion.value
        for entry in report.entries
        for suggestion in entry.suggestions
        if suggestion.source == "synonym"
    ]
    assert keywords == ["vehicle impact", "impact"]


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
    suggestion = next(s for s in report.entries[0].suggestions if s.field == "ucs_category")
    assert suggestion.value == "AMBIENCE"
    assert suggestion.confidence == 0.95


def test_report_uses_prior_tags_to_drive_ucs_catalog_suggestions(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    _seed_files(tmp_db, [{"path": root / "Light Rain 01.wav", "md5": "A"}])
    catalog_path = tmp_path / "ucs_catalog.json"
    save_catalog(_sample_catalog(), catalog_path)

    report = build_tag_suggestion_report(root, tmp_db, ucs_catalog_path=catalog_path)

    assert report.summary.by_source["ucs_catalog"] == 2
    by_field = {suggestion.field: suggestion for suggestion in report.entries[0].suggestions}
    assert by_field["ucs_category"].value == "AMBIENCE"
    assert by_field["ucs_subcategory"].value == "RAIN"
    assert by_field["ucs_category"].method == "prior_tag_catalog_match"


def test_report_filters_by_source_and_field(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Ambience"
    folder.mkdir(parents=True)
    _seed_files(tmp_db, [{"path": folder / "AMB_RAIN_01.wav", "md5": "A"}])

    catalog_path = tmp_path / "ucs_catalog.json"
    catalog_path.write_text(json.dumps(_sample_catalog().model_dump()), encoding="utf-8")

    report = build_tag_suggestion_report(
        root,
        tmp_db,
        ucs_catalog_path=catalog_path,
        sources=["ucs_catalog"],
        fields=["ucs_category,ucs_subcategory"],
    )

    assert report.sources == ["ucs_catalog"]
    assert report.fields == ["ucs_category", "ucs_subcategory"]
    assert report.summary.total_suggestions == 2
    assert report.summary.by_source == {"ucs_catalog": 2}
    assert report.summary.by_field == {"ucs_category": 1, "ucs_subcategory": 1}
    assert {s.field for s in report.entries[0].suggestions} == {"ucs_category", "ucs_subcategory"}


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
    assert payload["tool"] == "sfxworkbench"
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
    assert any(entry.field == "ucs_category" and entry.proposed_value == "SFX" for entry in plan.entries)

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
    assert ("ucs_category", "SFX", "ucs_stem") in [(row["field"], row["value"], row["source"]) for row in rows]
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


def test_tag_apply_rejects_file_changed_after_plan(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Impacts"
    folder.mkdir(parents=True)
    audio = folder / "SFX_HIT_01.wav"
    original = b"not really audio"
    audio.write_bytes(original)
    _seed_files(
        tmp_db,
        [
            {
                "path": audio,
                "md5": hashlib.md5(original).hexdigest(),
                "size": len(original),
            }
        ],
    )
    plan = build_tag_plan(root, db_path=tmp_db, min_confidence=0.7)
    plan_path = tmp_path / "tag_plan.json"
    write_tag_plan(plan, plan_path, quiet=True)
    review_tag_plan(plan_path, approve_all=True, quiet=True)

    audio.write_bytes(b"changed audio bytes")
    result = apply_tag_plan(plan_path, db_path=tmp_db, dry_run=False, require_reviewed=True, quiet=True)

    assert result.applied == 0
    assert result.errors
    assert "changed" in result.errors[0]["error"]
    conn = get_connection(tmp_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM accepted_tags").fetchone()[0] == 0
    finally:
        conn.close()


def test_synonym_keywords_can_flow_through_tag_plan_to_accepted_tags(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Vehicles"
    folder.mkdir(parents=True)
    audio = folder / "Car Crash 01.wav"
    audio.write_bytes(b"not really audio")
    _seed_files(tmp_db, [{"path": audio, "md5": "A", "size": len(audio.read_bytes())}])

    plan = build_tag_plan(
        root,
        db_path=tmp_db,
        include_synonyms=True,
        sources=["synonym"],
        fields=["keyword"],
    )

    assert plan.summary.candidate_entries == 5
    assert {entry.field for entry in plan.entries} == {"keyword"}
    assert {entry.source for entry in plan.entries} == {"synonym"}

    plan_path = tmp_path / "synonym_tag_plan.json"
    write_tag_plan(plan, plan_path, quiet=True)
    review_tag_plan(plan_path, approve_all=True, quiet=True)
    apply_tag_plan(plan_path, db_path=tmp_db, dry_run=False, require_reviewed=True, quiet=True)

    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT field, value, source FROM accepted_tags ORDER BY value").fetchall()
    conn.close()
    assert {(row["field"], row["value"], row["source"]) for row in rows} == {
        ("keyword", "auto collision", "synonym"),
        ("keyword", "collision", "synonym"),
        ("keyword", "impact", "synonym"),
        ("keyword", "vehicle impact", "synonym"),
        ("keyword", "wreck", "synonym"),
    }


def test_limited_synonym_keywords_can_flow_through_tag_plan(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Vehicles"
    folder.mkdir(parents=True)
    audio = folder / "Car Crash 01.wav"
    audio.write_bytes(b"not really audio")
    _seed_files(tmp_db, [{"path": audio, "md5": "A", "size": len(audio.read_bytes())}])

    plan = build_tag_plan(
        root,
        db_path=tmp_db,
        include_synonyms=True,
        synonym_limit=2,
        synonym_depth=1,
        sources=["synonym"],
        fields=["keyword"],
    )

    assert [entry.proposed_value for entry in plan.entries] == ["vehicle impact", "impact"]


def test_tag_plan_filters_source_report_by_source_and_field(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Ambience"
    folder.mkdir(parents=True)
    _seed_files(tmp_db, [{"path": folder / "AMB_RAIN_01.wav", "md5": "A"}])

    catalog_path = tmp_path / "ucs_catalog.json"
    catalog_path.write_text(json.dumps(_sample_catalog().model_dump()), encoding="utf-8")
    report = build_tag_suggestion_report(root, tmp_db, ucs_catalog_path=catalog_path, limit=0)
    report_path = tmp_path / "tag_suggestions.json"
    write_tag_suggestion_report(report, report_path, quiet=True)

    plan = build_tag_plan(
        root,
        db_path=tmp_db,
        source_report=report_path,
        sources=["ucs_catalog"],
        fields=["ucs_category", "ucs_subcategory"],
    )

    assert plan.sources == ["ucs_catalog"]
    assert plan.fields == ["ucs_category", "ucs_subcategory"]
    assert plan.summary.candidate_entries == 2
    assert {entry.field for entry in plan.entries} == {"ucs_category", "ucs_subcategory"}
    assert {entry.source for entry in plan.entries} == {"ucs_catalog"}


def test_tag_plan_can_import_reviewed_csv_bulk_updates(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Impacts"
    folder.mkdir(parents=True)
    audio = folder / "Hit 01.wav"
    audio.write_bytes(b"not really audio")
    _seed_files(tmp_db, [{"path": audio, "md5": "A", "size": len(audio.read_bytes())}])
    csv_path = tmp_path / "bulk_tags.csv"
    csv_path.write_text(
        "path,field,value,source,review_status\n"
        "Impacts/Hit 01.wav,description,Metal Hit,user_csv,approved\n"
        "Impacts/Hit 01.wav,keyword,impact,user_csv,approved\n",
        encoding="utf-8",
    )

    plan = build_tag_plan(root, db_path=tmp_db, csv_path=csv_path)

    assert plan.source_report == str(csv_path)
    assert plan.errors == []
    assert plan.summary.candidate_entries == 2
    assert plan.summary.approved_entries == 2
    assert {entry.source for entry in plan.entries} == {"user_csv"}

    plan_path = tmp_path / "csv_tag_plan.json"
    write_tag_plan(plan, plan_path, quiet=True)
    applied = apply_tag_plan(plan_path, db_path=tmp_db, dry_run=False, require_reviewed=True, quiet=True)

    assert applied.applied == 2
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT field, value, source FROM accepted_tags ORDER BY field").fetchall()
    conn.close()
    assert [(row["field"], row["value"], row["source"]) for row in rows] == [
        ("description", "Metal Hit", "user_csv"),
        ("keyword", "impact", "user_csv"),
    ]


def test_tag_plan_skips_existing_and_duplicate_pending_tags(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Impacts"
    folder.mkdir(parents=True)
    audio = folder / "Hit 01.wav"
    audio.write_bytes(b"not really audio")
    _seed_files(tmp_db, [{"path": audio, "md5": "A", "size": len(audio.read_bytes())}])
    conn = get_connection(tmp_db)
    try:
        file_id = conn.execute("SELECT id FROM files WHERE path = ?", (str(audio),)).fetchone()[0]
        conn.execute(
            """
            INSERT INTO accepted_tags (
                file_id, field, value, source, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_id, "keyword", "impact", "test", "2026-05-12T00:00:00", "2026-05-12T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    csv_path = tmp_path / "bulk_tags.csv"
    csv_path.write_text(
        "path,field,value,source,review_status\n"
        "Impacts/Hit 01.wav,keyword,impact,user_csv,approved\n"
        "Impacts/Hit 01.wav,keyword,whoosh,user_csv,approved\n"
        "Impacts/Hit 01.wav,keyword, whoosh ,user_csv,approved\n",
        encoding="utf-8",
    )

    plan = build_tag_plan(root, db_path=tmp_db, csv_path=csv_path)

    assert [entry.action for entry in plan.entries] == ["skip_existing", "add", "skip_existing"]
    assert plan.summary.add_entries == 1
    assert plan.summary.skip_existing_entries == 2

    plan_path = tmp_path / "csv_tag_plan.json"
    write_tag_plan(plan, plan_path, quiet=True)
    dry_run = apply_tag_plan(plan_path, db_path=tmp_db, require_reviewed=True, quiet=True)
    applied = apply_tag_plan(plan_path, db_path=tmp_db, dry_run=False, require_reviewed=True, quiet=True)

    assert dry_run.applied == 1
    assert dry_run.skipped == 2
    assert applied.applied == 1
    assert applied.skipped == 2
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT field, value FROM accepted_tags ORDER BY value").fetchall()
    conn.close()
    assert [(row["field"], row["value"]) for row in rows] == [("keyword", "impact"), ("keyword", "whoosh")]


def test_tag_plan_skips_description_when_embedded_description_exists(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Impacts"
    folder.mkdir(parents=True)
    audio = folder / "Hit 01.wav"
    audio.write_bytes(b"not really audio")
    _seed_files(tmp_db, [{"path": audio, "md5": "A", "size": len(audio.read_bytes())}])
    conn = get_connection(tmp_db)
    try:
        file_id = conn.execute("SELECT id FROM files WHERE path = ?", (str(audio),)).fetchone()[0]
        conn.execute(
            """
            INSERT INTO metadata_fields (
                file_id, namespace, key, value, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_id, "bext", "description", "Hit", "test", "2026-05-12T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    plan = build_tag_plan(root, db_path=tmp_db, min_confidence=0.0)
    description_entries = [entry for entry in plan.entries if entry.field == "description"]

    assert description_entries
    assert {entry.action for entry in description_entries} == {"skip_existing"}
    assert all("Hit" in entry.existing_values for entry in description_entries)


def test_tag_plan_replaces_technical_embedded_description_blob(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Ambience"
    folder.mkdir(parents=True)
    audio = folder / "Background Room Tone 01.wav"
    audio.write_bytes(b"not really audio")
    _seed_files(tmp_db, [{"path": audio, "md5": "A", "size": len(audio.read_bytes())}])
    technical_blob = (
        "sTAKE=48 sSWVER=2.63 sPROJECT= sSCENE=SFX_ "
        "sFILENAME=SFX_T48.WAV sTAPE=130208 sTRK1=Track A sTRK2=Track B sNOTE="
    )
    conn = get_connection(tmp_db)
    try:
        file_id = conn.execute("SELECT id FROM files WHERE path = ?", (str(audio),)).fetchone()[0]
        conn.execute(
            """
            INSERT INTO metadata_fields (
                file_id, namespace, key, value, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_id, "bext", "description", technical_blob, "test", "2026-05-12T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    plan = build_tag_plan(root, db_path=tmp_db, min_confidence=0.0)
    description_entries = [entry for entry in plan.entries if entry.field == "description"]

    assert description_entries
    assert {entry.action for entry in description_entries} == {"add"}
    assert all(entry.existing_values == [] for entry in description_entries)


def test_tag_plan_summarize_groups_values_for_review(tmp_path: Path, tmp_db: Path) -> None:
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
    plan = build_tag_plan(root, db_path=tmp_db, min_confidence=0.7)
    plan_path = tmp_path / "tag_plan.json"
    write_tag_plan(plan, plan_path, quiet=True)

    summary = summarize_tag_plan(plan_path, fields=["ucs_category"], value_limit=10)

    assert summary.total_entries == 2
    assert summary.by_field == {"ucs_category": 2}
    assert summary.by_source == {"ucs_stem": 2}
    assert summary.values[0].field == "ucs_category"
    assert summary.values[0].value == "SFX"
    assert summary.values[0].count == 2
    assert summary.values[0].sample_files == ["SFX_HIT_01.wav", "SFX_HIT_02.wav"]


def test_tag_review_selector_approves_and_rejects_batches(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Ambience"
    folder.mkdir(parents=True)
    _seed_files(tmp_db, [{"path": folder / "AMB_RAIN_01.wav", "md5": "A"}])
    catalog_path = tmp_path / "ucs_catalog.json"
    catalog_path.write_text(json.dumps(_sample_catalog().model_dump()), encoding="utf-8")
    plan = build_tag_plan(
        root,
        db_path=tmp_db,
        ucs_catalog_path=catalog_path,
        min_confidence=0.8,
        sources=["ucs_catalog"],
        fields=["ucs_category", "ucs_subcategory"],
    )
    plan_path = tmp_path / "tag_plan.json"
    write_tag_plan(plan, plan_path, quiet=True)

    review = review_tag_plan(
        plan_path,
        approve_fields=["ucs_category"],
        reject_values=["RAIN"],
        only_status=["pending"],
        quiet=True,
    )
    reviewed = summarize_tag_plan(plan_path, value_limit=0)

    assert review.approved_entries == 1
    assert review.rejected_entries == 1
    assert reviewed.by_review_status == {"approved": 1, "rejected": 1}


def test_tag_sidecar_export_and_import_round_trip(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Impacts"
    folder.mkdir(parents=True)
    audio = folder / "SFX_HIT_01.wav"
    audio.write_bytes(b"not really audio")
    _seed_files(tmp_db, [{"path": audio, "md5": "A", "size": len(audio.read_bytes())}])

    plan = build_tag_plan(root, db_path=tmp_db, min_confidence=0.7)
    plan_path = tmp_path / "tag_plan.json"
    write_tag_plan(plan, plan_path, quiet=True)
    review_tag_plan(plan_path, approve_all=True, quiet=True)
    apply_tag_plan(
        plan_path,
        db_path=tmp_db,
        dry_run=False,
        require_reviewed=True,
        log_path=tmp_path / "tag_apply_log.json",
        quiet=True,
    )

    sidecar = build_tag_sidecar_report(tmp_db, root=root)
    sidecar_path = tmp_path / "tags.sidecar.json"
    write_tag_sidecar_report(sidecar, sidecar_path, quiet=True)

    assert sidecar.entry_count == 1
    assert sidecar.tag_count == plan.summary.add_entries
    assert sidecar.entries[0].path == str(audio)
    assert any(tag.field == "ucs_category" and tag.value == "SFX" for tag in sidecar.entries[0].tags)

    conn = get_connection(tmp_db)
    conn.execute("DELETE FROM accepted_tags")
    conn.commit()
    conn.close()

    dry_run = import_tag_sidecar(sidecar_path, db_path=tmp_db, quiet=True)
    assert dry_run.dry_run is True
    assert dry_run.imported == sidecar.tag_count

    imported = import_tag_sidecar(sidecar_path, db_path=tmp_db, dry_run=False, quiet=True)
    assert imported.imported == sidecar.tag_count
    assert imported.errors == []
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT field, value FROM accepted_tags ORDER BY field, value").fetchall()
    conn.close()
    assert ("ucs_category", "SFX") in [(row["field"], row["value"]) for row in rows]


def test_tag_sidecar_import_rejects_file_changed_after_export(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Impacts"
    folder.mkdir(parents=True)
    audio = folder / "SFX_HIT_01.wav"
    original = b"not really audio"
    audio.write_bytes(original)
    _seed_files(
        tmp_db,
        [
            {
                "path": audio,
                "md5": hashlib.md5(original).hexdigest(),
                "size": len(original),
            }
        ],
    )
    plan = build_tag_plan(root, db_path=tmp_db, min_confidence=0.7)
    plan_path = tmp_path / "tag_plan.json"
    write_tag_plan(plan, plan_path, quiet=True)
    review_tag_plan(plan_path, approve_all=True, quiet=True)
    apply_tag_plan(plan_path, db_path=tmp_db, dry_run=False, require_reviewed=True, quiet=True)

    sidecar = build_tag_sidecar_report(tmp_db, root=root)
    sidecar_path = tmp_path / "tags.sidecar.json"
    write_tag_sidecar_report(sidecar, sidecar_path, quiet=True)
    conn = get_connection(tmp_db)
    conn.execute("DELETE FROM accepted_tags")
    conn.commit()
    conn.close()

    audio.write_bytes(b"changed audio bytes")
    imported = import_tag_sidecar(sidecar_path, db_path=tmp_db, dry_run=False, quiet=True)

    assert imported.imported == 0
    assert imported.errors
    assert "changed" in imported.errors[0]["error"]


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


# ---------------------------------------------------------------------------
# Suggestor protocol (PR #5)
# ---------------------------------------------------------------------------


def _suggest_ctx(
    tmp_path: Path,
    *,
    stem: str = "SFX_GUNSHOT_PISTOL_01",
    catalog=None,
    group_match=None,
    include_synonyms: bool = False,
    synonym_limit: int = 0,
    synonym_depth: int = 0,
):
    """Build a SuggestContext for unit tests with sensible defaults."""
    from sfxworkbench.tag_suggest import SuggestContext

    file_path = tmp_path / "library" / f"{stem}.wav"
    return SuggestContext(
        file_id=1,
        path=file_path,
        filename=file_path.name,
        stem=stem,
        root=tmp_path / "library",
        catalog=catalog,
        group_match=group_match,
        include_synonyms=include_synonyms,
        synonym_limit=synonym_limit,
        synonym_depth=synonym_depth,
    )


def test_default_suggestors_have_distinct_names() -> None:
    from sfxworkbench.tag_suggest import DEFAULT_SUGGESTORS

    names = [s.name for s in DEFAULT_SUGGESTORS]
    assert len(set(names)) == len(names), f"duplicate suggestor names: {names}"
    assert names == ["ucs_stem", "group", "filename", "path", "ucs_prior_tags", "synonym"]


def test_run_suggestors_concatenates_in_order(tmp_path: Path) -> None:
    from sfxworkbench.tag_suggest import run_suggestors

    ctx = _suggest_ctx(tmp_path, stem="SFX_GUNSHOT_PISTOL_01")
    suggestions = run_suggestors(ctx)
    # UCS stem suggestor fires first and provides ucs_category before any filename suggestion appears.
    sources_in_order = [s.source for s in suggestions]
    assert "ucs_stem" in sources_in_order
    assert (
        sources_in_order.index("ucs_stem") < sources_in_order.index("filename")
        if "filename" in sources_in_order
        else True
    )


def test_group_suggestor_returns_empty_without_group_match(tmp_path: Path) -> None:
    from sfxworkbench.tag_suggest import GroupSuggestor

    ctx = _suggest_ctx(tmp_path, group_match=None)
    assert list(GroupSuggestor().propose(ctx, prior=[])) == []


def test_group_suggestor_delegates_when_group_match_present(tmp_path: Path) -> None:
    from sfxworkbench.tag_suggest import GroupSuggestor

    member = RelatedSoundFile(path=str(tmp_path / "AMB_RAIN_01.wav"), filename="AMB_RAIN_01.wav", marker="01")
    sibling = RelatedSoundFile(path=str(tmp_path / "AMB_RAIN_02.wav"), filename="AMB_RAIN_02.wav", marker="02")
    group = RelatedSoundGroup(
        group_id=1,
        parent_path=str(tmp_path),
        inferred_stem="AMB_RAIN",
        reason="numbered_take",
        confidence="high",
        file_count=2,
        files=[member, sibling],
    )
    ctx = _suggest_ctx(tmp_path, group_match=(group, member))

    suggestions = list(GroupSuggestor().propose(ctx, prior=[]))
    assert suggestions, "group suggestor should produce output when a group_match is present"
    assert all(s.source == "group" for s in suggestions)


def test_filename_suggestor_skips_description_when_ucs_or_group_already_did(tmp_path: Path) -> None:
    """Gating logic that used to live inline in the orchestrator now lives in the suggestor."""
    from sfxworkbench.models import TagSuggestion
    from sfxworkbench.tag_suggest import FilenameSuggestor

    ctx = _suggest_ctx(tmp_path, stem="Metal Hit 04")  # would normally produce a description

    no_prior = list(FilenameSuggestor().propose(ctx, prior=[]))
    assert any(s.field == "description" for s in no_prior)

    ucs_prior = [
        TagSuggestion(
            field="description",
            value="Metal",
            source="ucs_stem",
            method="ucs_heuristic",
            confidence=0.75,
            evidence=["x"],
        )
    ]
    gated = list(FilenameSuggestor().propose(ctx, prior=ucs_prior))
    assert not any(s.field == "description" for s in gated)
    # Take number is still useful corroboration.
    assert any(s.field == "take_number" for s in gated)


def test_filename_suggestor_does_not_skip_description_for_low_confidence_prior(tmp_path: Path) -> None:
    """Only the 'ucs_stem', 'ucs_catalog', and 'group' sources gate filename description."""
    from sfxworkbench.models import TagSuggestion
    from sfxworkbench.tag_suggest import FilenameSuggestor

    ctx = _suggest_ctx(tmp_path, stem="Metal Hit 04")
    path_prior = [
        TagSuggestion(
            field="description",
            value="Whatever",
            source="path",
            method="folder_token",
            confidence=0.50,
            evidence=["x"],
        )
    ]
    suggestions = list(FilenameSuggestor().propose(ctx, prior=path_prior))
    # path-sourced description should NOT block filename description.
    assert any(s.field == "description" for s in suggestions)


def test_synonym_suggestor_only_runs_when_include_synonyms_is_true(tmp_path: Path) -> None:
    from sfxworkbench.tag_suggest import SynonymSuggestor, suggest_from_filename

    base = suggest_from_filename("Car Crash 01")
    assert base, "precondition: filename suggestor produces something for this stem"

    ctx_off = _suggest_ctx(tmp_path, include_synonyms=False)
    assert list(SynonymSuggestor().propose(ctx_off, prior=base)) == []

    ctx_on = _suggest_ctx(tmp_path, include_synonyms=True)
    result = list(SynonymSuggestor().propose(ctx_on, prior=base))
    # SynonymSuggestor mirrors suggest_synonym_keywords behavior.
    assert all(s.source == "synonym" for s in result)


def test_user_configured_confidence_profile_overrides_defaults() -> None:
    """A user-set ConfidenceProfile flows through to per-suggestor confidence values."""
    from sfxworkbench.config import ConfidenceProfile

    overridden = ConfidenceProfile(ucs_heuristic=0.10, filename_take=0.99, path=0.50)

    # Default profile produces the historical 0.75 anchor.
    suggestions = suggest_from_ucs_stem("SFX_GUNSHOT_PISTOL_01")
    assert any(s.confidence == 0.75 for s in suggestions)

    # User profile shifts every emitted confidence to the override.
    overridden_suggestions = suggest_from_ucs_stem("SFX_GUNSHOT_PISTOL_01", profile=overridden)
    assert all(s.confidence == 0.10 for s in overridden_suggestions), [s.confidence for s in overridden_suggestions]

    # Same propagation for filename take_number.
    filename_default = suggest_from_filename("Pistol_01")
    take_default = next(s for s in filename_default if s.field == "take_number")
    assert take_default.confidence == 0.60

    filename_overridden = suggest_from_filename("Pistol_01", profile=overridden)
    take_overridden = next(s for s in filename_overridden if s.field == "take_number")
    assert take_overridden.confidence == 0.99


def test_build_tag_suggestion_report_uses_default_suggestors(tmp_path: Path, tmp_db: Path) -> None:
    """End-to-end regression: the orchestrator's output matches what individual suggestors produce."""
    root = tmp_path / "library"
    folder = root / "Pistol"
    folder.mkdir(parents=True)
    _seed_files(tmp_db, [{"path": folder / "SFX_GUNSHOT_PISTOL_01.wav", "md5": "A"}])

    report = build_tag_suggestion_report(root, tmp_db)
    assert len(report.entries) == 1
    sources = {s.source for s in report.entries[0].suggestions}
    # Both ucs_stem (from the UCS-shaped filename) and filename or path heuristics fire.
    assert "ucs_stem" in sources
