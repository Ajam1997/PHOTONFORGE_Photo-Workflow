"""Brute-force prototype search with exclusive class assignment.

Two-phase approach:
  Phase 1: Download all pool images once to a shared cache (slow, network-bound)
  Phase 2: Generate N random samplings from cache, calibrate in parallel (fast, CPU-bound)

Each image is assigned to exactly ONE subject and ONE type (no intra-axis overlap).
Cross-axis overlap (same image in a subject AND type folder) is allowed.
"""

from __future__ import annotations

import concurrent.futures
import csv
import json
import logging
import random
from pathlib import Path
from typing import Any

import click
import cv2
import numpy as np

logger = logging.getLogger(__name__)

SUBJECTS = [
    "person", "people", "child", "wildlife", "pet", "plant",
    "landscape", "seascape", "cityscape", "building", "vehicle",
    "food", "object", "text", "night-sky", "abstract",
]
PHOTO_TYPES = [
    "portrait", "candid", "landscape", "street", "wildlife", "macro",
    "architecture", "action", "aerial", "long-exposure", "still-life",
    "documentary",
]

_CLIP_INPUT_SIZE = 256

# ── Unsplash keyword → class mappings ──────────────────────────────────────

_UNSPLASH_SUBJECT_KEYWORDS: dict[str, list[str]] = {
    "person": ["portrait", "face", "man", "woman", "headshot"],
    "people": ["crowd", "group", "team", "gathering", "audience"],
    "child": ["child", "kid", "baby", "toddler", "infant"],
    "wildlife": ["wildlife", "wild animal", "bird", "deer", "eagle", "fox", "bear", "wolf"],
    "pet": ["dog", "cat", "puppy", "kitten", "pet"],
    "plant": ["flower", "plant", "botanical", "leaf", "blossom", "flora"],
    "landscape": ["mountain", "valley", "forest", "desert", "meadow", "field", "canyon", "hill"],
    "seascape": ["ocean", "sea", "beach", "coast", "wave", "shore", "reef", "tide"],
    "cityscape": ["skyline", "downtown", "metropolis", "city skyline"],
    "building": ["church", "bridge", "tower", "castle", "cathedral", "temple", "monument"],
    "vehicle": ["car", "truck", "motorcycle", "airplane", "boat", "train", "bicycle"],
    "food": ["food", "meal", "cooking", "dish", "cuisine", "breakfast", "dinner", "lunch"],
    "object": ["product", "tool", "device", "gadget", "furniture", "clock", "watch"],
    "text": ["sign", "typography", "graffiti", "neon sign", "letter", "billboard"],
    "night-sky": ["night sky", "stars", "milky way", "aurora", "astrophotography", "constellation"],
    "abstract": ["abstract art", "geometric", "fractal", "kaleidoscope", "psychedelic"],
}

_UNSPLASH_TYPE_KEYWORDS: dict[str, list[str]] = {
    "portrait": ["portrait", "headshot", "face", "model"],
    "candid": [
        "candid", "unposed", "natural moment", "spontaneous",
        "behind the scenes", "snapshot",
    ],
    "landscape": [
        "panorama", "vista", "scenic", "horizon",
        "sunset landscape", "sunrise landscape",
    ],
    "street": ["street photography", "city life", "pedestrian", "urban life"],
    "wildlife": ["wildlife photography", "bird photography", "safari", "nature wildlife"],
    "macro": ["macro", "microscopic", "extreme close-up", "insect macro", "water drop"],
    "architecture": ["architecture", "interior design", "modern building", "facade"],
    "action": ["action", "sport", "running", "jumping", "motion blur", "athlete"],
    "aerial": ["aerial", "drone", "bird's eye", "top down", "satellite view"],
    "long-exposure": [
        "long exposure", "light trail", "smooth water",
        "light painting", "motion blur night",
    ],
    "still-life": ["still life", "flat lay", "arrangement", "tabletop", "product photography"],
    "documentary": ["documentary", "journalism", "reportage", "protest", "ceremony"],
}

_COCO_SUBJECT_MAP: dict[int, str] = {
    1: "person", 2: "vehicle", 3: "vehicle", 4: "vehicle", 5: "vehicle",
    6: "vehicle", 7: "vehicle", 8: "vehicle", 9: "vehicle",
    15: "wildlife", 16: "pet", 17: "pet",
    18: "wildlife", 19: "wildlife", 20: "wildlife", 21: "wildlife",
    22: "wildlife", 23: "wildlife", 24: "wildlife",
    46: "food", 47: "food", 48: "food", 49: "food", 50: "food",
    51: "food", 52: "food", 53: "food", 54: "food", 55: "food",
    59: "plant", 75: "plant",
    56: "object", 57: "object", 60: "object", 61: "object",
    62: "object", 63: "object", 64: "object", 67: "object",
    73: "object", 74: "object",
}


def _download_file(url: str, dest: Path) -> bool:
    """Download a large file (datasets, zips)."""
    if dest.exists():
        return True
    try:
        import urllib.request
        logger.info("  -> %s", dest.name)
        urllib.request.urlretrieve(url, str(dest))
        size_mb = dest.stat().st_size / 1e6
        logger.info("  -> %.1f MB", size_mb)
        return True
    except Exception as e:
        logger.error("Download failed: %s", e)
        return False


def _download_image(url: str, dest: Path, timeout: int = 15) -> bool:
    if dest.exists():
        return True
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "PHOTONForge/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dest.write_bytes(resp.read())
        return True
    except Exception:
        return False


# ── Phase 1: Build pools and download everything ──────────────────────────

def _build_unsplash_pools(
    cache_dir: Path, image_cache: Path,
) -> tuple[dict[str, list[Path]], dict[str, list[Path]]]:
    """Build exclusive pools and download all Unsplash images to shared cache."""
    import zipfile

    lite_dir = cache_dir / "unsplash_lite"
    lite_dir.mkdir(parents=True, exist_ok=True)

    # Download Unsplash Lite if not cached
    zip_path = lite_dir / "unsplash-lite.zip"
    if not any(lite_dir.glob("photos.*000")):
        if not zip_path.exists():
            _UNSPLASH_URL = (
                "https://unsplash-datasets.s3.amazonaws.com/lite/latest/"
                "unsplash-research-dataset-lite-latest.zip"
            )
            logger.info("Downloading Unsplash Lite (~500MB)...")
            _download_file(_UNSPLASH_URL, zip_path)

        if zip_path.exists():
            logger.info("Extracting Unsplash Lite...")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(lite_dir)

    photos_file = None
    keywords_file = None
    for name in ("photos.tsv000", "photos.csv000"):
        candidate = lite_dir / name
        if candidate.exists():
            photos_file = candidate
            keywords_file = candidate.parent / candidate.name.replace("photos", "keywords")
            break
    if not photos_file:
        for pattern in ("photos.tsv000", "photos.csv000"):
            for candidate in lite_dir.rglob(pattern):
                photos_file = candidate
                keywords_file = candidate.parent / candidate.name.replace("photos", "keywords")
                break
            if photos_file:
                break

    if not photos_file or not photos_file.exists():
        logger.warning("Unsplash data not found")
        return {s: [] for s in SUBJECTS}, {t: [] for t in PHOTO_TYPES}

    # Build keyword index
    logger.info("Indexing Unsplash keywords...")
    photo_keywords: dict[str, set[str]] = {}
    if keywords_file and keywords_file.exists():
        with keywords_file.open(encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                kw = (row.get("keyword") or "").lower().strip()
                pid = row.get("photo_id", "").strip()
                if kw and pid:
                    photo_keywords.setdefault(pid, set()).add(kw)

    # Build URL index
    photo_urls: dict[str, str] = {}
    with photos_file.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            pid = row.get("photo_id", "").strip()
            url = row.get("photo_image_url", "").strip()
            if pid and url:
                photo_urls[pid] = url + "?w=640&q=80"

    logger.info("  %d photos indexed", len(photo_urls))

    # Exclusive assignment
    subj_pids: dict[str, list[str]] = {s: [] for s in SUBJECTS}
    type_pids: dict[str, list[str]] = {t: [] for t in PHOTO_TYPES}

    for pid, keywords in photo_keywords.items():
        if pid not in photo_urls:
            continue

        best_subj, best_ss = None, 0
        for subj, kws in _UNSPLASH_SUBJECT_KEYWORDS.items():
            score = sum(1 for kw in kws if kw in keywords)
            if score > best_ss:
                best_ss = score
                best_subj = subj

        best_type, best_ts = None, 0
        for ptype, kws in _UNSPLASH_TYPE_KEYWORDS.items():
            score = sum(1 for kw in kws if kw in keywords)
            if score > best_ts:
                best_ts = score
                best_type = ptype

        if best_subj and best_ss > 0:
            subj_pids[best_subj].append(pid)
        if best_type and best_ts > 0:
            type_pids[best_type].append(pid)

    # Download all pool images to shared cache
    unsplash_cache = image_cache / "unsplash"
    unsplash_cache.mkdir(parents=True, exist_ok=True)

    all_pids = set()
    for pids in subj_pids.values():
        all_pids.update(pids)
    for pids in type_pids.values():
        all_pids.update(pids)

    # Cap downloads — we only need ~100 per class max across 10 sets
    capped_pids: set[str] = set()
    for label in SUBJECTS:
        capped_pids.update(subj_pids[label][:150])
    for label in PHOTO_TYPES:
        capped_pids.update(type_pids[label][:150])

    logger.info("Downloading %d Unsplash images to shared cache...", len(capped_pids))
    downloaded = 0
    failed = 0
    for pid in capped_pids:
        dest = unsplash_cache / f"{pid}.jpg"
        url = photo_urls.get(pid)
        if not url:
            continue
        if _download_image(url, dest):
            downloaded += 1
        else:
            failed += 1
        if (downloaded + failed) % 100 == 0:
            logger.info("  ... %d/%d downloaded", downloaded, downloaded + failed)

    logger.info("  Downloaded %d, failed %d", downloaded, failed)

    # Convert pid lists to Path lists (only include successfully downloaded)
    subj_pools: dict[str, list[Path]] = {}
    type_pools: dict[str, list[Path]] = {}
    for label in SUBJECTS:
        subj_pools[label] = [
            unsplash_cache / f"{pid}.jpg"
            for pid in subj_pids[label][:150]
            if (unsplash_cache / f"{pid}.jpg").exists()
        ]
        logger.info("  subject/%-12s %d available", label, len(subj_pools[label]))
    for label in PHOTO_TYPES:
        type_pools[label] = [
            unsplash_cache / f"{pid}.jpg"
            for pid in type_pids[label][:150]
            if (unsplash_cache / f"{pid}.jpg").exists()
        ]
        logger.info("  type/%-14s %d available", label, len(type_pools[label]))

    return subj_pools, type_pools


def _build_coco_pools(
    cache_dir: Path,
) -> tuple[dict[str, list[Path]], dict[str, list[Path]]]:
    """Build exclusive COCO pools, downloading if needed."""
    import zipfile

    coco_dir = cache_dir / "coco"
    coco_dir.mkdir(parents=True, exist_ok=True)
    ann_json = coco_dir / "annotations" / "instances_val2017.json"
    images_dir = coco_dir / "val2017"

    # Download annotations
    if not ann_json.exists():
        ann_zip = coco_dir / "annotations_trainval2017.zip"
        if not ann_zip.exists():
            logger.info("Downloading COCO annotations (~250MB)...")
            _download_file(
                "http://images.cocodataset.org/annotations/annotations_trainval2017.zip",
                ann_zip,
            )
        if ann_zip.exists():
            logger.info("Extracting COCO annotations...")
            with zipfile.ZipFile(ann_zip, "r") as zf:
                zf.extractall(coco_dir)

    # Download images
    if not images_dir.exists():
        img_zip = coco_dir / "val2017.zip"
        if not img_zip.exists():
            logger.info("Downloading COCO val2017 images (~800MB)...")
            _download_file(
                "http://images.cocodataset.org/zips/val2017.zip",
                img_zip,
            )
        if img_zip.exists():
            logger.info("Extracting COCO val2017 images...")
            with zipfile.ZipFile(img_zip, "r") as zf:
                zf.extractall(coco_dir)

    if not ann_json.exists() or not images_dir.exists():
        return {s: [] for s in SUBJECTS}, {t: [] for t in PHOTO_TYPES}

    logger.info("Parsing COCO annotations...")
    with ann_json.open(encoding="utf-8") as f:
        coco = json.load(f)

    id_to_file: dict[int, str] = {img["id"]: img["file_name"] for img in coco["images"]}

    image_subject_counts: dict[int, dict[str, int]] = {}
    image_person_count: dict[int, int] = {}
    image_sport: dict[int, bool] = {}
    sport_cats = {32, 34, 35, 36, 37, 38}

    for ann in coco["annotations"]:
        cat_id = ann["category_id"]
        img_id = ann["image_id"]
        if cat_id == 1:
            image_person_count[img_id] = image_person_count.get(img_id, 0) + 1
        if cat_id in sport_cats:
            image_sport[img_id] = True
        subj = _COCO_SUBJECT_MAP.get(cat_id)
        if subj:
            counts = image_subject_counts.setdefault(img_id, {})
            counts[subj] = counts.get(subj, 0) + 1

    subj_pools: dict[str, list[Path]] = {s: [] for s in SUBJECTS}
    type_pools: dict[str, list[Path]] = {t: [] for t in PHOTO_TYPES}

    for img_id, counts in image_subject_counts.items():
        fname = id_to_file.get(img_id)
        if not fname:
            continue
        fpath = images_dir / fname
        if not fpath.exists():
            continue

        if "person" in counts:
            pc = image_person_count.get(img_id, 0)
            best_subj = "people" if pc >= 2 else "person"
            other = {k: v for k, v in counts.items() if k != "person"}
            if other and max(other.values()) > counts.get("person", 0):
                best_subj = max(other, key=other.get)
        else:
            best_subj = max(counts, key=counts.get)

        subj_pools[best_subj].append(fpath)

        pc = image_person_count.get(img_id, 0)
        if pc == 1:
            type_pools["portrait"].append(fpath)
        elif pc >= 3:
            type_pools["documentary"].append(fpath)
        if image_sport.get(img_id):
            type_pools["action"].append(fpath)

    for s in SUBJECTS:
        if subj_pools[s]:
            logger.info("  COCO subject/%-12s %d", s, len(subj_pools[s]))
    for t in PHOTO_TYPES:
        if type_pools[t]:
            logger.info("  COCO type/%-14s %d", t, len(type_pools[t]))

    return subj_pools, type_pools


def _build_oxford_pool(cache_dir: Path) -> list[Path]:
    import tarfile

    pet_dir = cache_dir / "oxford_pet"
    pet_dir.mkdir(parents=True, exist_ok=True)
    images_dir = pet_dir / "images"

    if not images_dir.exists():
        tar_path = pet_dir / "images.tar.gz"
        if not tar_path.exists():
            logger.info("Downloading Oxford-IIIT Pet (~800MB)...")
            _download_file(
                "https://www.robots.ox.ac.uk/~vgg/data/pets/data/images.tar.gz",
                tar_path,
            )
        if tar_path.exists():
            logger.info("Extracting Oxford-IIIT Pet...")
            with tarfile.open(tar_path, "r:gz") as tf:
                tf.extractall(pet_dir)

    if not images_dir.exists():
        for p in pet_dir.rglob("*.jpg"):
            images_dir = p.parent
            break
    if not images_dir.exists():
        return []
    return sorted(images_dir.glob("*.jpg"))


# ── Phase 2: Sample, embed, calibrate (parallelizable) ───────────────────

def _embed_image(image_path: Path, session: Any) -> np.ndarray | None:
    img = cv2.imread(str(image_path))
    if img is None:
        return None
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, (_CLIP_INPUT_SIZE, _CLIP_INPUT_SIZE))
    img = img.astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))
    img = np.expand_dims(img, axis=0)

    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: img})
    emb = outputs[0].flatten()
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    return emb.astype(np.float32)


def _precompute_all_embeddings(
    subj_pools: dict[str, list[Path]],
    type_pools: dict[str, list[Path]],
    clip_session: Any,
) -> dict[str, np.ndarray]:
    """Embed every unique image once. Returns path_str → embedding."""
    all_paths: set[str] = set()
    for paths in subj_pools.values():
        all_paths.update(str(p) for p in paths)
    for paths in type_pools.values():
        all_paths.update(str(p) for p in paths)

    logger.info("Pre-computing CLIP embeddings for %d unique images...", len(all_paths))
    embeddings: dict[str, np.ndarray] = {}
    done = 0
    for path_str in all_paths:
        emb = _embed_image(Path(path_str), clip_session)
        if emb is not None:
            embeddings[path_str] = emb
        done += 1
        if done % 200 == 0:
            logger.info("  ... %d/%d embedded", done, len(all_paths))

    logger.info("  Embedded %d/%d images", len(embeddings), len(all_paths))
    return embeddings


def _calibrate_from_embeddings(
    seed: int,
    subj_pools: dict[str, list[Path]],
    type_pools: dict[str, list[Path]],
    all_embeddings: dict[str, np.ndarray],
    text_protos: np.ndarray | None,
    blend_alpha: float,
    samples_per_class: int,
) -> tuple[int, np.ndarray, dict[str, int]]:
    """Sample a random subset, build prototypes from precomputed embeddings."""
    rng = random.Random(seed)
    counts: dict[str, int] = {}
    prototypes: dict[str, np.ndarray] = {}

    for axis, labels, pools in [
        ("subjects", SUBJECTS, subj_pools),
        ("types", PHOTO_TYPES, type_pools),
    ]:
        for label in labels:
            pool = list(pools.get(label, []))
            rng.shuffle(pool)

            embeddings = []
            for p in pool:
                if len(embeddings) >= samples_per_class:
                    break
                emb = all_embeddings.get(str(p))
                if emb is not None:
                    embeddings.append(emb)

            key = f"{axis}/{label}"
            if not embeddings:
                prototypes[key] = np.zeros(512, dtype=np.float32)
                counts[key] = 0
                continue

            mean_emb = np.mean(embeddings, axis=0)
            norm = np.linalg.norm(mean_emb)
            if norm > 0:
                mean_emb = mean_emb / norm
            prototypes[key] = mean_emb.astype(np.float32)
            counts[key] = len(embeddings)

    # Blend with text
    if text_protos is not None and blend_alpha < 1.0:
        for i, label in enumerate(SUBJECTS):
            key = f"subjects/{label}"
            blended = blend_alpha * prototypes[key] + (1.0 - blend_alpha) * text_protos[i]
            norm = np.linalg.norm(blended)
            if norm > 0:
                blended = blended / norm
            prototypes[key] = blended.astype(np.float32)

        for i, label in enumerate(PHOTO_TYPES):
            key = f"types/{label}"
            blended = blend_alpha * prototypes[key] + (1.0 - blend_alpha) * text_protos[16 + i]
            norm = np.linalg.norm(blended)
            if norm > 0:
                blended = blended / norm
            prototypes[key] = blended.astype(np.float32)

    # Stack
    rows = []
    for label in SUBJECTS:
        rows.append(prototypes[f"subjects/{label}"])
    for label in PHOTO_TYPES:
        rows.append(prototypes[f"types/{label}"])

    return seed, np.array(rows, dtype=np.float32), counts


def _score_prototypes(protos: np.ndarray) -> tuple[float, float, str, str]:
    max_subj, worst_subj = 0.0, ""
    for i in range(16):
        for j in range(i + 1, 16):
            sim = float(protos[i] @ protos[j])
            if sim > max_subj:
                max_subj = sim
                worst_subj = f"{SUBJECTS[i]}-{SUBJECTS[j]}"

    max_type, worst_type = 0.0, ""
    for i in range(12):
        for j in range(i + 1, 12):
            sim = float(protos[16 + i] @ protos[16 + j])
            if sim > max_type:
                max_type = sim
                worst_type = f"{PHOTO_TYPES[i]}-{PHOTO_TYPES[j]}"

    return max_subj, max_type, worst_subj, worst_type


def _generate_text_prototypes() -> np.ndarray:
    import open_clip
    import torch

    logger.info("Generating text prototypes for blending...")
    model, _, _ = open_clip.create_model_and_transforms(
        "MobileCLIP-S2", pretrained="datacompdr"
    )
    model.eval()
    tokenizer = open_clip.get_tokenizer("MobileCLIP-S2")

    SUBJ_T = [
        "itap of a {}", "a bad photo of the {}", "a origami {}",
        "a photo of the large {}", "a {} in a video game",
        "art of the {}", "a photo of the small {}",
    ]
    TYPE_T = [
        "a {} photograph", "an example of {} photography",
        "a professional {} photo", "a {} style photograph",
        "a stunning {} photograph", "a beautiful {} photo",
        "an award-winning {} photograph",
    ]
    SUBJ_F = {
        "person": "person", "people": "group of people", "child": "child",
        "wildlife": "wild animal in nature", "pet": "domestic pet",
        "plant": "plant or flower", "landscape": "natural landscape",
        "seascape": "ocean or sea", "cityscape": "city or urban area",
        "building": "building or architecture", "vehicle": "vehicle",
        "food": "food or meal", "object": "object or product",
        "text": "text or signage", "night-sky": "night sky or stars",
        "abstract": "abstract pattern",
    }
    TYPE_F = {
        "portrait": "portrait", "candid": "candid", "landscape": "landscape",
        "street": "street", "wildlife": "wildlife", "macro": "macro close-up",
        "architecture": "architectural", "action": "action or sports",
        "aerial": "aerial or drone", "long-exposure": "long exposure",
        "still-life": "still life", "documentary": "documentary",
    }

    embs = {}
    with torch.no_grad():
        for s in SUBJECTS:
            prompts = [t.format(SUBJ_F[s]) for t in SUBJ_T]
            feats = model.encode_text(tokenizer(prompts))
            feats /= feats.norm(dim=-1, keepdim=True)
            m = feats.mean(dim=0)
            m /= m.norm()
            embs[s] = m.cpu().numpy()
        for t in PHOTO_TYPES:
            prompts = [t_.format(TYPE_F[t]) for t_ in TYPE_T]
            feats = model.encode_text(tokenizer(prompts))
            feats /= feats.norm(dim=-1, keepdim=True)
            m = feats.mean(dim=0)
            m /= m.norm()
            embs[t] = m.cpu().numpy()

    return np.stack([embs[g] for g in SUBJECTS + PHOTO_TYPES]).astype(np.float32)


@click.command()
@click.option("--cache", type=click.Path(path_type=Path),
              default=Path("training_data/.cache"))
@click.option("--output", type=click.Path(path_type=Path),
              default=Path("training_data/bruteforce"))
@click.option("--models-dir", type=click.Path(exists=True, path_type=Path),
              default=Path("models"))
@click.option("--num-sets", type=int, default=10)
@click.option("--samples-per-class", type=int, default=32)
@click.option("--blend", type=float, default=0.7)
@click.option("--install-best", is_flag=True)
@click.option("--workers", type=int, default=4,
              help="Parallel workers for calibration phase")
def main(
    cache: Path, output: Path, models_dir: Path,
    num_sets: int, samples_per_class: int, blend: float,
    install_best: bool, workers: int,
) -> None:
    """Generate N exclusive training sets, calibrate each, pick the best."""
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    output.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: Download all pool images once ──
    image_cache = output / ".image_cache"
    image_cache.mkdir(parents=True, exist_ok=True)

    logger.info("Phase 1: Building pools and downloading images...")
    unsplash_subj, unsplash_type = _build_unsplash_pools(cache, image_cache)
    coco_subj, coco_type = _build_coco_pools(cache)
    oxford_pet = _build_oxford_pool(cache)
    logger.info("Oxford Pet pool: %d images", len(oxford_pet))

    # Merge pools: Unsplash + COCO + Oxford
    merged_subj: dict[str, list[Path]] = {s: [] for s in SUBJECTS}
    merged_type: dict[str, list[Path]] = {t: [] for t in PHOTO_TYPES}

    for s in SUBJECTS:
        merged_subj[s].extend(unsplash_subj.get(s, []))
        merged_subj[s].extend(coco_subj.get(s, []))
        if s == "pet":
            merged_subj[s].extend(oxford_pet[:150])
    for t in PHOTO_TYPES:
        merged_type[t].extend(unsplash_type.get(t, []))
        merged_type[t].extend(coco_type.get(t, []))

    # Generate text prototypes
    text_protos = None
    if blend < 1.0:
        text_protos = _generate_text_prototypes()

    # ── Phase 1.5: Pre-compute ALL embeddings once ──
    logger.info("\nPhase 1.5: Pre-computing CLIP embeddings...")
    import onnxruntime as ort
    vision_path = models_dir / "mobileclip_s2_int8" / "vision_encoder.onnx"
    clip_session = ort.InferenceSession(str(vision_path), providers=["CPUExecutionProvider"])

    all_embeddings = _precompute_all_embeddings(merged_subj, merged_type, clip_session)

    # ── Phase 2: Calibrate N sets in parallel ──
    logger.info("\nPhase 2: Calibrating %d sets (parallel)...", num_sets)
    seeds = [42 + i * 7 for i in range(num_sets)]

    results: list[tuple[int, float, float, str, str, np.ndarray]] = []

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _calibrate_from_embeddings,
                seed, merged_subj, merged_type,
                all_embeddings, text_protos, blend, samples_per_class,
            ): seed
            for seed in seeds
        }

        for future in concurrent.futures.as_completed(futures):
            seed = futures[future]
            try:
                ret_seed, protos, counts = future.result()
                max_subj, max_type, worst_subj, worst_type = _score_prototypes(protos)
                results.append((ret_seed, max_subj, max_type, worst_subj, worst_type, protos))
                logger.info(
                    "  Seed %d: max_subj=%.4f (%s), max_type=%.4f (%s)",
                    ret_seed, max_subj, worst_subj, max_type, worst_type,
                )
                np.save(str(output / f"protos_seed{ret_seed:03d}.npy"), protos)
            except Exception as e:
                logger.error("  Seed %d failed: %s", seed, e)

    # Rank
    results.sort(key=lambda r: max(r[1], r[2]))

    click.echo("\n" + "=" * 70)
    click.echo("RESULTS (sorted by best worst-case overlap)")
    click.echo("=" * 70)
    header = (
        f"{'Rank':>4s}  {'Seed':>4s}  {'MaxSubj':>8s}"
        f"  {'WorstSubjPair':>25s}  {'MaxType':>8s}  {'WorstTypePair':>25s}"
    )
    click.echo(header)
    for rank, (seed, ms, mt, ws, wt, _) in enumerate(results, 1):
        marker = " <-- BEST" if rank == 1 else ""
        click.echo(f"{rank:4d}  {seed:4d}  {ms:8.4f}  {ws:>25s}  {mt:8.4f}  {wt:>25s}{marker}")

    best_seed, best_ms, best_mt, best_ws, best_wt, best_protos = results[0]
    click.echo(f"\nBest: seed={best_seed}, max_overlap={max(best_ms, best_mt):.4f}")

    if install_best:
        dest = models_dir / "genre_prototypes.npy"
        np.save(str(dest), best_protos)
        click.echo(f"Installed to {dest}")
    else:
        click.echo(f"Run with --install-best to copy to {models_dir / 'genre_prototypes.npy'}")


if __name__ == "__main__":
    main()
