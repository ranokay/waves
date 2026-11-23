Closes #<n>.

## Summary

<!-- 1-2 sentences: the problem and the fix. Add a diagram, diff-sketch or tree when it shows the change faster than prose. No background, no log tails. -->

<problem + fix>

## Evidence

<!-- No raw logs, no linked logs: commands, exits and counts are the whole record. Delete lines that do not apply. -->

Change class: <prose | isolated logic | full gate | release or native>

Tests: <what was added; red on base and green at head, or the stated limitation>

Gate (head `<sha>`, no writes since):

- `mise run check`: exit <n>
- <test command>: <passed> passed[, <failed> failed (<one-line disposition>)]
- Review: <`/code-review` for substantive code, or none for prose>; <n> fixed, <n> refuted
- PR checks: <all green | pending at merge | each failed check with its fix or refutation>
- Qualification gaps: <platform, native, live account or pending case; "none" when none>

## Merge Danger

<!-- Door: one-way or two-way. Blast Radius: one word; add a line when the impact is not obvious. -->

**Door:** <one-way or two-way>

**Blast Radius:** <one-word description>
