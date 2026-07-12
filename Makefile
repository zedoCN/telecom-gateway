.PHONY: build test check

build:
	go build -o bin/ctgw ./cmd/ctgw

test:
	go test ./...

check:
	gofmt -w $$(find . -name '*.go' -not -path './vendor/*')
	go test ./...
	go vet ./...
