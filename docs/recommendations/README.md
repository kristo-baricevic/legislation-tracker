# Explicit-follow recommendations

Implemented on the verified dashboard baseline `4c5302bcbd36c19fb1d04dcb1c4adb27fe38b4f7` using the existing Django/DRF/PostgreSQL and Next/React stack. There are no new dependencies, migrations, external recommendation services, embeddings, or model API calls. The approved specifications contain the source investigation and preimplementation decisions:

- [Bill discovery specification](../superpowers/specs/2026-10-10-follow-recommendations-design.md)
- [Representative activity and discovery specification](../superpowers/specs/2026-10-10-representative-topic-recommendations-design.md)
- [Integration contracts and source review map](INTEGRATION.md)
- [Evaluation, independent review, and measured limits](EVALUATION.md)

The dashboard has a separate, reversible browser preference, `legislation-tracker-recommendations`. Only the exact stored value `true` enables it; the default is off. “Show recommendations on this browser” enables bill and representative rows inside the card dashboard. Disabling it removes the rows and closes only a recommendation-owned bill dialog. The existing card dashboard rollback remains available. Near-white cards, off-white surfaces, and muted navy/burgundy/green bars use a dedicated CSS module.

## Research catalog

The cited works support architectural choices, not claims that these provisional weights improve recommendation quality. Original papers were read except the Pazzani/Billsus publisher abstract, whose limited access is explicit here.

| Original source | Adopted or deferred | Application and limitation |
| --- | --- | --- |
| [Pazzani and Billsus, Content-Based Recommendation Systems (2007)](https://link.springer.com/chapter/10.1007/978-3-540-72079-9_10), DOI 10.1007/978-3-540-72079-9_10 | Adopted architectural principle; publisher abstract only | Item metadata is compared with a profile derived from explicit follows. No claim to reproduce their models or experimental results. |
| [Sarwar et al., Item-Based Collaborative Filtering Recommendation Algorithms (WWW 2001)](https://files.grouplens.org/papers/www10_sarwar.pdf), DOI 10.1145/371920.372071 | Deferred | The repository does not establish adequate behavioral density or evaluation data. No cofollow matrix, cross-user similarity, or collaborative inference is introduced. |
| [Linden, Smith and York, Amazon.com Recommendations: Item-to-Item Collaborative Filtering (2003)](https://www.cs.umd.edu/~samir/498/Amazon-Recommendations.pdf), DOI 10.1109/MIC.2003.1167344 | Adopted candidate/ranking separation only; collaborative technique deferred | A bounded metadata candidate pool precedes ranking. This implementation does not use Amazon's item-to-item behavioral method or reproduce its scalability claims. |
| [Carbonell and Goldstein, The Use of MMR, Diversity-Based Reranking for Reordering Documents and Producing Summaries (SIGIR 1998)](https://www.cs.cmu.edu/~jgc/publication/The_Use_MMR_Diversity_Based_LTMIR_1998.pdf), DOI 10.1145/290941.291025 | Adapted | Greedy relevance-minus-redundancy selection uses exact bill topic/sponsor similarity or representative topic-vector similarity. The 0.9/0.1 tradeoff is local provisional policy. |
| [McNee, Riedl and Konstan, Being Accurate Is Not Enough: How Accuracy Metrics Have Hurt Recommender Systems (CHI 2006)](https://grouplens.org/site-content/uploads/accurate-CHI-20061.pdf), DOI 10.1145/1125451.1125659 | Adopted evaluation caution | Future evaluation must include coverage, useful discovery, diversity, explanations, and user feedback. Passing correctness tests does not demonstrate recommendation usefulness. |
| [Wilson, Probable Inference, the Law of Succession, and Statistical Inference (1927)](https://www.jhanley.biostat.mcgill.ca/c607/ch08/wilson_jasa_1927.pdf) | Rejected for current activity scoring | Incomplete ingestion and related/reintroduced bills do not establish independent binomial trials. The evidence discount below is a heuristic, not a statistical confidence interval. |

The [House's bill/resolution taxonomy](https://www.house.gov/the-house-explained/the-legislative-process/bills-resolutions) informs separate observed resolution counts. Official [Clerk passage evidence](https://clerk.house.gov/Votes/2026295) informs the strict passage-question/source treatment. Roll-call support is displayed as factual evidence with explicit missing coverage; it never contributes to ranking.

## Bill algorithm: `explicit-facets-mmr-v1`

Only persisted `TrackedTopic`, `TrackedLegislator`, and `TrackedBill` records contribute. A temporary search, dashboard filter, saved search, party, state, or jurisdiction selection does not become a followed interest. Followed bills are explicit seed items, whose metadata receives less weight than directly followed topics/representatives. No interest is inferred from ideology, party, demographic data, or voting persuasion.

A usable topic edge has a nonfallback topic and either null confidence or strictly positive finite confidence. Zero, negative, NaN, infinity, and `general-legislation` are excluded. Confidence is an eligibility check, not a probabilistic weight.

For each candidate, use the strongest match within each facet:

- `T = 100` for any directly followed topic; otherwise `35` for a usable topic on a followed bill; otherwise `0`.
- `R = 100` for a followed sponsor; otherwise `75` for an active, nonwithdrawn followed cosponsor; otherwise `35` for a sponsor of a followed bill; otherwise `0`.
- `D = 60 × has_topic_interest + 40 × has_representative_or_seed_sponsor_interest`.
- `cross = min(T,R)` when both profile facets exist; otherwise `0`.
- `N = 4 × (60T + 40R) + D × cross`; `S = N / (500D)`.

Normalization depends on available profile facets; a candidate missing a configured facet earns no match for it. A single explicit facet scores 0.8. With both profile facets present, topic plus followed sponsor scores 1.0, topic plus active followed cosponsor 0.87, topic alone 0.48, sponsor alone 0.32, and two seed-derived facets 0.35. Additional matching topics or representatives within one facet do not add weight. Explanations show at most the strongest topic and representative relationship, with the followed seed bill named when applicable.

Eligibility is already-ingested federal/state bills with positive session and nonblank title/number, at least one usable interest match, and exclusion of every bill the requesting user follows. This introduces no ingestion work and no arbitrary current-Congress restriction. Before diversity, tie order is score numerator descending, last action descending/null last, introduction descending/null last, then bill ID ascending. Freshness acts as a deterministic tie break, not an unproven relevance feature.

The query fetches at most 501 candidates, retains the first 500, then batches topic and active-followed-cosponsor metadata. Greedy MMR selects at most 60: `0.9 × S - 0.1 × maximum_similarity_to_selected`. Similarity is `0.7 × topic Jaccard + 0.3 × same_known_sponsor`. Empty topic sets and missing sponsors contribute zero. Exact fractions decide rankings; a six-decimal score is diagnostic only. MMR ties use the original base order. Candidate truncation and ranking limits are disclosed in the DTO.

## Public activity and representative discovery

Activity uses a visibly independent rolling 24-month calendar window in `America/New_York`, captured once. Bill introduction and dated active cosponsorship are separate channels. Year-derived terms do not justify exact service exposure: `service_days` and `monthly_rate` remain null. Congress January 3 boundaries attribute missing dates to uncertainty counts only, never invented service rates.

Each bill distributes topic mass `1/k` across its `k` usable tags. Untagged bills remain in denominators. Possible repeated proposals are conservatively grouped by NFKC/casefold/whitespace-normalized identical title and known sponsor. Across all group members, each topic retains the minimum original weight; missing tags contribute zero, with no renormalization. Unknown sponsors keep distinct bill identities. Raw and grouped observations, exact fraction masses, tag coverage, missing dates, withdrawn observations, and examples remain visible. This heuristic does not establish legislative bill families.

The default recurring-activity label requires **both** raw and grouped evidence to meet 20 observations, 5 topic observations, at least 20% topic share, and at least 80% tag coverage. Up to five recurring topics are labeled; other observations remain available. Sparse history stays labeled insufficient. Defaults are versioned policy, not empirical thresholds proved by research.

Passage evidence first selects the latest allowlisted passage roll per bill/chamber, including a latest unknown source/position as uncertainty rather than falling back to an older known yes. Then the latest actual member record across chambers represents that member/bill. Cross-chamber history is marked. Yes/no, present, not voting, other, and missing/uncertain remain separate; uncertain-only topic records are retained with null yes rate. No absent member record manufactures eligibility. Examples use validated actual persisted document/vote source links or null.

For representative discovery, sponsor and active-cosponsor grouped topic vectors have weights 0.6/0.4, normalized only over channels with observations. Untagged observations reduce mass. Explicit followed topics and the equal average of eligible followed-representative vectors form the request profile; followed-bill metadata is not used for this separate row. A reference needs at least 5 tagged union evidence units. Current, unfollowed candidates need at least 5 union units, 3 matched units, and positive overlap. Former followed representatives can remain references.

Let `T` be candidate vector mass on explicit followed topics and `C` be cosine similarity to the mean reference vector. With active-facet indicators `aT/aC`, `base = 0.8 × (0.7T + 0.3C)/(0.7aT + 0.3aC) + 0.2 × min(T,C)`; the crossover term is zero unless both facets exist. `E = tagged_union_units/(all_union_units + 20)`. The score is `base × E`, half-even quantized to millionths. `E` is an evidence discount, not confidence or probability. Greedy 0.9/0.1 MMR uses maximum topic-vector cosine to select five. Ties use score, explicit matched-topic count, tagged evidence count, Bioguide ID, then numeric ID. Reasons cite actual shared topic/channel evidence; votes, party, and voting agreement contribute zero ranking weight.

## API consistency, privacy, and failures

`GET /api/tracking/recommendations/` accepts only optional `page_size` (1–12; default 6) and `cursor`. The initial request captures the persisted profile and ranking in a PostgreSQL read-only repeatable-read transaction. A bounded per-user cache entry stores up to 60 cards for 300 seconds, with profile fingerprint and random snapshot nonce. Signed cursors bind user, nonce, offset, and page size. Continuation rereads the profile and page eligibility in the same isolation level, then checks that the cache slot still belongs to that nonce. Other users' cursors are 400, including expired ones; a changed profile/replaced snapshot is 409; an expired owned snapshot is 410. Newly ingested candidates do not silently reorder an existing page sequence. Refresh starts a new snapshot.

`GET /api/tracking/representative-recommendations/` accepts no query parameters. It reads the requester's explicit follows consistently, then uses a public catalog captured within five minutes. `GET /api/representatives/{id}/topic-activity/` is a public, strict-no-query profile integration route supplied by the separately reviewed profile branch.

Personalized responses and handled errors are private/no-store, vary on cookies and authorization, require authentication, and use existing DRF throttling at 30 requests/minute per endpoint. The bill snapshot is capped at 1 MiB; the public activity catalog at 16 MiB of strict compact JSON. Cache/database failures or overbound results return 503 with Retry-After rather than partial/truncated evidence. The catalog has a best-effort 30-second cache-add build gate, a cooperative 20-second deadline, PostgreSQL statement timeouts, and ownership validation before publication. This uses existing cache infrastructure; cross-process single-flight requires that deployment's cache backend to support shared atomic add. Large production corpus resource costs remain a measured limitation.

Client requests capture both session and interest generations plus an AbortSignal. Checks occur after CSRF, before unsafe POST/refresh/replay, and after responses/JSON. A changed generation cancels the old request's ability to refresh or replay into another account. Scope-owned shared refresh lets other current callers finish when one UI caller aborts. Successful follow/unfollow changes synchronously clear cards/cursors and private tracking, then refetch. Login/logout transitions clear private UI immediately; abandoned cross-tab transitions expire. Browser storage carries only opaque change epochs and the feature preference, never private recommendation payloads, cursors, identity, or JWTs. Focus and storage events revalidate; blocked storage retains same-tab guards.

Empty DTOs distinguish no follows, unsupported follows only, insufficient metadata, and no matching ingested items. The broad general-legislation follow is explicitly unsupported rather than matching everything. Loading, error/retry, refresh, empty, sparse evidence, and auth states have dedicated UI. Public bill content remains open through personalized revalidation unless its dialog belongs to the recommendation row. Keyboard focus moves to a persistent heading when a followed card disappears; final combined profile-stack restoration must be verified after integration.
