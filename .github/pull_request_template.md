Closes #<n>.

<!-- 1-2 sentences: the problem and the fix. No background, no log tails. -->

<problem + fix>

<!-- Only if tests were added or the fix needs proof; delete otherwise. -->

Tests: <what was added; red/green proof in one clause>

Gate (frozen SHA `<sha>`, no writes since):

- `mise run check` — exit <n>
- `mise run test-strict` — <passed> passed[, <failed> failed (<one-line disposition>)]
- OpenCodeReview — <n> findings; /code-review — <n> fixed, <n> refuted

Merge stands on the local gate; checks read, not awaited.
