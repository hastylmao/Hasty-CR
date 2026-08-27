# Berkan ClashRoyale study-only notes

Revision: `98b3656940d1606107527b9ddbc06a79f9a3016f`, last commit 2018-06-11. The [README](../_references/berkan-clashroyale/README.md) declares Creative Commons Attribution-NonCommercial-NoDerivs 4.0. Upstream: https://github.com/BerkanYildiz/ClashRoyale.

## Verified architecture

This is a historical C# solution with shared utilities/protocol code (`ClashRoyale`), client projects, server handlers/database models (`ClashRoyale.Server`), CSV generation (`ClashRoyale.CSV`), patcher/proxy projects, and binary/data dumps. Server code is organized around directional handlers and factories; database models separate players, clans, and battles.

## Sprint classification

Strict study-only. The NoDerivatives and NonCommercial declaration is incompatible with adapting implementation into this project, and the repository includes historical networking/private-server/proxy surfaces that are outside the fidelity sprint's safe scope. No code, protocol constants, assets, or dumps were copied or operationalized.

## Limited architectural observations

- Handler-factory separation is a generic example of dispatching typed messages to domain handlers.
- CSV/template tooling shows a historical attempt to turn tabular definitions into typed code.
- Shared/client/server project layering illustrates one way to isolate transport, storage, and domain concerns.

These patterns are generic inferences only. The repository is old, its protocol and data relevance are unknown, and it cannot establish current mechanics or official behavior.