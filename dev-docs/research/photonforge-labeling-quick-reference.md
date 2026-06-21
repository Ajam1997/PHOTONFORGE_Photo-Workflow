# PHOTONForge Photo Labeling Quick Reference

**Version:** 2.2 | **Date:** 2026-06-20

Use this guide when manually labeling training data or correcting auto-classifications. Every photo gets **exactly one Subject Tag** and **exactly one Photo Type Tag**.

The taxonomy is **15 Subjects × 11 Photo Types**, matching the runtime router in `src/photo_workflow/genre_router.py` (`SUBJECTS` / `PHOTO_TYPES`). The two axes are fully orthogonal — no label appears on both.

> **v2.2 taxonomy change:** Photo Type `long-exposure` renamed to **`motion-blur`** (T-10). The tag now names the *aesthetic effect* (visible blur from movement) rather than the *technical method* (a long shutter). Scope is unchanged in practice — smooth water, light trails, star trails, cloud streaks, light painting, intentional panning blur — but the framing is effect-first, so a shot reads as `motion-blur` whenever movement is rendered as blur on purpose, regardless of the exact shutter speed used to get there. Accidental camera shake is still **not** a style (it's a reject candidate).
>
> **v2.1 taxonomy change:** Subjects revised 13 → 15 — two dedicated subjects split out of the structure/nature buckets:
> - **`monument`** (S-14): statues, memorials, landmarks, fountains, sculptures, clock towers — *commemorative/symbolic* structures, split out of `building`.
> - **`waterfall`** (S-15): cascades and falls as the primary subject, split out of `landscape`/`seascape` (these are almost always shot for motion blur).
>
> **v2.0 taxonomy change:** Subjects revised 16 → 13, Photo Types revised 12 → 11, and the two axes became fully orthogonal.
> - **Subjects:** `person`/`child` merged into **`people`** (count/age is not a content axis — the Type axis carries posed-vs-candid); `text` folded into **`object`**; `night-sky` absorbed by a broader **`sky`** tag that also covers daytime clouds/sunsets. `abstract` is now a tightly-bounded catch-all (<5%), not a dumping ground.
> - **Types:** removed `wildlife` (it's a *subject*, not a technique — wild-animal shots take action/candid/macro/documentary); renamed `landscape` → **`scenic`** so no string collides with the `landscape` subject.

---

## Decision Flow: Subject Tag (What is in the photo?)

```
Is a human the main subject (any count, any age)? ─────── S-01 People

Is there an animal?
├─ YES
│   ├─ Wild animal in natural habitat? ────────────────── S-03 Wildlife
│   └─ Domestic pet in home/yard setting? ─────────────── S-02 Pet

Is the main subject a plant/flower? ───────────────────── S-04 Plant

Is the main subject a waterfall / cascade / falls? ─────── S-15 Waterfall

Is the sky the subject (sunset, clouds, stars, Milky Way,
  aurora, moon, wing-over-clouds aerials)? ───────────── S-07 Sky

Is it a wide natural scene (no dominant subject)?
├─ YES
│   ├─ Ocean, beach, waves, coastal water? ────────────── S-06 Seascape
│   └─ Mountains, forests, fields, desert, rock formations? S-05 Landscape

Is the main subject a structure or urban scene?
├─ YES
│   ├─ A statue / memorial / landmark / fountain
│   │    (commemorative, not a functional building)? ──── S-14 Monument
│   ├─ Multiple buildings, skyline, panorama? ─────────── S-08 Cityscape
│   └─ Single building, interior, detail? ─────────────── S-09 Building

Is the main subject a vehicle? ────────────────────────── S-10 Vehicle
Is the main subject food/drink? ───────────────────────── S-11 Food
Is the main subject a specific man-made item, incl.
  signs / text / products? ────────────────────────────── S-12 Object
Is it non-representational (patterns, textures,
  light studies, intentional abstraction)? ────────────── S-13 Abstract
```

When a photo is taken **from a plane/drone**, tag the Subject by *what's below*: land → `landscape`, town → `cityscape`, water → `seascape`, just wing+clouds/sky → `sky`. The Type axis carries `aerial`.

---

## Decision Flow: Photo Type Tag (What kind of photo is it?)

```
Was it shot from a drone or elevated position? ─── T-09 Aerial

Is movement intentionally rendered as blur
  (smooth water, light trails, star trails,
   cloud streaks, panning)? ────────────────────── T-10 Motion Blur

Is it an extreme close-up of a small subject
  (insects, flowers, textures at macro scale)? ──── T-06 Macro

Is it a controlled/arranged studio setup? ──────── T-11 Still Life

Is there fast action / sports / peak motion? ───── T-08 Action

Is the subject a building/structure with
  geometric emphasis? ──────────────────────────── T-07 Architecture

Is it a wide natural scene emphasizing
  environment over subject? ────────────────────── T-03 Scenic

Is it urban with decisive moment / human
  activity / street life? ─────────────────────── T-04 Street

Is it event coverage / journalism /
  storytelling context? ───────────────────────── T-12 Documentary

Is there a person posed or intentionally
  framed as the subject? ─────────────────────── T-01 Portrait

Is there a person captured naturally /
  unposed / in-the-moment? ───────────────────── T-02 Candid
```

---

## Subject Tag Reference Table

| ID | Tag | Assign When | Do NOT Assign When |
|:---|:---|:---|:---|
| S-01 | People | Any human is the clear subject — solo, couple, group, child, or crowd. Headshots, environmental portraits, group shots, candids. | A person is tiny/incidental in a landscape (use S-05). The shot is really about a vehicle/building the person stands near. |
| S-02 | Pet | Domestic animal in home, yard, or domestic context. Dogs, cats, hamsters, aquarium fish. | Stray/feral animals in wild setting (use S-03). |
| S-03 | Wildlife | Wild animal in nature. Birds in sky, deer in forest, insects on flowers, fish underwater. | Domestic pet in home (use S-02). Animal is tiny in a landscape (use S-05). |
| S-04 | Plant | Flowers, trees, gardens, botanical close-ups. Plant is the clear subject. | Plant is background in a landscape (use S-05). Plant is part of food styling (use S-11). |
| S-05 | Landscape | Natural wide scene. Mountains, valleys, forests, deserts, fields, **rock formations**, dramatic terrain. No single dominant subject. | Sky is the hero (use S-07). Ocean/coastal is primary (use S-06). Urban scene (use S-08). A person/animal is clearly the subject. |
| S-06 | Seascape | Ocean, sea, waves, beaches, harbors, coastal water dominates. | Lake in a mountain scene (use S-05 if mountains dominate). Boat is the subject (use S-10). |
| S-07 | Sky | The sky **is** the subject: sunsets, dramatic clouds, stars, Milky Way, aurora, moon, meteor showers; also aerials that are mostly wing + clouds. | Land/water occupies most of the frame with sky as backdrop (use S-05/S-06). Night cityscape with lights (use S-08). |
| S-08 | Cityscape | Urban panorama, skyline, multiple buildings, city overlook. Wide urban scene. | Single building fills frame (use S-09). Street-level with people as focus (use S-01). |
| S-09 | Building | Single structure, architectural detail, interior, façade, bridge, monument. | Multiple buildings in a skyline (use S-08). Building is background behind a person (use S-01). |
| S-10 | Vehicle | Car, motorcycle, aircraft, boat, train, bicycle is the clear subject. | Vehicle is incidental in a street scene. Boat as tiny element in seascape (use S-06). |
| S-11 | Food | Plated meal, ingredients, beverages, cooking process. Food is the subject. | Person eating where face is the focus (use S-01). Restaurant interior where space is the subject (use S-09). |
| S-12 | Object | Specific man-made item: tools, products, instruments, household items, still-life arrangements — **and signs, menus, graffiti, typography, documents**. | Object is food (use S-11). Object is a vehicle (use S-10). |
| S-13 | Abstract | Patterns, textures, light studies, intentional blur, reflections, experimental, non-representational or unidentifiable subject. **Hard cap ~5% — only when no other tag fits.** | Anything identifiable. A macro of a flower (use S-04). Bokeh behind a person (use S-01). A recognizable aerial of land (use S-05). |
| S-14 | Monument | A commemorative or symbolic structure is the subject: statue, memorial, landmark, fountain, obelisk, sculpture, clock tower, historic marker. | A functional building/façade/interior (use S-09). The monument is a small element in a wider skyline (use S-08) or street scene (tag by what dominates). |
| S-15 | Waterfall | A waterfall, cascade, or falls is the clear subject — usually shot for motion blur (smooth water). | Water is a minor element in a wider land scene (use S-05). Ocean waves / coastal water (use S-06). A calm river/lake in a vista (use S-05/S-06). |

---

## Photo Type Reference Table

| ID | Tag | Assign When | Do NOT Assign When |
|:---|:---|:---|:---|
| T-01 | Portrait | Person is posed or intentionally framed. Headshot, environmental portrait, fashion, formal. | Person is unposed/candid (use T-02). Multiple people at an event (use T-12). |
| T-02 | Candid | Person captured naturally, unposed, in-the-moment. Street candid, behind-the-scenes, daily life. | Person is clearly posing (use T-01). It's event coverage (use T-12). Urban scene without people focus (use T-04). |
| T-03 | Scenic | Wide natural scene. Emphasis on environment, depth, atmosphere. Scenic vistas, nature panoramas. | Urban scene (use T-04 or T-07). A specific animal is the subject (tag by technique — T-08 action, T-02 candid, T-06 macro). |
| T-04 | Street | Urban environment. Decisive moment, human activity, city life, found compositions in public spaces. | Rural/nature scene (use T-03). Formal event (use T-12). Architecture with no human element (use T-07). |
| T-06 | Macro | Extreme close-up. Magnification reveals detail invisible to naked eye. Insects, water drops, textures, electronics. | Regular close-up portrait (use T-01). Close-up of food (use T-11 if styled). |
| T-07 | Architecture | Building or structure is the subject with emphasis on geometry, lines, symmetry, perspective. Interior or exterior. | Building is background in a street scene (use T-04). Building in a cityscape panorama (use T-03 or label by dominant intent). |
| T-08 | Action | Fast motion captured. Sports, dance, vehicles in motion, jumping, running. Emphasis on peak moment or motion freeze. | Posed athlete portrait (use T-01). Slow candid walking (use T-02 or T-04). |
| T-09 | Aerial | Shot from drone, aircraft, or significantly elevated vantage. Top-down or oblique aerial perspective. Patterns from above. | Shot from a hill looking down (judgment — use T-03 if it reads as landscape). Airplane photographed from ground (use T-08 or S-10). |
| T-10 | Motion Blur | Movement intentionally rendered as blur for aesthetic effect. Smooth/silky water, light trails, star trails, cloud streaks, light painting, intentional panning blur. | Accidental camera shake (not a style — may be a reject). Handheld night shot with no intentional motion (use T-04 or T-03). A sharp action freeze (use T-08). |
| T-11 | Still Life | Arranged objects, controlled lighting. Studio, tabletop, product photography, flat lays, food styling. | Random snapshot of objects (use S-12 Object subject + most fitting type). Nature scene of flowers (use T-03 or T-06). |
| T-12 | Documentary | Event coverage, journalism, storytelling. Weddings, protests, ceremonies, behind-the-scenes, reportage. Multiple moments telling a story. | Single posed group shot at event (use T-01). Street scene without event context (use T-04). |

---

## Common Edge Cases

| Scenario | Subject | Type | Reasoning |
|:---|:---|:---|:---|
| Person standing in a vast landscape | S-01 People (if person > 10% of frame) OR S-05 Landscape (if person < 5%) | T-01 Portrait or T-03 Scenic | Tag by what the photographer emphasized. Small person = landscape. Large person = people. |
| Cat sitting in a window with city behind | S-02 Pet | T-02 Candid | Pet is subject. Unposed natural moment. |
| Pet leaping / running / mid-play | S-02 Pet | T-08 Action | Clear peak motion → action; lounging/walking pet → T-02 Candid. |
| Bird in flight over ocean | S-03 Wildlife | T-08 Action | Bird is the subject (not the ocean); flight = peak motion. A perched/still wild animal would be T-02 Candid. |
| Food on a restaurant table, people blurred behind | S-11 Food | T-11 Still Life | Food is clearly the subject. Styled/arranged = still life technique. |
| Sunset over the ocean, sky dominates | S-07 Sky | T-03 Scenic | Sky is the hero. If water dominates instead, use S-06 Seascape. |
| Milky Way over a mountain landscape | S-07 Sky (sky is the hero) OR S-05 Landscape (if land is equally important) | T-10 Motion Blur | Astro lives in `sky` now; the star-trail/streak blur is the defining Type. (Pinpoint-star astro with no trails leans T-03 Scenic.) |
| Airplane-window shot of farmland below | S-05 Landscape | T-09 Aerial | Tag subject by what's below; aerial is the technique. Town below → S-08, water → S-06, only wing+clouds → S-07. |
| Graffiti / sign / menu fills the frame | S-12 Object | T-04 Street or T-11 Still Life | Text/signage now lives under `object`. |
| Drone shot of a beach with people | S-06 Seascape (if water dominates) OR S-01 People (if people are the pattern) | T-09 Aerial | Aerial perspective is the defining technique regardless of subject. |
| Close-up of watch gears | S-12 Object | T-06 Macro | Object is the subject. Macro is the technique. |
| Wedding couple posing | S-01 People | T-01 Portrait | Posed = portrait, not documentary. |
| Wedding ceremony wide shot | S-01 People | T-12 Documentary | Event coverage = documentary. |
| Intentionally blurred city lights | S-13 Abstract | T-10 Motion Blur | Only use Abstract when the result is genuinely non-representational. |
| Silky waterfall in a forest, long shutter | S-15 Waterfall | T-10 Motion Blur | Waterfall is the hero subject; smooth-water blur = motion blur. A river that's only a small part of a vista → S-05 Landscape. |
| Panned shot of a cyclist, sharp rider / streaked background | S-10 Vehicle or S-01 People | T-10 Motion Blur | Intentional panning blur reads as motion blur even at a moderate shutter — effect over method. A fully frozen action shot is T-08 Action. |
| Frozen-spray waterfall, fast shutter | S-15 Waterfall | T-03 Scenic | Still a waterfall subject even without motion blur; technique here is scenic. |
| Statue / war memorial filling the frame | S-14 Monument | T-07 Architecture | Commemorative structure = monument, not building. Geometric/structural emphasis = architecture. |
| Lincoln-Memorial-style landmark at dusk | S-14 Monument | T-07 Architecture or T-12 Documentary | Monument subject; pick the type by intent (formal study vs. visit/event coverage). |

---

## Labeling Rules

1. **Tag by primary subject, not secondary elements.** A landscape with a tiny hiker is S-05 Landscape, not S-01 People.
2. **Tag by photographer intent when detectable.** A posed pet portrait is T-01 Portrait. A candid pet snap is T-02 Candid.
3. **When in doubt on Subject, ask: "What would I search for to find this photo?"** If the answer is "sunset," tag S-07 Sky. If the answer is "my dog," tag S-02 Pet.
4. **When in doubt on Type, ask: "What technique or approach defines this shot?"** Drone = Aerial. Intentional movement blur = Motion Blur. Posed person = Portrait.
5. **For a Type with no perfect fit, pick the closest technique.** A wide urban vista → T-04 Street or T-07 Architecture; a parked vehicle / travel grab → T-12 Documentary.
6. **Aerial and Motion Blur override other types.** A drone shot of architecture is T-09 Aerial; a motion-blurred waterfall in a landscape is T-10 Motion Blur.
7. **Macro overrides still life.** A close-up of a styled object at macro magnification is T-06 Macro.
8. **People is one tag.** Solo, group, or child — all S-01 People. Count and pose are captured by the Type axis (portrait/candid/documentary), not the Subject.
9. **Sky vs Landscape/Seascape is about who's the hero.** Sky filling most of the frame → S-07; land/water dominant with sky as backdrop → S-05/S-06.
10. **Abstract is the last resort.** Only when no other subject tag fits. It should represent < 5% of a typical library — if you can name what's in the photo, it isn't abstract.
11. **Monument vs Building is purpose, not size.** Commemorative/symbolic (statue, memorial, landmark, fountain) → S-14 Monument. Functional/inhabited (office, house, church-as-architecture, bridge) → S-09 Building.
12. **Waterfall is its own subject.** If a waterfall/cascade is the hero, use S-15 Waterfall — not S-05 Landscape — even when it sits in a wider scene. Falling water that's only an incidental element stays S-05/S-06.
