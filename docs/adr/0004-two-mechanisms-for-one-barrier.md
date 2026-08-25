# ADR 0004: Two mechanisms for one barrier, and the measurements that decided it

**Status:** accepted, 25 August 2026.

## The decision

**A partial index carrying both predicates, behind row level security on the retrieval role.**
Four constructions were measured before any schema was written, and neither of the two chosen is
sufficient alone.

## What was measured

The claim is that a document published after the stated knowing-time cannot be retrieved at all,
rather than retrieved and then discarded. That is a claim about the query plan, so it was checked
against the query plan, as the restricted role, with a query vector shaped like the documents it
is not allowed to see.

| construction | forbidden rows visited | enforced by | verdict |
|---|---|---|---|
| a `WHERE` clause beside the full index | **3** | nothing, it is a convention | fails the claim |
| a partial index on publication only | **3** | index contents, partially | fails once the knowing-time is late enough |
| a partial index carrying both predicates | **0** | index contents | makes the claim literally true |
| row level security alone | **3** read, 0 returned | the database | cannot return one, still reads them |

## Why both

The index is a convention. Nothing stops a later query naming no index, and nothing in the schema
says those rows were forbidden rather than merely unindexed.

The policy is enforcement, and it answers a different question. Asked to prove the retrieval role
cannot read the holdout, the answer is a policy the database applies rather than a query somebody
remembered to write correctly. But **row level security stops rows being returned without
stopping them being read**: with only the publication predicate in the index, the policy still had
to visit three forbidden documents in order to refuse them.

## Two corrections to the spike that designed this

The spike recorded that the partial index produces a plan with "no filter line at all". That is
true of the table owner's query and never of the retrieval role's, because under row level
security the policy predicate is applied on every plan. The measurable claim is the count of
forbidden rows read.

And a partial index keyed on publication alone still admits held-out periods once the
knowing-time is late enough to have published them, which is why the index carries both.

## The test only works because the query is adversarial

Three earlier measurements showed no difference between the constructions, because the nearest
neighbours of an arbitrary question are admissible whatever the index contains. The query vector
has to be the embedding of a document the caller is not allowed to see. An assertion that
everything returned was admissible passes against every one of the four constructions above,
which is exactly how this defect survives review.

## What was rejected

**An exact sequential scan with no approximate index.** Recall is 1.0 by construction and the
claim is still false: it visits every inadmissible row, and in the spike's larger corpus it was
seventy times slower. It fails the claim while paying for the privilege.

## Why a partial index per knowing-time is practical here

It would not be, for arbitrary caller supplied dates. This corpus answers at a declared set of
knowing-times, published in the question set, and a question at an undeclared one is a refusal
the contract already implements. Building one for a knowing-time that is always refused now
raises, because such an index reaches past the end of the corpus and is a superset of every index
that can serve an answerable query.
