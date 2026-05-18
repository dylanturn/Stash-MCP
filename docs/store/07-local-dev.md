# 07 — Local dev stack

Dev and CI run against [RustFS](https://github.com/rustfs/rustfs)
in docker-compose rather than a real cloud bucket. RustFS is
Apache-2.0 licensed, exposes the S3 API surface (subject to the
implementation matrix below), and sits next to the existing
`dex` and `postgres` services without introducing a heavier
dependency.

## Compose service

```yaml
# docker-compose.yml (additions)
services:
  rustfs:
    image: rustfs/rustfs:1.0.0          # see "version pin" below
    container_name: stash-rustfs
    environment:
      RUSTFS_ACCESS_KEY: ${RUSTFS_ACCESS_KEY:-stash-dev}
      RUSTFS_SECRET_KEY: ${RUSTFS_SECRET_KEY:-stash-dev-secret}
      RUSTFS_VOLUMES: /data
    volumes:
      - rustfs-data:/data
    ports:
      - "9000:9000"                     # S3 API
      - "9001:9001"                     # web console
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/health"]
      interval: 10s
      timeout: 3s
      retries: 5

  rustfs-bootstrap:
    image: amazon/aws-cli:2
    depends_on:
      rustfs:
        condition: service_healthy
    environment:
      AWS_ACCESS_KEY_ID: ${RUSTFS_ACCESS_KEY:-stash-dev}
      AWS_SECRET_ACCESS_KEY: ${RUSTFS_SECRET_KEY:-stash-dev-secret}
      AWS_EC2_METADATA_DISABLED: "true"
    entrypoint: >
      sh -c "aws --endpoint-url http://rustfs:9000 s3api create-bucket
             --bucket stash || true &&
             aws --endpoint-url http://rustfs:9000 s3api put-bucket-versioning
             --bucket stash --versioning-configuration Status=Enabled"

volumes:
  rustfs-data:
```

The `rustfs-bootstrap` one-shot creates the `stash` bucket and
turns on object versioning (the bucket-level backstop mentioned
in [02-data-model.md § S3 layout](./02-data-model.md#s3-layout)).
It's idempotent — re-running the compose stack is a no-op against
an existing bucket.

## Application config

```dotenv
# .env additions
STASH_S3_ENDPOINT_URL=http://rustfs:9000
STASH_S3_BUCKET=stash
STASH_S3_ACCESS_KEY=stash-dev
STASH_S3_SECRET_KEY=stash-dev-secret
STASH_S3_REGION=us-east-1                # required by SDK, value ignored by RustFS
STASH_S3_FORCE_PATH_STYLE=true           # rustfs uses path-style addressing
```

## Version pin

Pin to a RustFS release that includes the s3s v0.12.0-rc.5
upgrade (which made ETag strongly typed and fixed the
conditional-PUT / conditional-GET behaviour discussed in
[#791](https://github.com/rustfs/rustfs/issues/791)). The dedup
strategy doesn't depend on conditional PUT for correctness (see
[03-commit-protocol.md § Dedup strategy](./03-commit-protocol.md#dedup-strategy)),
but keeping it as defense-in-depth means we want the bug-free
version. Update the pin in lockstep with RustFS GA — `latest` is
not acceptable in compose because RustFS is still pre-1.0 and
breaking changes are still landing.

## Production targets

Same env var surface — point `STASH_S3_ENDPOINT_URL` at AWS S3,
R2, or a self-hosted RustFS cluster as appropriate. The
application code does not branch on the target; differences are
absorbed by the S3 SDK and the dedup design (which avoids
depending on backend-specific features).

## S3 implementation matrix

Tracks which S3 features the design uses and which targets we've
verified for each. "Required" means the code path doesn't work
without it; "defense in depth" means we use it if available but
correctness doesn't depend on it.

| Feature                   | Required?        | RustFS (dev)                                                                                  | AWS S3 (prod)                   | R2 |
| ------------------------- | ---------------- | --------------------------------------------------------------------------------------------- | ------------------------------- | -- |
| `PutObject`               | Required         | ?                                                                                             | ?                               | ?  |
| `GetObject`               | Required         | ?                                                                                             | ?                               | ?  |
| `DeleteObject`            | Required         | ?                                                                                             | ?                               | ?  |
| `HeadObject`              | Required         | ?                                                                                             | ?                               | ?  |
| `ListObjectsV2`           | Required         | ?                                                                                             | ?                               | ?  |
| Multipart upload          | Required         | ?                                                                                             | ?                               | ?  |
| `If-None-Match: *` on PUT | Defense in depth | ✓ (per [issue #791 resolution](https://github.com/rustfs/rustfs/issues/791), s3s v0.12.0-rc.5) | ✓ (AWS launched Nov 2024)       | ?  |
| Object versioning         | Backstop         | ?                                                                                             | ?                               | ?  |
| Path-style endpoint       | Required for dev | ?                                                                                             | ?                               | ?  |

Only the two cells with explicit citations are verified. Every
`?` is a thing to confirm before relying on it — either by
reading the target's documentation and updating the cell to ✓
*with a citation*, or by writing a smoke test that exercises the
feature against the target and linking the test from the cell.
Cells without citations stay `?` no matter how plausibly the
target "should" support the feature.

This matrix is **load-bearing** — adding a new target means
walking each row and confirming. Don't extend it by assumption.
