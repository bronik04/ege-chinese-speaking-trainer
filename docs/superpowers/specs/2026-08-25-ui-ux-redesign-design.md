# UI/UX redesign: three focused modes

**Status:** agreed design, ready for implementation planning

## Goal

Make the Chinese oral-exam trainer feel calm, intentional, and easy to use in three distinct contexts:

1. choosing and starting a practice session;
2. completing a spoken task under exam conditions;
3. reviewing a student's voluntarily submitted work as the sole teacher.

The redesign improves presentation and navigation only. It does not change the already agreed review-queue product rules: one configured teacher, voluntary student submission, no assignments, groups, deadlines, or written comments.

## Visual language

- Preserve the existing warm paper background, dark brown text, deep red accent, and serif editorial character.
- Use the red accent only for the current state, key score/status, and primary actions.
- Use generous whitespace and clear type hierarchy for learner-facing pages; use denser but still calm lists for teacher work.
- The horizontal Chinese phrase `熟能生巧` sits above the Russian translation on the landing page. Remove its vertical treatment and remove pinyin/transcription.
- Do not reintroduce an “About me” block.

## Information architecture

The product has one visual system with three screen modes:

| Mode | Main user goal | Interface character |
| --- | --- | --- |
| Discover | Pick a suitable exercise and begin | Editorial, spacious, welcoming |
| Practice | Finish the current speaking task | Focused, minimal, sequential |
| Review | Listen to submitted work and save scores | Compact teacher workspace |

Global navigation is deliberately small: trainer, reference, variants, account. It must remain consistent on static pages; the active destination is marked by text treatment, not a new decorative component.

## Landing page

### Hero

- Header: compact horizontal logo, primary navigation, account entry.
- Hero hierarchy: exam context → horizontal Chinese phrase → Russian message → concise explanation → single primary action, “Выбрать тренировку”.
- Keep the current useful facts (three tasks, fourteen minutes, one variant) as a quiet row below the primary action.
- Add a brief three-step explanation of preparation, recording, and optional submission to the teacher.

### Choosing a format

- Show the three oral tasks as equally weighted cards: interview, photo description, and photo comparison.
- Each card explains the expected response and time/quantity constraint in plain language.
- One click starts the selected task; a whole variant remains available as a clearly labelled alternative rather than competing with every card.

### Secondary content

- Keep a compact “how it works” section: exam timing, saved recordings/progress, optional teacher review.
- Do not add marketing panels, testimonials, educator biography, or duplicate calls to action.

## Practice mode

### Layout and state

- The learner sees the current task, its stage, timer, instruction, relevant material, recording controls, and one next action.
- On desktop, a narrow progress rail shows tasks 1–3 and their completion status. On mobile it becomes a compact top progress summary; it must not consume the content width.
- The header provides only an exit control, a small brand marker, and a truthful saving state.
- Current state is expressed in text and color; color alone never conveys completion, recording, or errors.

### Photographic tasks are non-negotiable

- Task 2 must show its source photograph(s) as the dominant material in the task area, with an accurate alternative text.
- Task 3 must show both comparison photographs at the same visual weight, with their labels and alternative texts.
- The photographs remain visible during preparation, recording, playback, and re-recording. They do not move behind a modal or collapse into an attachment.
- On a narrow screen, photographs stack vertically while keeping the labels and order unambiguous.
- Task prompt and response plan follow the image material. Recording controls follow the prompt; the user never loses the image context while recording.

### Recording

- A recording card clearly names its state: not started, recording with elapsed time, ready for playback, or retry available.
- It offers only the action relevant to the current state, preventing competing “continue”, “record”, and “submit” calls to action.
- After the final task, present results and the voluntary review-submission action separately. The wording must make clear that submission is optional and only possible for fully recorded material.

## Teacher workspace

- Replace the large teacher modal with a dedicated full-page teacher workspace reachable from the account area.
- A left navigation on desktop groups queue, reviewed works, materials, and profile. On mobile it becomes a compact local navigation without hiding the current workspace title.
- The initial screen is the queue, with the number of waiting requests and small filters for student, task, status, and date.
- Each queue row shows student name, submission type, selected tasks, date, and status. It opens the selected review rather than expanding every work at once.
- The review screen keeps recordings and scoring in adjacent, visually distinct areas. Scoring contains only the existing criteria and total; it does not introduce written comments.
- Reviewed work stays accessible from history. Its scores are legible, but the primary action changes to update rather than save.

## Responsive and accessibility requirements

- Preserve readable line length and tap targets of at least 44×44 CSS pixels.
- Keyboard users can reach navigation, recording controls, filters, audio controls, score fields, and dialog-close controls in a logical order.
- Maintain existing semantic landmarks, headings, labels, `aria-live` status feedback, and focus restoration. New visual wrappers must not replace meaningful controls with clickable `div`s.
- Text and status contrast must meet WCAG AA against paper surfaces.
- Motion is limited to brief state transitions and respects `prefers-reduced-motion`.

## Delivery boundaries

### In scope

- Page and component layout, typography, responsive behavior, navigation placement, buttons, cards, queue presentation, and visual feedback for the current flows.
- Updating JavaScript and browser tests where markup, labels, or navigation behavior change.

### Out of scope

- New product features, new scoring rules, text feedback, automated speech assessment, groups, invitations, assignment distribution, or any change to the review-request data model/API.
- Replacing the existing content/photos. The redesign consumes the existing versioned materials and their accessible labels.

## Validation

- Add/adjust JavaScript tests for modified markup and state rendering.
- Add Playwright coverage for landing-to-task selection, visibly persistent photo material during task 2 and task 3, voluntary submission visibility after a complete recording, and teacher workspace navigation/score saving.
- Run `make check` and `make test-e2e` after implementation.
