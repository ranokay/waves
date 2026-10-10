Closes #<n>.

## Summary

<!-- 1-2 sentences: the problem and the fix. Add a diagram, diff-sketch or tree when it shows the change faster than prose. No background, no log tails. -->

<problem + fix>

## Evidence

<!-- No raw logs, no linked logs: counts and exits are the whole record. Delete lines that do not apply. -->

Tests: <what was added; red/green proof in one clause>

Gate (frozen SHA `<sha>`, no writes since):

- `mise run check` — exit <n>
- `mise run test-strict` — <passed> passed[, <failed> failed (<one-line disposition>)]
- /code-review (standards, spec, correctness) — <n> fixed, <n> refuted
- PR checks — <all green | pending at merge | each failed check with its fix or refutation>
- Bot reviews (advisory) — CodeRabbit, requested: <n fixed, n refuted | no findings | out of quota, skipped, failed or no answer at merge>; each other bot that posted: <same>

Merge stands on the local gate; checks and bot reviews read, none gating.

## Merge Danger

<!-- Door: one-way or two-way. Blast Radius: one word; add a line when the impact is not obvious. -->

**Door:** <one-way or two-way>

**Blast Radius:** <one-word description>
