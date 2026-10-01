# Promptvoorbeelden product-LoRA (`tvbprod`)

Prompts schrijf je in het Engels. Gebruik dezelfde opbouw als de captions,
dan herkent het model het meest:

```
tvbprod, [wat er gebeurt], [omgeving], [hoek en afstand], [licht]
```

- Zet `tvbprod` altijd vooraan en beschrijf het product verder **niet** (geen
  kleur, vorm of logo): dat heeft de LoRA geleerd. Beschrijf je het toch, dan
  "vecht" je prompt tegen de LoRA.
- Gebruik de woorden uit je captions ("seen from the side", "close-up",
  "wide shot"), niet afwisselend synoniemen.
- LoRA-sterkte: begin op 1.0. Product klopt niet? Hoger (1.1–1.2). Beelden
  lijken te veel op trainingsfoto's? Lager (0.7–0.9).
- Logo en tekst gaan het vaakst mis: zet het TVB-logo er achteraf op met
  `fotogeneratie/voeg_logo_toe.py`, en laat het model geen tekst maken.
- Maak per prompt 4 varianten (verschillende seeds) en kies de beste.

## Vacatures en employer branding

```
tvbprod, being used by a technician in a navy work jacket, in a modern technical room with cable trays, seen from the side, medium shot, cool fluorescent light
tvbprod, held by two hands in work gloves, on a rooftop with solar panels, close-up, bright midday sun
tvbprod, being installed by a young woman in safety glasses, in a half-finished office building, seen from slightly below, soft daylight through large windows
tvbprod, on a workbench next to a laptop and a coffee mug, in a small workshop with tools on the wall, seen from above, warm indoor light
```

## Projecten en website

```
tvbprod, mounted on the wall of a hospital corridor, people walking past slightly blurred, wide shot, even overhead light
tvbprod, standing in a clean server room between racks, seen from the front, cool blue ambient light
tvbprod, on a construction site with scaffolding in the background, wide shot, overcast daylight
tvbprod, in a bright school classroom, seen from the back of the room, morning sunlight
```

## Social media (opvallend, veel ruimte voor tekst)

```
tvbprod, alone on a plain dark navy background, centered with empty space above it, soft studio light from the left
tvbprod, on a concrete floor, seen from directly above, empty space on the right side, soft overcast light
tvbprod, seen from a low angle close to the ground, dramatic evening sky behind it, wide shot
tvbprod, close-up of the details, shallow depth of field, studio lighting
```

Laat bij social-mediabeelden ruimte vrij ("empty space on the right side") voor
tekst en het logo, en zet die er in Canva of Photoshop op.

## Seizoenen en thema's

```
tvbprod, on a snowy rooftop, seen from the side, cold winter morning light
tvbprod, on a terrace with plants, seen from the front, warm summer evening light
tvbprod, in a festive office with a Christmas tree in the background, slightly blurred, warm indoor light
```

## Controleprompts

```
a modern technical room with cable trays, cool fluorescent light
```

Zonder triggerwoord hoort het product **niet** te verschijnen. Verschijnt het
toch, dan is de LoRA overgetraind: kies een eerder checkpoint.

## Na het genereren

```powershell
# 1. Huisstijl (vaste LUT)
python fotogeneratie/pas_lut_toe.py outputs/gegenereerd --lut tvb_stijl.cube --sterkte 0.8
# 2. Logo rechtsonder
python fotogeneratie/voeg_logo_toe.py outputs/lut
```

Controleer elk beeld op productdetails (vorm, verhoudingen, kleuren, knoppen,
naden) voordat het naar buiten gaat.
