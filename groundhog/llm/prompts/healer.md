A saved test step's selector no longer matches the page. Given the step's intent and an accessibility snapshot of the current page, return ONE resilient Playwright locator for the element the step intends to act on. Only propose a selector you can justify from the snapshot.

Hard rule: NEVER return an element whose visible label or action contradicts the step intent. A "Delete", "Submit", or "Confirm" step must not heal to a "Cancel"/"Close"/"Back" control, and vice versa. If no element clearly matches the intent, it is better to fail than to act on the wrong element — in that case return an empty selector and say why in the reasoning.

Selector rules — resilient locators only:
- Prefer, in order: [data-testid="…"], a stable #id, [aria-label="…"], role=button[name="…"] / role=link[name="…"], [placeholder="…"], text="…". Key on visible, human-meaningful text and roles.
- Avoid brittle CSS: positional/:nth selectors, long descendant chains, hashed/generated class names, and bare tags (div, button, a).
- ONE engine per locator; never glue an attribute onto role= — role=textbox[placeholder='…'] is INVALID.

{{context}}
