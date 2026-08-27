# Historical protocol architecture notes

Repository: `royale-proxy/cr-messages`, revision `64560f4a3c78005cea53c697fbe8ad2bb55bb82d`, last commit 2017-08-16. Declared `GNU GPLv3` in [package.json](../_references/cr-messages/package.json), with no standalone license. Upstream: https://github.com/royale-proxy/cr-messages.

## Scope boundary

This inspection is historical architecture research only. It does not establish a current protocol, authorize server access, or support interception, authentication bypass, private-server operation, or circumvention. No message definition was copied into HastyCR.

## Verified organization

The repository stores declarative JSON definitions in three directions/layers:

- [client](../_references/cr-messages/client/): client-originated envelopes such as hello/login, keepalive, home/alliance queries, replay stream requests, and end-turn events.
- [server](../_references/cr-messages/server/): server-originated login/home/alliance/ranking/replay/TV/status responses.
- [component](../_references/cr-messages/component/): nested reusable structures such as alliance entries, replay components, spell lists, command components, and client-home data.

The architecture separates envelope direction from reusable payload components and therefore suggests a general schema design: typed envelope → versioned payload → nested components → explicit decode/validation boundary. That pattern can inform offline trace schemas without using historical wire identifiers.

## Useful study files

- [ClientHello.json](../_references/cr-messages/client/ClientHello.json) and [ServerHello.json](../_references/cr-messages/server/ServerHello.json): historical request/response pairing.
- [EndClientTurn.json](../_references/cr-messages/client/EndClientTurn.json): historical turn/event envelope concept.
- [ReplayComponent.json](../_references/cr-messages/component/ReplayComponent.json) and [HomeBattleReplayData.json](../_references/cr-messages/server/HomeBattleReplayData.json): nested replay packaging concepts.
- [CommandComponent.json](../_references/cr-messages/component/CommandComponent.json) and [ServerCommandComponent.json](../_references/cr-messages/component/ServerCommandComponent.json): component indirection.

## Conclusion and uncertainty

Use only the abstract separation of envelopes, components, direction, and versioning. Definitions are old, GPL-constrained, incomplete as a license distribution, and likely obsolete. Their semantics were not verified against any game client or server.