# Search evidence and source quality

Goal: fix the observed ambiguous PoE release answer with an unrelated DTF citation, and make real search usage auditable.

Keep the current isolated OpenRouter path and existing Discord-ID permission checks. Do not add Hermes tools or local URL fetching. Ambiguous colloquial PoE release questions get one clarification before any model call. Fresh PoE/Diablo queries restrict search and displayed citations to developer domains. Fresh factual answers require both a positive provider search counter and a suitable citation; otherwise return an explicit inability to verify. This verifies retrieval, not universal factual correctness.

User steering: unqualified «поешечка/поешка/пое» means PoE 2 in this server; explicit PoE 1 overrides the default. Clarify only the requested event, not the slang or default game. Do not mix first-game patch indices with PoE 2 Early Access Patch Notes (/forum/view-forum/2212, verified on the official site).

- [x] Regression tests: screenshot prompt, official-domain filtering, missing/zero usage, rejected DTF/lookalike domains, two-sentence fallback; price/version and mixed factual/joke requests.
- [x] Implement pure search policy, integrate evidence checks and current date, and log delivered-reply audit metadata without conversation contents or credentials.
- [ ] Mocked reply-path tests and real API checks on the test container without publishing Discord messages.
- [x] Full pytest (134 passed), review with no remaining blockers. Live staging found token-budget truncation; add headroom without increasing prose length and reject `finish_reason=length`. Final staging verification follows. No merge or production deployment without a further user instruction.
