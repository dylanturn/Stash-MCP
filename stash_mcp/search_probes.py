"""Calibration probes for the search noise floor.

A cosine similarity means nothing on its own: unrelated text scores around 0.65
against one embedding model and 0.25 against another, and code-like input sits
higher than a plain question. To judge a result the engine needs to know what
*unrelated* input scores against this particular index, so it runs the probes
below — text chosen to be about nothing any one store is likely to hold — and
takes a robust upper bound of their best matches (see
``SearchEngine.noise_floor``).

Two sets, because the two kinds of input have different baselines:

* ``QUESTION_PROBES`` — short natural-language queries, the shape an agent
  types into ``search_content``.
* ``TEXT_PROBES`` — raw working text (command output, logs, diffs, source),
  the shape a caller passes when asking "is anything in the store related to
  what I am looking at?".

The sets span many unrelated domains on purpose. A store will be on-topic for
a few of them; the floor is median-based so those few do not move it.
"""

QUESTION_PROBES: tuple[str, ...] = (
    "how long should sourdough proof at room temperature",
    "what is the statute of limitations for breach of contract in California",
    "symptoms and treatment of iron deficiency anemia",
    "how do React hooks manage component state",
    "compare fixed rate and adjustable rate mortgages",
    "training plan for a first marathon",
    "causes of the fall of the western Roman empire",
    "when to prune tomato plants",
    "best time of year to visit Kyoto",
    "circle of fifths and key signatures",
    "PostgreSQL autovacuum tuning for large tables",
    "AWS reserved instance billing explained",
    "GDPR data subject access request deadlines",
    "how does photosynthesis convert light into chemical energy",
    "French subjunctive conjugation rules",
    "quarterly estimated tax payments for freelancers",
    "configuring a Shopify discount code",
    "Rust borrow checker lifetime errors",
    "Go generics type constraints",
    "Redis eviction policies",
    "OAuth PKCE authorization code flow",
    "Terraform remote state locking",
    "SwiftUI navigation stack",
    "Unity shader graph basics",
    "LaTeX multi-row tables",
    "Excel pivot table grouping by month",
    "Stripe webhook signature verification",
    "Kafka consumer group rebalancing",
    "CSS grid template areas",
    "proof of stake consensus finality",
    "AlphaFold protein structure prediction",
    "quantum error correction surface codes",
    "battle of Midway timeline",
    "how to negotiate a salary offer",
    "kubernetes ingress TLS termination with cert-manager",
    "watercolor wet on wet technique",
    "difference between baking soda and baking powder",
    "how do vaccines train the immune system",
    "chess opening theory for the Sicilian defense",
)

TEXT_PROBES: tuple[str, ...] = (
    (
        "npm warn deprecated inflight@1.0.6: This module is not supported, and leaks "
        "memory.\n"
        "added 1423 packages, and audited 1424 packages in 41s\n"
        "212 packages are looking for funding\n"
        "8 vulnerabilities (2 low, 6 moderate)"
    ),
    (
        "============================= test session starts =============================\n"
        "collected 623 items\n"
        "tests/test_api.py ....................................                   [  5%]\n"
        "tests/test_search.py ...................................F....            [ 61%]\n"
        "FAILED tests/test_search.py::TestOnnxBackendWiring::test_unknown_provider - "
        "NameError"
    ),
    (
        "NAME                         READY   STATUS             RESTARTS   AGE\n"
        "traefik-7d9c6b5f4-x2k8p      1/1     Running            0          12d\n"
        "longhorn-manager-4hw9z       1/1     Running            3          40d\n"
        "grafana-5c8d7b6f9d-qplm2     0/1     CrashLoopBackOff   17         3h"
    ),
    (
        '{"coord":{"lon":-0.13,"lat":51.51},"weather":[{"id":300,"main":"Drizzle",'
        '"description":"light intensity drizzle"}],'
        '"main":{"temp":280.32,"pressure":1012,"humidity":81}}'
    ),
    (
        "FROM node:20-alpine AS build\n"
        "WORKDIR /app\n"
        "COPY package*.json ./\n"
        "RUN npm ci\n"
        "COPY . .\n"
        "RUN npm run build"
    ),
    (
        ".card { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, "
        "1fr)); gap: 16px; }\n"
        ".card__title { font-weight: 600; color: var(--text-primary); }"
    ),
    (
        "Running migration 0042_add_invoice_status... OK\n"
        "Running migration 0043_backfill_customer_region... OK\n"
        "ALTER TABLE invoices ADD COLUMN status varchar(16) NOT NULL DEFAULT 'draft';"
    ),
    (
        "error[E0502]: cannot borrow `self.items` as mutable because it is also borrowed "
        "as immutable\n"
        "  --> src/cart.rs:48:9\n"
        "   |\n"
        "46 |     let first = &self.items[0];\n"
        "48 |     self.items.push(item);"
    ),
    (
        "Plan: 3 to add, 1 to change, 0 to destroy.\n"
        "  # aws_s3_bucket.assets will be created\n"
        "  # aws_iam_role.lambda_exec will be updated in-place"
    ),
    (
        "export function InvoiceTable({ rows }: Props) {\n"
        '  const [sort, setSort] = useState<SortKey>("dueDate");\n'
        "  const sorted = useMemo(() => [...rows].sort(by(sort)), [rows, sort]);\n"
        "  return <table>{sorted.map(r => <Row key={r.id} {...r} />)}</table>;\n"
        "}"
    ),
    (
        "total 48\n"
        "drwxr-xr-x  7 taylor taylor 4096 Nov 12 09:14 .\n"
        "drwxr-xr-x  3 root   root   4096 Aug  2 11:40 ..\n"
        "-rw-r--r--  1 taylor taylor  220 Aug  2 11:40 .bash_logout\n"
        "drwxr-xr-x  4 taylor taylor 4096 Nov 10 17:02 Documents"
    ),
    "The file src/components/Header.tsx has been updated successfully.",
    (
        "ERROR: Cannot install requests==2.31.0 and botocore 1.34.2 because these package "
        "versions have conflicting dependencies.\n"
        "The conflict is caused by: botocore 1.34.2 depends on urllib3<2.1"
    ),
    (
        "On branch main\n"
        "Your branch is up to date with 'origin/main'.\n"
        "nothing to commit, working tree clean"
    ),
    (
        "--- FAIL: TestRateLimiterBurst (0.02s)\n"
        "    limiter_test.go:88: expected 10 tokens, got 7\n"
        "FAIL\tgithub.com/acme/gateway/limiter\t0.214s"
    ),
    (
        "asset main.4f2a.js 412 KiB [emitted] [minimized] (name: main)\n"
        "asset vendor.9c1e.js 1.21 MiB [emitted] [big] (name: vendor)\n"
        "webpack 5.91.0 compiled with 2 warnings in 8421 ms"
    ),
    "(no output)",
    "Exit code 0",
)
