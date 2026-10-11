# A universal grammar of video production

This is the intended creative model for VideoGenome, not a claim that every capability already has a working adapter. A universal system cannot use a single mutually exclusive enum like cinematic/documentary/social/3D: cinematic is an aesthetic, documentary a representational intention, social a distribution context, and 3D a production technique.

## Six independent dimensions

| Axis | Question | Examples |
| --- | --- | --- |
| Intent | What viewer outcome matters? | persuade, teach, entertain, document, inspire, convert |
| Audience | Who watches in which setting? | consumers, students, workers, fans, mute autoplay |
| Narrative | What sequence communicates meaning? | demonstration, reveal, interview, problem-solution, montage, dramatic arc |
| Aesthetics | What style and emotional tone? | documentary naturalism, premium cinematic, lo-fi personal, playful graphic |
| Production | How is each shot physically made? | filming, licensed footage, 3D, animation, generative video, screen capture, motion design |
| Delivery | Where, when and in what form? | shorts, film, courses, presentations, 16:9, 9:16, multi-language |

A video archetype is a **bundle of presets across these axes**, never a mutually exclusive video category. Each scene and shot can employ a different production method.

## The reusable composition hierarchy

~~~
Project/Series
  BrandSystem / Audience / WorldBible
    VideoBlueprint (narrative and delivery goals)
      Beat (setup, escalation, payoff, CTA)
        Scene (time, place, participants)
          Shot (camera, movement, composition, length)
            Layer (picture, graphics, caption, music, SFX, dialogue)
              Asset (origin, rights, versions, references)
~~~

A recipe can be reused at any level. The scene declares artistic purpose; a shot recipe supplies cinematic grammar; an adapter converts the intent into actual filmed, generated or assembled media.

Suggested future types: BrandKit, CharacterBible, WorldBible, NarrativeRecipe, SceneRecipe, ShotRecipe, LookPreset, AudioRecipe, AssetRecord, DeliveryProfile and EvaluationRubric. Every reusable unit needs a stable identifier, semantic version, dependencies, examples, supported capability bounds and approval status.

## Creative domains and production capabilities

These domains are modular; not every video requires all of them.

| Area | What the repository eventually needs to encode | Typical failure |
| --- | --- | --- |
| 1. Objective and audience | outcome, viewer, action, tone, constraints | irrelevant idea |
| 2. Creative strategy | premise, product claim, differentiation, concept | generic or unsupported claims |
| 3. Story architecture | acts, beats, hooks, emotional progression, payoffs | confusing or flat structure |
| 4. Scripts/dialogue | spoken text, pacing, pronunciation, localization | unnatural or inaccurate copy |
| 5. Storyboard/previsualization | ordering, coverage, thumbnails, blocking | missing visual continuity |
| 6. Cinematography | lenses, framing, depth, movement, point of view | visually disorienting cuts |
| 7. Lighting and color | light sources, exposure, temperature, grade | inconsistent shot look |
| 8. Performances | casting, talent, direction, wardrobe, consent | misrepresented actors |
| 9. Footage acquisition | shot lists, stock search, capture settings | incorrect/low quality media |
| 10. Generative media | prompt/reference contract, model controls, retries | continuity/identity failure |
| 11. 3D production | geometry, rigs, shaders, camera, simulation | implausible 3D |
| 12. Animation | 2D/3D motion language, poses, timing, easing | robotic or unclear actions |
| 13. VFX/compositing | tracking, mattes, masking, occlusion, particles | poorly integrated layers |
| 14. Graphic design | grids, typography, hierarchy, logo/brand rules | illegible or inconsistent look |
| 15. Editing | pacing, rhythm, transitions, retiming, J/L cuts | bad continuity and attention |
| 16. Voice/audio capture | microphones, dialogue, synthetic voice, room tone | unclear narration |
| 17. Music and SFX | motifs, stems, sync, rights, emotional arc | intrusive or unlicensed audio |
| 18. Audio post | loudness, dialogue ducking, compression, stereo | clipping, quiet dialogue |
| 19. Captions/accessibility | safe areas, reading speed, alt-description | unusable captions |
| 20. Localization | scripts, voice, culture, typography expansion | overflow, mistranslation |
| 21. Identity and continuity | products, persons, locations, props, temporal consistency | drift across clips |
| 22. Brand/legal governance | approvals, claims, likeness, licensing, disclosures | publication risk |
| 23. Technical mastering | frame rate, codecs, color science, aspect variants | failed delivery |
| 24. Evaluation | technical metrics, perceptual rubrics, human review | attractive but incorrect output |
| 25. Production economics | cost budgets, provider choice, retries, caching | poor cost per approved video |
| 26. Distribution learning | channel variants, thumbnails, evaluation of outcomes | optimizing to vanity metrics |

The schema v0.1 only captures a portion. The intent is to create multiple orthogonal modules and a useful representation for combining them, not one enormous template schema with hundreds of optional fields.

## Shot intent versus execution

Consider an expert shot recipe: *Reveal the product from a close-up to a heroic three-quarter view over four seconds, preserving its actual geometry and logos.*

Depending on inputs and constraints it can be fulfilled by a camera shoot, a product-turntable 3D render, carefully edited stock, generated video with references, or 2.5D compositing. Each adapter must declare **which requirements it can actually guarantee**. Generated-video prompts often cannot guarantee fine typography or product identity, so those demands require a different engine or review.

A project may also combine those media types in a single scene, with music driving the editorial beat. Therefore scenes, layers and audio tracks are more foundational than broad labels like "marketing video".

## The creative contract between models

The frontier model is the **template author**: it defines narrative beats, expected shots, visual language, style tokens, tunable parameters, prohibited changes, requirements, reference videos and quality rubrics.

The smaller model is the **template filler**: it searches the approved registry, fills named content slots, points to licensed media, and selects approved variants. It cannot replace the color system, claim constraints, continuity, or edit structure without a reviewed new version.

The compiler is the **enforcer**. An engine adapter is the **executor**, not an independent creative authority. The evaluator determines which requirements can be machine-tested and which still need explicit human approval.

## Examples across ostensibly different video types

**Luxury car spot:** dramatic teaser, filmed macro detail, 3D visualization, generated landscape, real hero shot, graphics overlay, branded end card, approved music. Product identity and claims require signoff.

**Creator testimonial:** authorized speaking footage, authentic cutaways, screen recording as proof, captions and a CTA. Editing must preserve the true meaning of the original speaker.

**Software explainer:** interface recording, animated callouts, narrator audio, captions, localized versions. Exact UI fidelity outranks cinematic spectacle.

**Documentary profile:** archival clips, location footage, interview, narration, maps and editorial graphics. Provenance and evidence review matter more than perfect brand design.

**Animated narrative:** character/model bible, action planning, poses, simulated backgrounds, layered sound, continuity references. Story progression and character identity are first-class.

All should use a **shared creative/time/media contract**, with specialized adapters and rubrics selected by declared capabilities.

## Quality has independent dimensions

Technical correctness, semantic truth, artistic consistency, narrative coherence, accessibility, legal rights and cost are different metrics. A single AI "looks good" score is insufficient. Future evaluations should produce linked artifacts: probe data, frames, captions, waveform information, reference comparisons and reviewer decisions. A failure must point to the responsible asset or shot so the system regenerates only affected work.

The ultimate package format should preserve reference renders and benchmark briefs alongside code and schemas. Without those, expert craftsmanship will get lost when a cheaper model fills slots.
