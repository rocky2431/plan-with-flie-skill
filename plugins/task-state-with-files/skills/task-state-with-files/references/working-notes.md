# Writing notes that preserve understanding

The consumer is an agent or owner who did not read the earlier conversation. Preserve
what changes their next decision; let the task determine length. These examples explain
content quality, not mandatory extra files or a fixed sequence of reasoning.

## A useful checkpoint

```markdown
## Current understanding

Intent: Generate a complete local inventory, including items on later pages.
The user clarified that a quick sample does not satisfy the request.
Completion: The export covers the server-reported total, with no duplicate item IDs.

Observed: The first response contains 50 items, total=137, and a next_cursor (E1).
Hypothesis: The missing items are on subsequent pages; not yet verified by traversal.
Approach: Follow the server cursor and reconcile IDs against the total.

- S1 done: identify response shape; evidence E1.
- S2 in_progress: implement traversal; first page works, later pages unverified.
- S3 pending, depends on S2: verify all 137 items and write the final export.

Next action: Fetch the next page using its returned cursor and compare IDs.

## Judgments and corrections

- The initial interpretation treated the first page as the complete result.
  E1 and the user's clarification invalidate that interpretation. Preserve the
  total and cursor through every checkpoint; a successful request is insufficient.
- Increasing page_size returned the same 50-item cap (E2). Under this API version,
  do not repeat that attempt. Revisit only if the documented limit changes.

## Evidence and artifacts

- E1: evidence/page-1.json; response total=137, 50 unique IDs, next_cursor present.
- E2: evidence/page-size-check.txt; tested page_size=500, response still 50 items.
- collector.py: traversal implementation is incomplete; no complete export exists.
```

This checkpoint preserves intent, partial progress, a hypothesis, a rejected approach,
and the evidence needed to continue. It does not label the hypothesis as proven or
claim the unfinished collector works. If the server changes, recheck the relevant
premise rather than treating the old lesson as a permanent prohibition.

## Research and design also make progress

An exploratory task may have no implementation steps yet. Track the question being
resolved, conclusions supported so far, live alternatives, and the evidence that would
distinguish them. For example:

```markdown
Intent: Select a local document search approach that preserves exact identifiers.
Known: Keyword search retrieved exact IDs in the sample; paraphrased questions missed
two relevant documents (E3). This is a sample result, not a general ranking.
Current judgment: Exact-match retrieval is necessary; semantic retrieval may supplement
it. We have not established that a vector-only design meets the requirement.
Open: Does a combined approach recover the misses without losing exact-ID results?
Next: Test both query types on the same held-out documents and inspect the actual hits.
```

A new agent should run the outstanding comparison rather than restart a broad tool
survey. Keep the source documents and evaluation queries reachable through E3.

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

When the note grows, keep the current understanding readable and move bulky evidence
to referenced artifacts. Merge redundant historical entries, retaining the reason for
important reversals. Update affected passages locally; repeatedly summarizing a summary
can drop qualifications and turn tentative ideas into facts. At context pressure, save
the current unresolved question and evidence before starting another investigation.

## Check the receiver, not just the file

After a context reset or handoff, the receiver should be able to explain the outcome,
current judgment and evidence, completed versus unfinished work, and the next uncertainty
to resolve. Then observe whether execution actually continues from there. A different
valid approach is acceptable when explained by new evidence; matching the old prose or
blindly preserving an old decision is not the objective.

For evaluation, compare against the previous Skill using the same task and available
artifacts. Include user corrections, misleading early hypotheses, failed attempts,
partial implementation, and an interrupted verification. Inspect final artifacts,
unsupported claims, repeated work, recovery effort, and total task cost. A single fresh
context pass provides evidence about that case; it is not proof of every host lifecycle.
