"""Tests for genre-weighted score fusion."""

from __future__ import annotations

import numpy as np

from photo_workflow.scoring_types import (
    FaceDetection,
    SharpnessScores,
    CompositionScores,
    ExposureScores,
    GenreResult,
    FusionResult,
)
from photo_workflow.score_fusion import (
    bootstrap_weight_profiles,
    estimate_eye_openness,
    fuse_scores,
    SUBJECT_WEIGHTS,
    TYPE_WEIGHTS,
)
from photo_workflow.genre_router import SUBJECTS, PHOTO_TYPES


def _make_sharpness(**kwargs) -> SharpnessScores:
    defaults = dict(subject=0.7, eye_region=0.8, background=0.3,
                    sharpness_contrast=2.3, blur_type="bokeh", overall=0.7)
    defaults.update(kwargs)
    return SharpnessScores(**defaults)


def _make_composition(**kwargs) -> CompositionScores:
    defaults = dict(rule_of_thirds=0.6, symmetry=0.4, leading_lines=0.3,
                    negative_space=0.65, subject_isolation=0.7, balance=0.6, overall=0.55)
    defaults.update(kwargs)
    return CompositionScores(**defaults)


def _make_exposure(**kwargs) -> ExposureScores:
    defaults = dict(zone_entropy=0.8, zone_diversity=8, clipping_shadows=0.01,
                    clipping_highlights=0.02, dynamic_range=0.85, midtone_density=0.4,
                    face_exposure=-1.0, style="normal", style_confidence=0.0, overall=0.75)
    defaults.update(kwargs)
    return ExposureScores(**defaults)


def _make_genre(subject: str = "wildlife", photo_type: str = "candid",
                subject_confidence: float = 0.85, type_confidence: float = 0.5) -> GenreResult:
    subj_dist = {s: 0.02 for s in SUBJECTS}
    subj_dist[subject] = subject_confidence
    total = sum(subj_dist.values())
    subj_dist = {s: v / total for s, v in subj_dist.items()}

    type_dist = {t: 0.02 for t in PHOTO_TYPES}
    type_dist[photo_type] = type_confidence
    total = sum(type_dist.values())
    type_dist = {t: v / total for t, v in type_dist.items()}

    return GenreResult(
        subject=subject,
        subject_confidence=subject_confidence,
        photo_type=photo_type,
        type_confidence=type_confidence,
        subject_distribution=subj_dist,
        type_distribution=type_dist,
        needs_review=False,
    )


def test_bootstrap_profiles_reproduce_hardcoded_master() -> None:
    """DB-backed profiles seeded from the defaults must score identically."""
    args = dict(sharpness=_make_sharpness(), composition=_make_composition(),
                exposure=_make_exposure(), genre=_make_genre(), aesthetic=0.65)
    hardcoded = fuse_scores(**args)
    via_profiles = fuse_scores(**args, weight_profiles=bootstrap_weight_profiles())
    assert via_profiles.master_score == hardcoded.master_score


def test_custom_profiles_change_master_score() -> None:
    """A different profile for the active genre must change the master score."""
    base = fuse_scores(
        sharpness=_make_sharpness(), composition=_make_composition(),
        exposure=_make_exposure(), genre=_make_genre(subject="wildlife", photo_type="candid"),
        aesthetic=0.65,
    )
    # All weight on a sub-score that is high here -> higher master.
    profiles = {"subject": {"wildlife": {"subject_sharpness": 1.0}},
                "type": {"candid": {"subject_sharpness": 1.0}}}
    tuned = fuse_scores(
        sharpness=_make_sharpness(subject=1.0), composition=_make_composition(),
        exposure=_make_exposure(), genre=_make_genre(subject="wildlife", photo_type="candid"),
        aesthetic=0.65, weight_profiles=profiles,
    )
    assert tuned.master_score != base.master_score
    assert tuned.master_score == 1.0  # 0.5*1.0 + 0.5*1.0 weight on subject_sharpness=1.0


def test_missing_profile_falls_back_to_hardcoded() -> None:
    """A profiles dict lacking the active genre falls back per-label, not crashes."""
    profiles = {"subject": {"people": {"subject_sharpness": 1.0}}, "type": {}}
    result = fuse_scores(
        sharpness=_make_sharpness(), composition=_make_composition(),
        exposure=_make_exposure(), genre=_make_genre(subject="wildlife", photo_type="candid"),
        aesthetic=0.65, weight_profiles=profiles,
    )
    assert 0.0 <= result.master_score <= 1.0


def test_aesthetic_none_drops_weight_and_renormalizes() -> None:
    """aesthetic=None must drop aesthetic_clip and renormalize, not fill a constant."""
    common = dict(sharpness=_make_sharpness(), composition=_make_composition(),
                  exposure=_make_exposure(), genre=_make_genre(subject="abstract",
                                                                photo_type="still-life"))
    # abstract weights aesthetic_clip 0.30; a constant 0.0 vs 0.5 fill would swing
    # the master a lot. With renormalization the score must stay a sane [0,1] value
    # and must NOT equal either constant-fill outcome.
    none_res = fuse_scores(**common, aesthetic=None)
    hi = fuse_scores(**common, aesthetic=1.0)
    lo = fuse_scores(**common, aesthetic=0.0)
    assert 0.0 <= none_res.master_score <= 1.0
    # renormalized result is independent of the (absent) aesthetic value, and sits
    # strictly between the all-low and all-high aesthetic extremes
    assert lo.master_score < none_res.master_score < hi.master_score


def test_face_sentinels_dropped_when_no_face() -> None:
    """No-face images drop face_exposure/expression_proxy (0.5 sentinels) and
    renormalize, so the weight goes to real signals instead of a constant."""
    from photo_workflow.score_fusion import _build_sub_score_dict, _compute_master_score
    genre = _make_genre(subject="people", photo_type="documentary")
    ss = _build_sub_score_dict(_make_sharpness(), _make_composition(), _make_exposure(), 1.0)
    ss = {k: 1.0 for k in ss}            # every real signal maxed...
    ss["face_exposure"] = 0.5            # ...but the face sentinels are neutral 0.5
    ss["expression_proxy"] = 0.5
    full = _compute_master_score(ss, genre)
    dropped = _compute_master_score(ss, genre, drop_keys=("face_exposure", "expression_proxy"))
    assert dropped > full                # dropping the 0.5 sentinels lifts the master
    assert abs(dropped - 1.0) < 1e-6     # renormalized over all-1.0 signals -> 1.0


def test_degeneracy_detector_flags_constant_model() -> None:
    """_aesthetic_session_is_degenerate catches a model that ignores its input."""
    from photo_workflow.subject_context import _aesthetic_session_is_degenerate

    class _Input:
        name = "x"
        shape = ["batch", 8]

    class _ConstSession:
        def get_inputs(self): return [_Input()]
        def run(self, _out, _feed): return [np.array([[0.556]], dtype=np.float32)]

    class _LiveSession:
        def get_inputs(self): return [_Input()]
        def run(self, _out, feed):
            return [np.array([[float(np.asarray(feed["x"]).sum())]], dtype=np.float32)]

    assert _aesthetic_session_is_degenerate(_ConstSession()) is True
    assert _aesthetic_session_is_degenerate(_LiveSession()) is False


def test_fuse_scores_returns_fusion_result() -> None:
    """fuse_scores should return a FusionResult."""
    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=_make_genre(),
        aesthetic=0.65,
    )
    assert isinstance(result, FusionResult)
    assert 0.0 <= result.master_score <= 1.0
    assert result.subject == "wildlife"
    assert result.genre == "wildlife"  # backward compat
    assert result.star_rating in range(1, 6)


def test_subject_weights_all_sum_to_one() -> None:
    """Every subject weight profile should sum to 1.0."""
    for subj, weights in SUBJECT_WEIGHTS.items():
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, f"{subj} weights sum to {total}"


def test_type_weights_all_sum_to_one() -> None:
    """Every photo type weight profile should sum to 1.0."""
    for ptype, weights in TYPE_WEIGHTS.items():
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, f"{ptype} weights sum to {total}"


def test_high_scores_produce_high_master() -> None:
    """All-high sub-scores should produce a high master score."""
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.95, eye_region=0.95, background=0.3, overall=0.9),
        composition=_make_composition(rule_of_thirds=0.9, subject_isolation=0.9, overall=0.85),
        exposure=_make_exposure(zone_entropy=0.9, dynamic_range=0.95, overall=0.9),
        genre=_make_genre("wildlife"),
        aesthetic=0.9,
    )
    assert result.master_score > 0.7
    assert result.star_rating >= 4


def test_low_scores_produce_low_master() -> None:
    """All-low sub-scores should produce a low master score."""
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.1, eye_region=0.1, background=0.1, overall=0.1),
        composition=_make_composition(rule_of_thirds=0.1, subject_isolation=0.1, overall=0.1),
        exposure=_make_exposure(zone_entropy=0.2, dynamic_range=0.2, overall=0.2),
        genre=_make_genre("wildlife"),
        aesthetic=0.2,
    )
    assert result.master_score < 0.35
    assert result.star_rating <= 2


def test_hard_reject_motion_global() -> None:
    """motion_global with low subject sharpness should hard reject."""
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.1, eye_region=0.1, blur_type="motion_global"),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=_make_genre("wildlife"),
        aesthetic=0.7,
    )
    assert result.hard_reject is True
    assert "motion_global" in result.hard_reject_reason


def test_hard_reject_misfocused() -> None:
    """Misfocused with very low eye sharpness should hard reject."""
    result = fuse_scores(
        sharpness=_make_sharpness(eye_region=0.1, blur_type="misfocused"),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=_make_genre("people", "portrait"),
        aesthetic=0.7,
    )
    assert result.hard_reject is True
    assert "misfocused" in result.hard_reject_reason


def test_no_hard_reject_for_bokeh() -> None:
    """Bokeh should NOT trigger hard reject."""
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.8, blur_type="bokeh"),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=_make_genre("people", "portrait"),
        aesthetic=0.7,
    )
    assert result.hard_reject is False


def test_color_label_mapping() -> None:
    """Color labels should map correctly from master score."""
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.95, eye_region=0.95, background=0.9, overall=0.9),
        # min-gate uses individual sub-scores (not `overall`), so set them all high
        composition=_make_composition(rule_of_thirds=0.9, symmetry=0.9, leading_lines=0.9,
                                      negative_space=0.9, subject_isolation=0.9, balance=0.9,
                                      colorfulness=0.9, overall=0.9),
        exposure=_make_exposure(zone_entropy=0.9, dynamic_range=0.9, overall=0.9),
        genre=_make_genre("wildlife"),
        aesthetic=0.9,
    )
    assert result.color_label == 3  # BLUE (excellent)

    result2 = fuse_scores(
        sharpness=_make_sharpness(subject=0.1, eye_region=0.1, background=0.1, overall=0.1),
        composition=_make_composition(rule_of_thirds=0.1, symmetry=0.1, leading_lines=0.1,
                                     negative_space=0.1, subject_isolation=0.1, balance=0.1, overall=0.1),
        exposure=_make_exposure(zone_entropy=0.1, dynamic_range=0.1, overall=0.1),
        genre=_make_genre("wildlife"),
        aesthetic=0.1,
    )
    assert result2.color_label == 1  # YELLOW (weak)


def test_soft_genre_blending() -> None:
    """Two-axis scoring should blend subject and type weights."""
    genre = _make_genre("wildlife", "portrait", 0.5, 0.5)

    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=genre,
        aesthetic=0.6,
    )
    assert 0.0 <= result.master_score <= 1.0


# ---------------------------------------------------------------------------
# estimate_eye_openness — intensity-variance heuristic
# ---------------------------------------------------------------------------

def _make_face(left_eye: tuple[int, int], right_eye: tuple[int, int],
               confidence: float = 0.9) -> FaceDetection:
    return FaceDetection(
        bbox=(50, 50, 100, 100),
        landmarks={
            "left_eye": left_eye,
            "right_eye": right_eye,
            "nose": (100, 120),
            "mouth_left": (80, 140),
            "mouth_right": (120, 140),
        },
        confidence=confidence,
    )


def _open_eyes_image() -> np.ndarray:
    """200x200 gray image with high-contrast eye regions (iris/sclera pattern)."""
    img = np.full((200, 200), 180, dtype=np.uint8)
    for r in range(70, 90):
        for c in range(70, 90):
            img[r, c] = 40 if (r + c) % 2 == 0 else 220
    for r in range(70, 90):
        for c in range(110, 130):
            img[r, c] = 40 if (r + c) % 2 == 0 else 220
    return img


def _closed_eyes_image() -> np.ndarray:
    """200x200 gray image with uniform eye regions (eyelid skin)."""
    img = np.full((200, 200), 180, dtype=np.uint8)
    img[70:90, 70:90] = 165
    img[70:90, 110:130] = 165
    return img


def test_eye_openness_high_variance_means_open() -> None:
    """High local variance around eye landmarks indicates eyes open."""
    face = _make_face(left_eye=(80, 80), right_eye=(120, 80))
    img = _open_eyes_image()
    score = estimate_eye_openness(face, img)
    assert score > 0.7, f"Expected open eyes score > 0.7, got {score}"


def test_eye_openness_low_variance_means_closed() -> None:
    """Low local variance around eye landmarks indicates eyes closed."""
    face = _make_face(left_eye=(80, 80), right_eye=(120, 80))
    img = _closed_eyes_image()
    score = estimate_eye_openness(face, img)
    assert score < 0.3, f"Expected closed eyes score < 0.3, got {score}"


def test_eye_openness_one_open_one_closed() -> None:
    """One open eye and one closed should produce a mid-range score."""
    face = _make_face(left_eye=(80, 80), right_eye=(120, 80))
    img = np.full((200, 200), 180, dtype=np.uint8)
    for r in range(70, 90):
        for c in range(70, 90):
            img[r, c] = 40 if (r + c) % 2 == 0 else 220
    img[70:90, 110:130] = 165
    score = estimate_eye_openness(face, img)
    assert 0.2 < score < 0.8, f"Expected mid-range for mixed eyes, got {score}"


def test_eye_openness_landmark_near_edge_clamps_roi() -> None:
    """Eye landmark near image edge should not crash."""
    face = _make_face(left_eye=(5, 5), right_eye=(195, 5))
    img = np.full((200, 200), 128, dtype=np.uint8)
    score = estimate_eye_openness(face, img)
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# expression_proxy in fuse_scores — wired to eye openness
# ---------------------------------------------------------------------------

def test_expression_proxy_eyes_open() -> None:
    """With faces present and eyes open, expression_proxy should be near 1.0."""
    faces = [_make_face(left_eye=(80, 80), right_eye=(120, 80))]
    img = _open_eyes_image()
    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(face_exposure=0.8),
        genre=_make_genre("people", "portrait"),
        aesthetic=0.6,
        faces=faces,
        image_gray=img,
    )
    assert result.sub_scores["expression_proxy"] > 0.7


def test_expression_proxy_eyes_closed() -> None:
    """With faces present and eyes closed, expression_proxy should be near 0.0."""
    faces = [_make_face(left_eye=(80, 80), right_eye=(120, 80))]
    img = _closed_eyes_image()
    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(face_exposure=0.8),
        genre=_make_genre("people", "portrait"),
        aesthetic=0.6,
        faces=faces,
        image_gray=img,
    )
    assert result.sub_scores["expression_proxy"] < 0.3


def test_expression_proxy_no_face() -> None:
    """Without faces, expression_proxy should be neutral 0.5."""
    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(face_exposure=-1.0),
        genre=_make_genre("general", "scenic"),
        aesthetic=0.6,
    )
    assert result.sub_scores["expression_proxy"] == 0.5


# ---------------------------------------------------------------------------
# Both-eyes-closed hard rejection gate
# ---------------------------------------------------------------------------

def test_hard_reject_both_eyes_closed() -> None:
    """All detected faces with closed eyes should trigger hard reject."""
    faces = [_make_face(left_eye=(80, 80), right_eye=(120, 80))]
    img = _closed_eyes_image()
    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(face_exposure=0.8),
        genre=_make_genre("people", "portrait"),
        aesthetic=0.7,
        faces=faces,
        image_gray=img,
    )
    assert result.hard_reject is True
    assert "eyes_closed" in result.hard_reject_reason


def test_no_hard_reject_eyes_open() -> None:
    """Open eyes should not trigger the eyes-closed hard gate."""
    faces = [_make_face(left_eye=(80, 80), right_eye=(120, 80))]
    img = _open_eyes_image()
    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(face_exposure=0.8),
        genre=_make_genre("people", "portrait"),
        aesthetic=0.7,
        faces=faces,
        image_gray=img,
    )
    assert result.hard_reject is False


def test_no_hard_reject_no_faces() -> None:
    """No faces means no eyes-closed gate."""
    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(face_exposure=-1.0),
        genre=_make_genre("general", "scenic"),
        aesthetic=0.7,
    )
    assert result.hard_reject is False


def test_hard_reject_multi_face_all_closed() -> None:
    """Multiple faces all with closed eyes should hard reject."""
    faces = [
        _make_face(left_eye=(80, 80), right_eye=(120, 80)),
        _make_face(left_eye=(80, 150), right_eye=(120, 150)),
    ]
    img = _closed_eyes_image()
    img[140:160, 70:90] = 165
    img[140:160, 110:130] = 165
    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(face_exposure=0.8),
        genre=_make_genre("people", "event"),
        aesthetic=0.7,
        faces=faces,
        image_gray=img,
    )
    assert result.hard_reject is True


def test_no_hard_reject_multi_face_one_open() -> None:
    """At least one face with open eyes should not trigger reject."""
    img = _closed_eyes_image()
    for r in range(70, 90):
        for c in range(70, 90):
            img[r, c] = 40 if (r + c) % 2 == 0 else 220
    for r in range(70, 90):
        for c in range(110, 130):
            img[r, c] = 40 if (r + c) % 2 == 0 else 220
    faces = [
        _make_face(left_eye=(80, 80), right_eye=(120, 80)),
        _make_face(left_eye=(80, 150), right_eye=(120, 150)),
    ]
    img[140:160, 70:90] = 165
    img[140:160, 110:130] = 165
    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(face_exposure=0.8),
        genre=_make_genre("people", "event"),
        aesthetic=0.7,
        faces=faces,
        image_gray=img,
    )
    assert result.hard_reject is False


# ---------------------------------------------------------------------------
# Backward compatibility — existing callers without faces/image_gray
# ---------------------------------------------------------------------------

def test_fuse_scores_backward_compatible_no_faces() -> None:
    """fuse_scores without faces/image_gray args must still work."""
    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=_make_genre(),
        aesthetic=0.65,
    )
    assert isinstance(result, FusionResult)
    assert 0.0 <= result.master_score <= 1.0
