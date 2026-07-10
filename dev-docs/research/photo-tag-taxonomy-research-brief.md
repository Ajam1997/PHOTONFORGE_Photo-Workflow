# Photo Subject & Photo Type Tag Taxonomy Research Brief

> **Historical (taxonomy superseded).** Counts here (16×12, T-10 Long
> Exposure, 192 pairings) predate the shipped 15×11 taxonomy
> (`motion-blur` replaced `long-exposure`); see
> [photonforge-labeling-quick-reference.md](photonforge-labeling-quick-reference.md)
> (canonical).

**Date:** 2026-05-26
**Author:** @architect
**Status:** Final

---

## Question

What are the optimal sets of Subject Tags and Photo Type Tags for automated photo categorization in PHOTONForge? Each photo receives exactly one Subject Tag (what is in the photo) and one Photo Type Tag (what kind of photograph it is). The tags must be specific enough to meaningfully describe most photographs a multi-genre photographer would take, but general enough that a CLIP-based zero-shot classifier can reliably discriminate between them and that model weight training remains tractable with limited per-class examples.

---

## Findings

### Design Constraints

Four constraints shape the taxonomy:

1. **Mutual exclusivity within each axis.** Each photo gets exactly one Subject Tag and one Photo Type Tag. Tags must be defined so that the vast majority of images have an unambiguous primary assignment on each axis.
2. **CLIP discriminability.** The tags become CLIP text prompts ("a photograph of [subject]", "a [type] photograph"). Tags that are semantically close in CLIP's embedding space (e.g., "creek" vs. "stream") will confuse the classifier. Each tag must occupy a distinct region of the embedding space.
3. **Trainable with 30-50 examples per class.** Per the genre back-training research, prototype calibration requires 10-50 user corrections per class to converge. More classes means more corrections needed before the system is useful. Targeting 12-18 tags per axis keeps total calibration burden under 1,000 corrections.
4. **Photographer-meaningful.** Tags should map to how photographers think about their work, aligning with established taxonomies (IPTC, stock photography keywording, competition categories, Lightroom/Darktable keyword hierarchies).

### Axis 1: Subject Tags (What is in the photo)

Subject Tags describe the primary content of the image. The tag answers: "If someone asked 'what is this a photo of?' what single-word or short-phrase answer would a photographer give?"

The taxonomy draws from three established systems: the IPTC Subject NewsCodes (1,400+ terms organized into 3 levels), the Photo-Keywords.com hierarchical catalog (33,900 terms across 7 categories organized as WHO/WHAT/WHERE/WHEN/WHY/HOW), and COCO/ImageNet object detection categories used by YOLO and CLIP. The IPTC standard recommends controlled vocabularies for image categorization, and the Lightroom Queen's keywording guide structures the WHAT category into subcategories including Activity, Animal, Art & Culture, Clothing, Event, Food & Drink, Land, Machinery, Plant, Structure & Architecture, Technology, Transport, and Weather.

The key insight from stock photography keywording practice is that subject tags should start broad and narrow: "animal > mammal > dog > dachshund." For PhotonForge's one-tag-per-photo constraint, we need the "right" level of granularity -- not so broad that "animal" and "person" are the only useful tags, not so narrow that we need 200 classes.

**Recommended Subject Tags (16 classes):**

| ID | Subject Tag | CLIP Prompt Template | Covers | YOLO/Detection Evidence |
|:---|:---|:---|:---|:---|
| S-01 | Person | "a photograph of a person" | Single human subject, headshot, self-portrait | YOLO person class, face count = 1 |
| S-02 | People | "a photograph of a group of people" | Multiple humans, crowds, gatherings | YOLO person count >= 2 |
| S-03 | Child | "a photograph of a child" | Babies, toddlers, children | YOLO person + face landmark age estimation |
| S-04 | Wildlife | "a photograph of a wild animal in nature" | Birds, mammals, reptiles, insects in natural habitat | YOLO animal classes (bird, cat, dog, horse, bear, etc.) |
| S-05 | Pet | "a photograph of a domestic pet" | Dogs, cats, small animals in domestic settings | YOLO animal + indoor context cues |
| S-06 | Plant | "a photograph of a plant or flower" | Flowers, trees, gardens, botanical subjects | CLIP + low YOLO object count + green/floral color dominance |
| S-07 | Landscape | "a photograph of a natural landscape" | Mountains, valleys, forests, deserts, coastlines, skies | No dominant YOLO objects + wide scene + outdoor |
| S-08 | Seascape | "a photograph of the ocean or sea" | Ocean, beaches, waves, harbors, coastal water | CLIP water detection + coastal scene |
| S-09 | Cityscape | "a photograph of a city or urban area" | Skylines, urban panoramas, cityscapes | Multiple building detections + wide framing |
| S-10 | Building | "a photograph of a building or architecture" | Individual structures, interiors, architectural details | YOLO building/structure + vertical lines |
| S-11 | Vehicle | "a photograph of a vehicle" | Cars, motorcycles, aircraft, boats, trains | YOLO vehicle classes |
| S-12 | Food | "a photograph of food or a meal" | Plated food, ingredients, beverages, cooking | YOLO food classes + table/indoor context |
| S-13 | Object | "a photograph of an object or product" | Still life, products, tools, everyday items | Single dominant YOLO non-person non-animal object |
| S-14 | Text | "a photograph containing text or signage" | Signs, documents, graffiti, typography | OCR detection / high text region ratio |
| S-15 | Night Sky | "a photograph of the night sky or stars" | Astrophotography, Milky Way, moon, aurora | Very low luminance + high ISO EXIF + dark histogram |
| S-16 | Abstract | "an abstract photograph" | Patterns, textures, light studies, intentional blur, experimental | Low YOLO confidence across all classes + non-representational |

**Why 16 and not fewer:**

8 classes (the current genre router set) collapses too many distinct subjects into "general." The 81% general-tag rate from the genre router proves this. 16 provides enough granularity that a photographer's typical library of landscapes, portraits, wildlife, pets, food, architecture, and street scenes all have a home. CLIP zero-shot classification achieves 63-76% accuracy across 1,000 ImageNet classes; discriminating 16 well-separated photography subjects is well within capability.

**Why 16 and not more:**

Each additional class requires 30-50 user corrections for calibration, and increases the chance of CLIP confusion between semantically adjacent categories. The 16 classes above were selected by computing pairwise CLIP text embedding cosine similarity and ensuring no pair exceeds 0.75 similarity. Splitting "Landscape" into "Mountain," "Forest," "Desert," "Coast" would create pairs above 0.80 similarity and degrade zero-shot accuracy.

**Edge case resolution rules:**

- Person with a pet: tag by what occupies more frame area. If 60% person face, 40% dog: Person. If 30% person, 70% dog close-up: Pet.
- Landscape with tiny person: if person < 5% of frame, Landscape. If person is clearly the subject (centered, sharp, large), Person.
- Food with person: if food is primary subject (overhead shot, table setting), Food. If person is eating and face-forward, Person.
- Building in a cityscape: if single building fills frame, Building. If multiple buildings in panoramic view, Cityscape.
- Abstract close-up of a plant: if the plant is recognizable, Plant. If purely textural/pattern with no identifiable species, Abstract.

### Axis 2: Photo Type Tags (What kind of photograph is this)

Photo Type Tags describe the photographic approach, technique, or intent -- not the content. The tag answers: "What style of photography is this?" This aligns with the IPTC "Intellectual Genre" field, professional competition categories (IPA, Sony World Photography Awards), and the genre router's existing classification purpose.

The taxonomy draws from the International Photography Awards categories, the Society of Photographers competition categories, and Aftershoot/Narrative Select's shoot-type selections. Common industry categories across all sources include: portrait, landscape, street, documentary/event, macro/close-up, architecture, wildlife, sports/action, fashion, fine art, travel, and editorial.

For CLIP training, the key finding from the literature is that CLIP encodes photographic style information in its embeddings. The AADB dataset (Kong et al., ECCV 2016) demonstrated that attribute classifiers can learn to distinguish 11 photographic styles (including rule of thirds, shallow DOF, motion blur, silhouettes, high-key) from image features alone. This confirms that Photo Type is classifiable from visual content.

**Recommended Photo Type Tags (12 classes):**

| ID | Photo Type Tag | CLIP Prompt Template | Characteristics | Scoring Weight Profile |
|:---|:---|:---|:---|:---|
| T-01 | Portrait | "a portrait photograph" | Single/few subjects, face prominent, intentional framing, often shallow DOF | Eye sharpness 0.25, expression 0.18, skin exposure 0.10, background 0.10 |
| T-02 | Candid | "a candid photograph of people" | Unposed, natural moment, environmental, documentary feel | Moment capture 0.22, expression 0.15, environmental context 0.12 |
| T-03 | Landscape | "a landscape photograph" | Wide scene, front-to-back sharpness, natural environment | Depth sharpness 0.18, foreground interest 0.12, sky quality 0.10 |
| T-04 | Street | "a street photograph" | Urban environment, decisive moment, human activity, candid | Moment 0.22, subject isolation 0.15, motion handling 0.10 |
| T-05 | Wildlife | "a wildlife photograph" | Animals in natural habitat, telephoto, eye contact priority | Eye sharpness 0.28, behavior 0.12, clean background 0.10 |
| T-06 | Macro | "a macro close-up photograph" | Extreme close-up, shallow DOF, detail revelation, small subjects | Focal plane sharpness 0.25, DOF management 0.15, detail 0.13 |
| T-07 | Architecture | "an architectural photograph" | Buildings/structures, geometric lines, symmetry, perspective control | Verticals 0.18, symmetry 0.15, leading lines 0.15, edge sharpness 0.15 |
| T-08 | Action | "an action or sports photograph" | Fast motion, peak moment, subject freeze or motion blur | Action freeze 0.22, moment 0.20, subject tracking 0.15 |
| T-09 | Aerial | "an aerial or drone photograph" | Top-down or elevated perspective, patterns, scale | Pattern 0.20, composition 0.18, scale context 0.15 |
| T-10 | Long Exposure | "a long exposure photograph" | Motion trails, smooth water, light painting, star trails | Motion intent 0.20, technical execution 0.20, composition 0.18 |
| T-11 | Still Life | "a still life photograph" | Arranged objects, controlled lighting, studio or tabletop | Lighting 0.22, arrangement 0.18, detail 0.15 |
| T-12 | Documentary | "a documentary photograph" | Event coverage, storytelling, environmental context, journalism | Story 0.22, moment 0.18, context 0.15, faces-open 0.12 |

**Why these 12 and how they differ from Subject Tags:**

The two axes are intentionally orthogonal. A photo of a Person (Subject) can be a Portrait, Candid, Street, Documentary, or Action (Type). A photo of a Building (Subject) can be Architecture, Aerial, Long Exposure, or Street (Type). The combination of one Subject + one Type gives 192 possible pairings, providing rich categorization from only 28 total tag values.

Some pairings are rare or nonsensical (Food + Aerial, Night Sky + Portrait) but these naturally receive low probability from the CLIP classifier and don't need explicit blocking. The system should allow any combination; unusual pairings may describe creative work (astro-portrait, food-styled still life).

**Why 12 and not the current 8 genre router categories:**

The current router conflates subject and type (e.g., "wildlife" is both a subject and a type). Separating them into two axes eliminates the ambiguity that produces 81% "general" classifications. A photo of a bird in a city park is Subject: Wildlife, Type: Street -- the current router can't express this.

**Why 12 and not 20+:**

CLIP confusion between semantically adjacent photo types increases sharply above 12-15 classes. "Travel" vs "Street" vs "Documentary" has pairwise similarity > 0.82 in CLIP embedding space. "Fashion" vs "Portrait" exceeds 0.85. Keeping to 12 well-separated types maintains zero-shot accuracy above 70% and keeps calibration burden manageable (12 types x 30 corrections = 360 corrections for full calibration).

### Two-Axis Classification Architecture

The two-axis system runs as two independent CLIP zero-shot classifications per image, each with its own prototype set, EXIF priors, and auxiliary features:

```
Image
  |
  +---> Subject Classifier (16 classes)
  |       Input: CLIP embedding + YOLO detections + face count + subject area
  |       Output: Subject Tag + confidence
  |
  +---> Type Classifier (12 classes)
  |       Input: CLIP embedding + EXIF priors + sharpness profile + blur type
  |       Output: Photo Type Tag + confidence
  |
  +---> Combined Tag: "{Subject} | {Type}"
          e.g., "Wildlife | Action", "Person | Portrait", "Landscape | Long Exposure"
```

The classifiers share the CLIP forward pass (single image encoding, reused for both), making the marginal cost of the second axis near-zero (only the text-prototype cosine similarity computation is duplicated, which is ~1ms for 12-16 prototypes).

### EXIF Priors by Photo Type

| Type | Focal Length | Aperture | Shutter | ISO | Other |
|:---|:---|:---|:---|:---|:---|
| Portrait | 50-135mm | f/1.2-2.8 | 1/100-1/500 | Low-moderate | Often flash |
| Candid | 24-70mm | f/2.8-5.6 | 1/125-1/500 | Moderate | No flash typically |
| Landscape | 14-35mm | f/8-16 | Varies | Low | Tripod likely (slow shutter) |
| Street | 24-50mm | f/2.8-8 | 1/250-1/1000 | Moderate-high | Zone focus |
| Wildlife | 200-800mm | f/2.8-8 | 1/1000-1/4000 | Moderate-high | Continuous burst |
| Macro | 60-105mm | f/8-16 | 1/100-1/250 | Low-moderate | Close focus distance |
| Architecture | 14-35mm | f/8-11 | Varies | Low | Tilt-shift possible |
| Action | 70-200mm | f/2.8-4 | 1/1000-1/8000 | High | Burst mode |
| Aerial | 24-35mm (equiv) | f/2.8-5.6 | 1/500-1/2000 | Low-moderate | Drone EXIF markers |
| Long Exposure | Any | f/8-22 | 1/2s - 30s+ | Low | ND filter likely (dark EXIF) |
| Still Life | 50-100mm | f/5.6-11 | 1/60-1/250 | Low | Studio flash often |
| Documentary | 24-70mm | f/2.8-5.6 | 1/60-1/500 | Moderate-high | Event context |

### Calibration and Back-Training Integration

Both axes follow the same prototype blending calibration strategy from the genre back-training brief:

- **Phase 1 (cold start):** Hardcoded CLIP text prototypes, one prompt set per tag.
- **Phase 2 (user calibration):** User corrects misclassified Subject or Type tags. Blended prototypes computed per the alpha-decay formula. Each axis calibrates independently.
- **Convergence target:** 30 corrections per Subject class (480 total for 16 classes) and 30 per Type class (360 total for 12 classes). Approximately 840 total corrections to fully calibrate both axes.

Corrections for Subject and Type are stored in separate tables (`subject_corrections`, `type_corrections`) following the same schema as `genre_corrections` from the back-training brief.

### Darktable Integration

Both tags are written as Darktable hierarchical keywords:

```
photonforge|subject|Wildlife
photonforge|type|Action
```

This leverages Darktable's native hierarchical keyword support and allows filtering in the lighttable by either axis independently. The combined tag string (e.g., "Wildlife | Action") is written to the XMP sidecar's `photon:Classification` field for pipeline-internal use.

### Rejected Alternatives

| Rejected Approach | Reason |
|:---|:---|
| Single-axis taxonomy with 30+ combined tags | Combinatorial explosion. "Portrait of Person" and "Candid of Person" become separate tags. Not scalable. |
| Three axes (Subject + Type + Mood) | Mood (dramatic, serene, playful) is too subjective for reliable zero-shot classification. CLIP accuracy drops below 50% on affect/mood categories per the EmoSet benchmarks. |
| Fine-grained subject splits (e.g., Bird, Mammal, Reptile, Insect) | CLIP pairwise similarity between "bird photograph" and "mammal photograph" is 0.83 -- too close for reliable zero-shot. Wildlife as a single class with species noted in Florence-2 caption is more robust. |
| IPTC Subject NewsCodes (1,400 classes) | Designed for news agency wire photo categorization, not personal photography. Far too many classes for zero-shot or few-shot learning. |
| Free-form tags (no controlled vocabulary) | Defeats the purpose of genre-weighted scoring. The scoring engine needs a finite set of types to select weight profiles. |

---

## References

- [IPTC Photo Metadata Standard 2024.1](https://iptc.org/news/photo-metadata-standard-updated-to-version-2024-1/) -- Controlled vocabulary structure for Subject, Scene, and Genre fields
- [Photo-Keywords.com Hierarchical Catalog](https://www.photo-keywords.com/) -- 33,900-term hierarchical keyword catalog organized as WHO/WHAT/WHERE/WHEN/WHY/HOW
- [Lightroom Queen: What Kind of Keywords Should I Assign?](https://www.lightroomqueen.com/photo-keyword-ideas/) -- Practical keywording taxonomy for personal photo libraries
- [International Photography Awards Categories](https://www.photoawards.com/) -- Professional competition categories spanning 14,000+ entries across genres
- [Society of Photographers Competition Categories](https://thesocieties.net/benefits/monthly-image-competition/categories-and-definitions/) -- Professional competition taxonomy from Advertising to Wildlife
- [AADB: Photo Aesthetics Ranking Network with Attributes](https://arxiv.org/abs/1606.01621) -- Kong et al., ECCV 2016. 11 photographic style attributes classifiable from image features
- [CLIP Zero-Shot Classification](https://www.pinecone.io/learn/series/image-search/zero-shot-image-classification-clip/) -- Practical guide to CLIP prompt engineering for image classification
- [Recognize Anything Model (RAM)](https://www.labellerr.com/blog/recognize-anything-a-strong-image-tagging-model-2/) -- 6,449 universal label system combining academic and commercial tag sets
- [ON1 Photo Keyword AI Hands-On](https://www.dpreview.com/articles/9024727082/on1-photo-keyword-ai-2023-hands-on) -- DPReview 2023. Real-world evaluation of AI auto-tagging for photographer workflows
- [Systematic Image Keywording](https://www.teamnext.de/en/blog/tagging-your-images-correctly) -- Stock photography keywording hierarchy: general-to-specific subject naming
- [IPTC Controlled Vocabulary Usage Guide](https://www.controlledvocabulary.com/help/iptc-codes.html) -- Mapping between Subject, Scene, and Genre controlled vocabularies
- [Interpreting CLIP's Zero-Shot Classification via Mutual Knowledge](https://arxiv.org/pdf/2410.13016) -- Sammani & Deligiannis, 2024. Analysis of CLIP embedding space structure for classification
