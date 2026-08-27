# APK static analysis

Generated: `2026-08-23T20:02:09.659880+00:00`

Static clean-room analysis only. APK code and native libraries were never executed. Raw proprietary bytes remain ignored under `_references/apk_analysis/`.

## Scope and safety

- Inventoried every `*.apk` recursively under `C:\Users\aksha\Downloads\cr`.
- Preserved originals byte-for-byte and re-hashed each original after extraction.
- Treated APKs strictly as ZIP/data containers; no bytecode, app component, JNI library, or bundled executable was run.
- Applied path traversal, duplicate normalized path, symlink, per-entry size, total expanded size, and compression-ratio protections before extraction.
- Stored raw extraction, entry hashes, and focused machine evidence only under ignored `_references/apk_analysis/`.
- Compared names/schema identifiers and hashes only; no APK or cr-csv proprietary bytes are copied into tracked reports.

## Artifacts

- `inventory.md`: source, hash, package/version/SDK, ZIP, DEX, ABI, and classification inventory.
- `cross_apk_matrix.md`: exact APK and component-hash similarities.
- `code_and_asset_map.md`: DEX/native/resource/data layout.
- `mechanics_evidence.md`: focused static terminology and schema evidence.
- `data_source_comparison.md`: identifier-level comparison with local cr-csv and HastyCR data.
- `reports/apks/<safe-name>/SUMMARY.md`: one bounded summary per APK.
- `_references/apk_analysis/inventory.json`: normalized machine-readable record.

## Classification vocabulary

`official match`, `official historical`, `modified official`, `custom/private-server`, and `unknown` are evidence labels, not authenticity guarantees. No APK received `official historical` merely due to old-looking versions; that label requires corroborated official provenance and version evidence.

## Tool limitations

- JADX, apktool, aapt/aapt2, and 7z were absent; no tools were downloaded or installed.
- Package/version/SDK values use an in-house read-only Android binary XML parser; unresolved resource references remain numeric.
- Certificate subject/issuer trust and signer identity are blocked because no dedicated APK signature verifier/parser was available; reports retain certificate-entry hashes and signing-block scheme IDs where recoverable.
- DEX analysis parses headers/string tables only; there is no Java/Kotlin decompilation or control-flow interpretation.
- Native analysis parses ELF metadata/dynamic symbol names and focused printable strings only; libraries were never loaded or executed.
- Compressed/encrypted/proprietary assets that the bounded stdlib decoders could not decode remain inventoried and hashed but semantically opaque.
- No current protocol interception, authentication bypass, server connection, app launch, emulator installation, or runtime observation was attempted.
