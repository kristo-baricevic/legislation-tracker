# Committees page

Approved layout: a Committees navbar destination, with each committee's name and chamber above two horizontal rows. First: circular member avatars with leadership indicators (Chair, Vice Chair, Ranking Member). Second: the existing bill cards for bills introduced by those members. Names appear in avatar tooltips. Avatars link to representative profiles; cards link to bill details.

Include House, Senate and Joint committees, with a chamber filter. Use the current Congress for both memberships and bills. Do not confuse members' sponsorship with referral to a committee. Include subcommittees with parent context in their heading.

## Approach

Reuse the stored Committee/CommitteeMembership models and existing avatars, tooltips and bill cards. Extend the public committee endpoint with scoped member data and a paginated introduced-bills action. This avoids new ingestion work and one network lookup per avatar. A standalone visualization or new card system would duplicate existing UI without improving the requested layout.

## Constraints

- Keep copy minimal; no explanatory paragraphs or raw metadata.
- Leadership labels come from stored roles, never inferred from membership rank.
- Bills are distinct primary-sponsored bills, not cosponsored bills, from the same Congress.
- Load committee sections incrementally and bill pages on horizontal approach to the end.
- Preserve row geometry and existing items during loading, retries and filtering.
- Use initials for missing portraits. Support keyboard navigation and mobile horizontal scrolling.
- Only render known records; show a brief empty state when rosters or bills are unavailable.
- No paid API calls, data deletion, new dependencies or subagents.

## Verification

Test chamber/Congress isolation, role indicators, deduplicated sponsored bills, stable pagination, retry behavior and accessible links. Verify desktop and mobile in the Docker app at localhost:13000.
