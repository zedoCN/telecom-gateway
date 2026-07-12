# Contributing

Contributions are welcome. Open an issue before adding support for a new gateway family so that response fixtures and compatibility boundaries can be discussed without exposing device secrets.

Before submitting a pull request:

1. Add or update redacted `httptest` fixtures; never commit live credentials or full device exports.
2. Run `gofmt -w` on changed Go files.
3. Run `go test ./...` and `go vet ./...`.
4. Update both `README.md` and `README-zh-cn.md` when user-facing behavior changes.
5. Keep write operations narrowly scoped and explicitly confirmed.
