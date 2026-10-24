# Groundhog brand guidelines

Groundhog drives an app once, saves the run as plain selectors, and replays it
free. The brand follows that: warm, quick, and exact about numbers.

Tokens live in `design-tokens.css`. The mascot lives in `groundhog.svg`.

## The idea

One shape runs everything: the burrow, a circle. Pictures and mascot poses sit
in circles, buttons are pills, list bullets are small amber circles, and the
loader is the groundhog popping out of its hole.

## Colour

Grey ground, burrow-dark ink, one amber accent.

| Token | Value | Use |
| --- | --- | --- |
| `--gh-ground` | `#E4E3DF` | Most of every page |
| `--gh-surface`, `--gh-surface-2` | `#D7D6D1`, `#CBC9C3` | A tone step instead of a border |
| `--gh-muted` | `#4F453B` | Secondary notes, never running text |
| `--gh-burrow` | `#241911` | Ink, and the one dark field per page |
| `--gh-accent` | `#F2A71B` | The action and the mascot's circle |
| `--gh-pass`, `--gh-fail` | `#1B6B3C`, `#A8231B` | Results only. Fixed, never re-themed |

Rough proportions: ground 58, surface 20, burrow 14, amber 8. Fur, belly, paws
and cheek colours belong to the mascot and never colour interface.

## Type

Outfit for everything. Five sizes: hero (48 to 108px, tracking -0.04em),
section heading (36 to 72px), statement (22 to 32px, medium), body (18px,
full ink), small (15px). JetBrains Mono appears only for code: selectors,
commands and terminal output.

## Shape

Pills and circles only. Surfaces separate by tone step, not by lines or
shadows. No gradients.

## Motion

Transform and opacity only, and everything stops under
`prefers-reduced-motion`.

- Pop, 750ms: rises from the hole with an overshoot. Plays on load, hover and tap.
- Blink every few seconds, pupils drift left then right.
- Ear twitch about every 6 seconds, each ear on its own offset.
- Pose props loop over 1 to 3 seconds: floating Zs, sweat drop, check pulse, magnifier sweep, swaying sign.
- Buttons, 150ms: 105% on hover, 96% on press, same overshoot curve.

## The mascot

Eight poses, each rising from the bottom edge of a circle.

| Pose | Use |
| --- | --- |
| Peek | Greetings: landing page, README header |
| Wake | First launch and onboarding |
| Sleep | Empty states and idle queues |
| Search | Authoring and loading |
| Pass | A green run |
| Zero | A green run with no AI calls |
| Heal | A selector was repaired |
| Fail | A failing assertion |

Rules:

1. One pose per screen.
2. Always inside a circle.
3. Nothing sits on top of the mascot, and it never sits on text.
4. Never celebrate a failure. The fail pose is small, in a corner, next to the cause.
5. Results lead with numbers: steps, seconds, AI calls. The mascot lives in headers and empty states.

## Voice

Dry and plain. Short sentences, numbers first, no exclamation marks.
"14 steps, 0 AI calls, 3.2s." beats any slogan.
