# Writing notes that preserve understanding

The consumer is an agent or owner who did not read the earlier conversation. Preserve
what changes their next decision; let the task determine length. These examples explain
content quality, not mandatory extra files or a fixed sequence of reasoning.

## A useful record

```markdown
# Export the complete inventory

<!-- current-state -->
Objective: a complete local inventory, including items on later pages. The user
clarified that a quick sample does not satisfy the request.
Done when: the export covers the server-reported total with no duplicate item IDs.
Known: page 1 returns 50 items, total=137, and a next_cursor (history 10:05).
Hypothesis, not verified: the missing items are on later pages.
Progress: response shape understood; traversal works for page 1 only; no complete
export exists yet.
Next: fetch the next page with its returned cursor and compare IDs.
<!-- /current-state -->

## History
- 10:05 Evidence: evidence/page-1.json — total=137, 50 unique IDs, next_cursor present.
- 10:12 Correction: treating page 1 as the full result was wrong (page-1.json and the
  user's clarification). Keep total and cursor in view; a successful request is not coverage.
- 10:20 Evidence: page_size=500 still returned 50 items (evidence/page-size-check.txt).
  Do not repeat under this API version; revisit only if the documented limit changes.
```

The current state says what is true now and what to do next. It labels the hypothesis
as unverified and does not claim the unfinished collector works. History keeps the
evidence and the rejected attempt with the condition that would justify revisiting it.
If the server changes, recheck that premise instead of treating the old lesson as a
permanent prohibition.

## Research and design also make progress

An exploratory task may have no implementation steps yet. Track the question being
resolved, conclusions supported so far, live alternatives, and the evidence that would
distinguish them:

```markdown
<!-- current-state -->
Objective: choose a local document search approach that preserves exact identifiers.
Supported so far: exact-match retrieval is necessary; semantic retrieval may supplement
it. Not established: that a vector-only design meets the requirement.
Open: does a combined approach recover the paraphrase misses without losing exact IDs?
Next: run both query types on the same held-out documents and inspect the actual hits.
<!-- /current-state -->
```

A new agent should run the outstanding comparison rather than restart a broad tool
survey. Keep the source documents and evaluation queries reachable from History.

## Maintain an existing document

If `documents/search/THOUGHTS.md` already owns an inquiry, read it with `read --file`,
wrap its `## Current position` body in the current-state markers once, and keep that
section current: the supported judgment, the unsettled comparison, the next observation
and the result location. Leave its research evidence and other sections in their own
structure; do not create `tasks/search.md` or insert the standalone template. No
companion Skill is required to maintain either form.

If `.goals/export.goal.md` owns execution state, edit only `## Carry-over`, for example:

```markdown
## Carry-over
Read this before acting; update it from current evidence before finishing.
### State
- A1 remains unverified: the fixture export has 50 of 137 items (evidence/page-1.json).
### Lessons
- A successful request does not establish coverage; reconcile the server total.
### Next
- Follow next_cursor, then compare the exported IDs and total against the fixture.
```

Leave Intent, Boundary, Anchor, Stop condition, Verification, Acceptance requirement
text and labelled Means declarations intact. Use the goal's existing confirmation
process for requested changes; state maintenance grants no authority to change them.
UltraGoal recovers its own goal; finish and retain the goal under its own lifecycle and
never archive it as a task record.

If `tasks/export.md` already owns a longer milestone, keep it in place when a goal
starts. The goal carries its accepted scope and a locator to that record; update the
record's current state and history there. A reference must resolve to actual content,
not another reference back to the goal. Select one recovery provider independently of
where the state lives; manual reading does not activate a hook.

## Avoid semantic loss during updates

| Weak record | Useful replacement |
|---|---|
| Fixed; next run tests | Edit landed; required verification remains; step is in progress |
| This approach does not work | The approach failed under these conditions, with this evidence |
| User wants a database | User wants reliable retrieval; a database is our proposed means |
| Need to be more careful | We mistook a page for the full dataset; check total and cursor next |
| Investigated the issue | State what is now known, excluded, or still unresolved |
| Continue implementation | Name the outstanding result and the next concrete action |

Do not fabricate reasons that were never established. A reflection is a revisable
interpretation of evidence, not proof of its own correctness. Preserve a user correction
as a correction instead of silently rewriting history to make the original plan seem right.

Keep the current state short by removing what is no longer true or no longer steers
work, with the reason appended to History. Do not summarize History into the current
state; repeatedly summarizing a summary drops qualifications and turns tentative ideas
into facts. Move bulky evidence into referenced artifacts. At context pressure, save the
current unresolved question and evidence before starting another investigation.

## Check the receiver, not just the file

After a context reset or handoff, the receiver should be able to explain the outcome,
current judgment and evidence, completed versus unfinished work, and the next uncertainty
to resolve. Then observe whether execution actually continues from there. A different
valid approach is acceptable when explained by new evidence; matching the old prose or
blindly preserving an old decision is not the objective.

For evaluation, compare against the previous Skill using the same task and available
artifacts. Include user corrections, misleading early hypotheses, failed attempts,
partial implementation, an authorization that changes mid-task, and an interrupted
verification. Inspect final artifacts, stale statements in the delivered current state,
unsupported claims, repeated work, recovery effort, and total task cost. A single fresh
context pass provides evidence about that case; it is not proof of every host lifecycle.
