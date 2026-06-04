## Description

<!-- Link to exactly ONE issue this PR addresses. PRs addressing multiple issues will be rejected. -->

Closes #

## Acceptance Criteria Verification

<!-- Check every box below. If a criterion doesn't apply, explain why. -->

- [ ] Every acceptance criterion in the linked issue is met (list them below)
- [ ] No acceptance criteria from the linked issue were silently dropped or deferred
- [ ] This PR addresses exactly one issue — it does not bundle unrelated changes

### Acceptance Criteria Checklist

<!-- Copy each acceptance criterion from the linked issue and confirm it's fulfilled. Add rows as needed. -->

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | | ✅ / ❌ | |
| 2 | | ✅ / ❌ | |

## Quality Checks

- [ ] Tests pass: `pytest -q -m "not slow"`
- [ ] Lint passes: `ruff check scripts/ tests/`
- [ ] All new code has test coverage (happy path + error cases)
- [ ] No `TODO`, `FIXME`, `HACK`, `XXX`, or debug `print()` left in code
- [ ] No dead code or commented-out blocks
- [ ] Functions are focused (single responsibility) — no 200+ line functions
- [ ] Public APIs and new CLI flags are documented (README or docstrings)
- [ ] SQL queries use parameterized statements (`?` placeholders) — no f-string SQL

## Security Checks

- [ ] No hardcoded credentials, API keys, tokens, or secrets
- [ ] No real names, personal emails, or identifying information in code or comments
- [ ] All network requests validate URL scheme (`https://` only, no `file://`/`ftp://`)
- [ ] All user-supplied values are validated or sanitized before use
- [ ] No SSRF vectors: webhook URLs, RPC URLs, or similar are validated
- [ ] Rate limiting or cooldown applied where repetitive external calls are possible

## Review Criteria

Reviewers should prioritize the following when evaluating this PR:

- **Correctness:** Does the code do what the linked issue specifies?
- **Security:** Are there any injection, SSRF, or credential-leak vectors?
- **Resilience:** Are error paths handled gracefully (no silent crashes)?
- **Test coverage:** Are edge cases covered?
- **Scope discipline:** Does the PR touch only files relevant to the linked issue?
