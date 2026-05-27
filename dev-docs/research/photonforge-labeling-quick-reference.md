# PHOTONForge Photo Labeling Quick Reference

**Version:** 1.0 | **Date:** 2026-05-26

Use this guide when manually labeling training data or correcting auto-classifications. Every photo gets **exactly one Subject Tag** and **exactly one Photo Type Tag**.

---

## Decision Flow: Subject Tag (What is in the photo?)

```
Is there a person or people?
├─ YES
│   ├─ Single person, face prominent? ─────────── S-01 Person
│   ├─ Multiple people? ──────────────────────── S-02 People
│   └─ Subject is clearly a child/baby? ──────── S-03 Child
│
Is there an animal?
├─ YES
│   ├─ Wild animal in natural habitat? ────────── S-04 Wildlife
│   └─ Domestic pet in home/yard setting? ─────── S-05 Pet
│
Is the main subject a plant/flower?
├─ YES ────────────────────────────────────────── S-06 Plant
│
Is it a wide natural scene (no dominant subject)?
├─ YES
│   ├─ Ocean, beach, waves, coastal water? ────── S-08 Seascape
│   └─ Mountains, forests, fields, desert? ────── S-07 Landscape
│
Is the main subject a structure or urban scene?
├─ YES
│   ├─ Multiple buildings, skyline, panorama? ─── S-09 Cityscape
│   └─ Single building, interior, detail? ─────── S-10 Building
│
Is the main subject a vehicle? ────────────────── S-11 Vehicle
Is the main subject food/drink? ───────────────── S-12 Food
Is the main subject a specific object? ────────── S-13 Object
Does text/signage dominate the frame? ─────────── S-14 Text
Is it a night sky / astrophotography? ─────────── S-15 Night Sky
Is it non-representational (patterns, textures,
  light studies, intentional abstraction)? ─────── S-16 Abstract
```

---

## Decision Flow: Photo Type Tag (What kind of photo is it?)

```
Was it shot from a drone or elevated position? ─── T-09 Aerial

Is there visible long-exposure motion
  (smooth water, light trails, star trails)? ───── T-10 Long Exposure

Is it an extreme close-up of a small subject
  (insects, flowers, textures at macro scale)? ──── T-06 Macro

Is it a controlled/arranged studio setup? ──────── T-11 Still Life

Is the primary subject an animal in nature? ────── T-05 Wildlife

Is there fast action / sports / peak motion? ───── T-08 Action

Is the subject a building/structure with
  geometric emphasis? ──────────────────────────── T-07 Architecture

Is it a wide natural scene emphasizing
  environment over subject? ────────────────────── T-03 Landscape

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
| S-01 | Person | Single human is the clear subject. Headshots, environmental portraits, self-portraits. | Multiple people (use S-02). Child is the subject (use S-03). Person is tiny in a landscape (use S-07). |
| S-02 | People | Two or more humans are the subject. Group shots, crowds, gatherings, teams. | One person dominates (use S-01). People are incidental background in a street scene (use by primary subject). |
| S-03 | Child | Subject is visibly a baby, toddler, or young child. | Teenagers who could pass as adults (use S-01 or S-02). |
| S-04 | Wildlife | Wild animal in nature. Birds in sky, deer in forest, insects on flowers, fish underwater. | Domestic pet in home (use S-05). Animal is tiny in a landscape (use S-07). Zoo animals in enclosures (judgment call -- use S-04 if animal fills frame). |
| S-05 | Pet | Domestic animal in home, yard, or domestic context. Dogs, cats, hamsters, aquarium fish. | Stray/feral animals in wild setting (use S-04). |
| S-06 | Plant | Flowers, trees, gardens, botanical close-ups. Plant is the clear subject. | Plant is background in a landscape (use S-07). Plant is part of food styling (use S-12). |
| S-07 | Landscape | Natural wide scene. Mountains, valleys, forests, deserts, fields, dramatic skies. No single dominant subject. | Ocean/coastal is primary (use S-08). Urban scene (use S-09). A person or animal is clearly the subject (use their tag). |
| S-08 | Seascape | Ocean, sea, waves, beaches, harbors, coastal water dominates. | Lake in a mountain scene (use S-07 if mountains dominate). Boat is the subject (use S-11). |
| S-09 | Cityscape | Urban panorama, skyline, multiple buildings, city overlook. Wide urban scene. | Single building fills frame (use S-10). Street-level with people as focus (use S-01/S-02). |
| S-10 | Building | Single structure, architectural detail, interior, facade, bridge, monument. | Multiple buildings in a skyline (use S-09). Building is background behind a person (use S-01). |
| S-11 | Vehicle | Car, motorcycle, aircraft, boat, train, bicycle is the clear subject. | Vehicle is incidental in a street scene. Boat as tiny element in seascape (use S-08). |
| S-12 | Food | Plated meal, ingredients, beverages, cooking process. Food is the subject. | Person eating where face is the focus (use S-01). Restaurant interior where space is the subject (use S-10). |
| S-13 | Object | Specific non-living, non-food item. Tools, products, instruments, household items, still life arrangements. | Object is text/signage (use S-14). Object is food (use S-12). Object is a vehicle (use S-11). |
| S-14 | Text | Signs, documents, graffiti, typography, menus, book covers. Text or lettering dominates the frame. | Text is incidental in a street scene. Brand logo on a product (use S-13). |
| S-15 | Night Sky | Stars, Milky Way, moon, aurora, meteor showers, planetary conjunctions. Sky is the subject. | Night cityscape with lights (use S-09). Night portrait with sky background (use S-01). |
| S-16 | Abstract | Patterns, textures, light studies, intentional blur, reflections, experimental. Non-representational or unidentifiable subject. | Macro of a recognizable flower (use S-06). Bokeh behind a portrait (use S-01 -- subject is person). |

---

## Photo Type Reference Table

| ID | Tag | Assign When | Do NOT Assign When |
|:---|:---|:---|:---|
| T-01 | Portrait | Person is posed or intentionally framed. Headshot, environmental portrait, fashion, formal. | Person is unposed/candid (use T-02). Multiple people at an event (use T-12). |
| T-02 | Candid | Person captured naturally, unposed, in-the-moment. Street candid, behind-the-scenes, daily life. | Person is clearly posing (use T-01). It's event coverage (use T-12). Urban scene without people focus (use T-04). |
| T-03 | Landscape | Wide natural scene. Emphasis on environment, depth, atmosphere. Scenic vistas, nature panoramas. | Urban scene (use T-04 or T-07). Subject is a specific animal in nature (use T-05). |
| T-04 | Street | Urban environment. Decisive moment, human activity, city life, found compositions in public spaces. | Rural/nature scene (use T-03). Formal event (use T-12). Architecture with no human element (use T-07). |
| T-05 | Wildlife | Animal in natural habitat is the subject. Telephoto, bird photography, safari, underwater marine life. | Pet in home (assign type by technique -- T-01 if posed, T-02 if candid). Animal is incidental in landscape (use T-03). |
| T-06 | Macro | Extreme close-up. Magnification reveals detail invisible to naked eye. Insects, water drops, textures, electronics. | Regular close-up portrait (use T-01). Close-up of food (use T-11 if styled). |
| T-07 | Architecture | Building or structure is the subject with emphasis on geometry, lines, symmetry, perspective. Interior or exterior. | Building is background in a street scene (use T-04). Building in a cityscape panorama (use T-03 or label by dominant intent). |
| T-08 | Action | Fast motion captured. Sports, dance, vehicles in motion, jumping, running. Emphasis on peak moment or motion freeze. | Posed athlete portrait (use T-01). Slow candid walking (use T-02 or T-04). |
| T-09 | Aerial | Shot from drone, aircraft, or significantly elevated vantage. Top-down or oblique aerial perspective. Patterns from above. | Shot from a hill looking down (judgment -- use T-03 if it reads as landscape). Airplane photographed from ground (use T-08 or S-11). |
| T-10 | Long Exposure | Visible motion blur from extended shutter. Smooth water, light trails, star trails, cloud streaks, light painting. | Accidental camera shake / motion blur (not a style -- may be a reject). Handheld night shot without intentional motion (use T-04 or T-03). |
| T-11 | Still Life | Arranged objects, controlled lighting. Studio, tabletop, product photography, flat lays, food styling. | Random snapshot of objects (use S-13 Object subject + most fitting type). Nature scene of flowers (use T-03 or T-06). |
| T-12 | Documentary | Event coverage, journalism, storytelling. Weddings, protests, ceremonies, behind-the-scenes, reportage. Multiple moments telling a story. | Single posed group shot at event (use T-01). Street scene without event context (use T-04). |

---

## Common Edge Cases

| Scenario | Subject | Type | Reasoning |
|:---|:---|:---|:---|
| Person standing in a vast landscape | S-01 Person (if person > 10% of frame) OR S-07 Landscape (if person < 5%) | T-01 Portrait or T-03 Landscape | Tag by what the photographer emphasized. Small person = landscape. Large person = portrait. |
| Cat sitting in a window with city behind | S-05 Pet | T-02 Candid | Pet is subject. Unposed natural moment. |
| Bird in flight over ocean | S-04 Wildlife | T-05 Wildlife | Bird is subject, not the ocean. |
| Food on a restaurant table, people blurred behind | S-12 Food | T-11 Still Life | Food is clearly the subject. Styled/arranged = still life technique. |
| Graffiti on a building wall | S-14 Text (if text dominates) OR S-10 Building (if architecture dominates) | T-04 Street or T-07 Architecture | Judge by what fills more frame and what the photographer focused on. |
| Milky Way over a mountain landscape | S-15 Night Sky (if sky is the hero) OR S-07 Landscape (if land is equally important) | T-10 Long Exposure | Long exposure technique is the defining characteristic. |
| Drone shot of a beach with people | S-08 Seascape (if water dominates) OR S-02 People (if people are the pattern) | T-09 Aerial | Aerial perspective is the defining technique regardless of subject. |
| Close-up of watch gears | S-13 Object | T-06 Macro | Object is the subject. Macro is the technique. |
| Wedding couple posing | S-02 People | T-01 Portrait | Posed = portrait, not documentary. |
| Wedding ceremony wide shot | S-02 People | T-12 Documentary | Event coverage = documentary. |
| Intentionally blurred city lights | S-16 Abstract | T-10 Long Exposure (if motion blur) OR S-16 Abstract + T-04 Street (if bokeh) | If the abstraction comes from long exposure, tag the technique. |

---

## Labeling Rules

1. **Tag by primary subject, not secondary elements.** A landscape with a tiny hiker is S-07 Landscape, not S-01 Person.
2. **Tag by photographer intent when detectable.** A posed pet portrait is T-01 Portrait. A candid pet snap is T-02 Candid.
3. **When in doubt on Subject, ask: "What would I search for to find this photo?"** If the answer is "sunset," tag S-07 Landscape. If the answer is "my dog," tag S-05 Pet.
4. **When in doubt on Type, ask: "What technique or approach defines this shot?"** Drone = Aerial. Long shutter = Long Exposure. Posed person = Portrait.
5. **Aerial and Long Exposure override other types.** If it's a drone shot of architecture, it's T-09 Aerial (the perspective is the defining element). If it's a long-exposure waterfall in a landscape, it's T-10 Long Exposure.
6. **Macro overrides still life.** If it's a close-up of a styled object at macro magnification, it's T-06 Macro.
7. **Documentary requires event context.** A single candid shot on the street is T-04 Street or T-02 Candid. Documentary implies event coverage or journalistic storytelling across a series.
8. **Abstract is the catch-all for unclassifiable subjects.** Only use S-16 when no other subject tag fits. It should represent < 5% of a typical library.
