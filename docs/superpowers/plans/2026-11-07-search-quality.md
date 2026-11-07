# Universal search quality and private dialogue

Goal: answer information requests across topics with usable private context and auditable evidence, retaining Discord-ID permissions and short replies.

One existing OpenRouter web_search route handles every topic. The model resolves the current question using up to four private Q/A pairs and decides between chat, clarification, fact and not_found. It returns internal JSON with answer, selected source URL and a verbatim supporting quote. For facts, code requires a positive provider search counter, a safe URL present in current annotations, and a normalized exact quote in that source's title/excerpt. No fabricated link, topic-specific source allowlists, keyword freshness router, or local URL fetching. Slang such as «поешечка = PoE 2» is persona knowledge only.

Dialogue is bounded by SDK guild/channel/author, TTL15min, capacity128; no channel backfill or source pages in memory. Authorization precedes context access. Store only delivered turns, redact known profile secrets before model/memory/output/logs. The model gets no Hermes tools, files or terminal. Logs record provider counts, evidence length, delivery shape and rejection reason, not conversation text or credentials.

The model chooses sources and semantic support; exact-quote checks verify retrieval provenance, not universal factual truth. Native JSON response format was validated on a real Python-version query, outside gaming.

- [x] Replace the game router with universal JSON/evidence validation and generic bounded private dialogue.
- [x] Regressions for arbitrary topics, quote/source mismatch, malformed/truncated output, credentials, user/channel/guild isolation and TTL/bounds.
- [x] Full pytest (139 passed) and independent review without remaining findings. Secret redaction precedes formatting/truncation, with a dotted-token regression.
- [ ] Real API checks on test: unrelated topics and a conversational follow-up, no Discord test posts.
- [ ] Update PR32 and staging deployment. No merge or production deployment without further user instruction.
