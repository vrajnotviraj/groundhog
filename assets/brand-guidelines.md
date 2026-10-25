# Groundhog brand guidelines

Groundhog drives an app once, saves the run as plain selectors, and replays it
free. The brand is the run report: a board of tiles, each holding one thing,
and numbers before words.

Tokens live in `design-tokens.css`. The mascot lives in `groundhog.svg`.

## The idea

Every surface is a board. Tiles sit edge to edge on 8px gaps with 8px outer
margins and no empty cells. A tile holds exactly one thing: a figure, a step, a
selector, a sentence, a link, the groundhog. Nothing is ever two things. Where
a designer would reach for a card, a divider or a hero image, there is a tile.

## Colour

Bone ground, chocolate ink, one green.

| Token | Value | Use |
| --- | --- | --- |
| `--gh-ground` | `#E5E1D8` | The page, seen only in the gaps |
| `--gh-surface`, `--gh-surface-2` | `#DAD5CA`, `#B8AD9E` | Most tiles. Neighbours differ in tone, never by a line |
| `--gh-muted` | `#61524A` | Secondary notes, and the third dark tile tone |
| `--gh-ink` | `#2A1D17` | Text, the name band, the groundhog's tile |
| `--gh-accent` | `#3D6433` | The action, and a green run. Pass green is the accent |
| `--gh-fail` | `#A8231B` | A failed run. The only colour outside the palette |
| `--gh-sun` | `#F5C518` | The one primary action, live runs, healed steps |

Rough proportions on a screen: surfaces 55, ink 25, ground 10 (the gaps),
green 5. Fail red appears only when something failed. Text on a dark tile is
`--gh-ink-text`.

## Type

Albert Sans for everything. 600 for display and headings, 400 for text, 500
for emphasis. Five sizes: display (64 to 128px, tracking -0.04em, leading 0.9),
heading (40px, tracking -0.035em), lead (22px), body (17px, full ink), small
(15px). Tabular figures wherever numbers align. The name is always lowercase
`groundhog` in the display weight; the name band sets it at 220px, cropped by
the tile at both ends. JetBrains Mono appears only for code: selectors,
commands and terminal output.

## Shape

Tiles. One 4px radius, filled, never outlined, never shadowed. A button is a
tile too: the whole tile is the link, label bottom-left. No circles, no pills,
no gradients, no lines.

## Motion

Transform and opacity only, and everything stops under
`prefers-reduced-motion`.

- The name band is a marquee: `groundhog` repeats and travels edge to edge at a
  constant speed, 40s a loop, paused on hover.
- Tiles enter once, staggered 60ms apart, rising 16px with opacity.
- Buttons, 150ms: the tile darkens one tone on hover and presses to 98%.
- Tiles never lift.

## The mascot

A groundhog peeking out of its burrow in front of the sunrise, built the way
Duolingo builds Duo: no outlines, flat fur `#E0873A` with one darker side tone,
a lighter face mask `#F4B877`, big white eyes with `#1B2533` pupils, white
incisors, no hands.

1. Always on an ink tile, sitting on its bottom edge, the sun `--gh-sun` behind it.
2. Its mood is the run's state, shown only in the face: lids cut into the eye
   whites and how far it sinks into the hole. Happy squint when all passed,
   worried lids when something failed, focused lids and rocking while a run is
   live, closed eyes and z's when nothing has run, eyes squeezed shut while a
   password is typed.
3. One groundhog per screen. The head alone is the mark and the favicon.
4. Nothing sits on the groundhog, and it never sits on text.

## Voice

Dry and plain. Short sentences, numbers first, no exclamation marks.
"14 steps, 0 AI calls, 3.2s." beats any slogan.
