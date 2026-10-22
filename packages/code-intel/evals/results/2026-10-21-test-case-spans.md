# JavaScript/TypeScript test-case spans — development investigation

The initial comparison is **operator-invalid**, not a test of the intended
callback-span hypothesis. macOS workspace aliases (`/var` versus `/private/var`)
caused the adapter to fail before extraction. The index caught that exception
and used file windows. All 2,088 candidate hit occurrences were file windows;
there were zero callback units. The earlier arithmetic rejection must not be
interpreted as evidence that correctly indexed callback spans are ineffective.

An independent author and reviewer grounded 24 new questions in pinned Express
and Prisma sources before that attempt. The questions are now consumed. Any
corrected comparison on them is development evidence, not fresh validation.
The initial failed source-copy attempt, fallback-only comparison, raw pages,
operators and earlier uncommitted report/archive are retained privately.

The technical correction canonicalizes workspace and AST paths. An alias-path
regression fails before the fix and passes afterward. Before any query, the
operator now requires actual indexed callback units, byte-identical keyword
documents, and unchanged counts of named function/class/method body windows.
The callback extraction rule, scoring configuration and questions are unchanged.
No search ranking change is enabled in product.
