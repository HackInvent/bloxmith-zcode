# Zcode artwork

This illustration belongs to the BloxSmith industrial pixel-art block family.
It communicates the block's function; it is not a screenshot of Studio or a
promise of additional runtime features.

## Files

- `cover.png`: original square PNG cover, preserved without retouching.
- `thumbnail.webp`: 320 × 320 WebP derivative for README and catalog cards.
- Accent: Violet / purple.
- Meaning: A local coding-agent launcher with instructions, a working directory and optional persistent sessions.

The module's silhouette, viewpoint, light, framing and steel/graphite housing are
shared with the other pilot blocks. A large roof symbol and a single English title
provide identification without relying only on color. Descriptive alt text must
accompany the image wherever it is rendered.

These are documentation assets, not executable UI assets. Their presence does
not automatically register them in Studio or the public compatibility catalog.
The block version and runtime contract remain unchanged.

## Provenance

Created on 2026-09-27 with the built-in image generation tool, using owner-supplied
visual references. No image API key or CLI fallback was used.
The generated Audio Mixer cover is the family anchor. Use the cover from the companion HackInvent/bloxmith-audio-mixer repository as the input reference.

The selected generated PNG was copied byte for byte. Only the thumbnail was
resized and encoded; no text, recoloring or compositing was applied afterwards.
The artwork is distributed under this repository's [Apache-2.0 license](../LICENSE).

Thumbnail export with ImageMagick:

```sh
convert media/cover.png -thumbnail 320x320 -strip -quality 88 -define webp:method=6 media/thumbnail.webp
```

## Generation prompt

The following is the exact prompt used for the selected cover. Generation is
not deterministic; retain this selected cover as the reference for future edits.

```text
Use case: stylized-concept.
Asset type: square cover illustration for the Zcode software-agent block in the BloxSmith catalog.
Input image: the Audio Mixer cube is the exact family reference. Retain its cube proportions, front/top/right three-quarter viewpoint, position, square framing, white backdrop, corner reinforcements, housing materials, restrained pixel-art technique and upper-left lighting. Create the Zcode variant, not an audio device.
Subject changes: replace all orange accents with restrained violet-purple light; keep dark charcoal and graphite housing and steel edges. Change the roof display to one LARGE luminous terminal prompt symbol ">_". Replace the entire front panel with a wide upper title plate reading exactly "ZCODE" in crisp white uppercase pixel lettering, and one large recessed dark terminal display below. The display shows a prominent terminal prompt glyph, a few simple indented horizontal code-line bars, and one clear output/result pane. Use abstract bars, not tiny words or actual code. Below it, two or three large understated controls with simple folder, instruction/document and circular session-arrow symbols. These represent working directory, instructions and persistent session. The side panel should show sparse generic data ports and a vertical violet light strip, not audio jacks.
Semantic truth: this is a configurable local coding-agent launcher with named inputs, instructions, a working directory and persistent sessions. It is not an autonomous robot, chatbot mascot, model provider, microphone or audio tool. Do not promise unavailable features or depict a particular provider.
Composition: a single complete cube, identical visual scale and margins to the reference. One square image, no collage. Keep the existing plain near-white background and subtle grounded shadow. Match the reference's front-facing title placement and strong visual hierarchy. Roof symbol and front screen should be recognizable at 320 px.
Style: premium crisp industrial pixel-art illustration, deliberately stepped edges, controlled clusters and tactile metal, no photorealism, no excessive neon, no decorative clutter.
Text (verbatim): "ZCODE" exactly once (letters Z C O D E). The terminal symbol ">_" is allowed as an icon. No other words, fake text, subtitles, slogans, version numbers, watermarks, labels or logos.
Avoid: all waveforms, faders, mixer diagrams, orange accents, audio connectors, additional objects, cats, people, desks, floating props, humanoid heads and mascot faces.
```
