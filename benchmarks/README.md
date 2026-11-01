# Citation quality trends

Run `uv run python scripts/citation_benchmark.py > /tmp/citation-quality.jsonl`
with an explicitly configured model endpoint. This is opt-in and never required
by CI. It runs each pinned case three times. Compare releases using the same
model, settings, fixtures, and repetition count. Record package and parser
versions alongside the results (`uv pip freeze`). Source fixture hashes are
checked before execution. HTTPX 0.28.1's `_client.py` is copied verbatim from the
published wheel; its BSD license accompanies the fixture.

Hit rate means all expected definition regions were touched. Symbol recall is
the fraction touched; tightness is expected/cited unique line intersection over
cited unique lines (null for empty answers). Report these together: tightness
alone can reward incomplete answers. Bytes measure UTF-8 snippets and serialized
results separately. Timing includes the model; unit tests measure deterministic
structure without calling an endpoint.
