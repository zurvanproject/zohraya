These are exact, source-pinned copies from zurvanproject/zohraya. The manifest
records repository paths, commits, Git blob SHA1 and SHA256. Its own SHA256 is
pinned in `body.py`. Preserve bytes, including LF and the phenotype file's lack
of a final newline. All files are verified before the atlas builder is loaded.

Only `tools/fullbody_design_atlas.py` is executed, to build an inventory and gap
report from the two pinned JSON inputs. It performs no native body cycle, API
call or sensor access. Neural and affect Python files are parsed as syntax to
extract definitions, never imported or executed. The genome contract is read
as authored design metadata. Remaining native schema references are catalogue
entries from a read-only source audit, not runtime integration.

The three body identities stay separate: reduced legacy 195 kg physiology,
78 kg authored visual target, and separate 78 kg MuJoCo mechanics. No stock,
mass, geometry or checkpoint is migrated. Native valence is signed [-1, 1];
the separate body-loop policy's [0, 1] valence is not implicitly converted.

The accepted export schema, fields and digest serialization are documented in
`body.py`. `project_native_snapshot(snapshot, model_id=MODEL, finite_stocks=...)`
validates the existing snapshot envelope and projects it to that closed schema.
The model ID is an explicit caller declaration. Hashes verify integrity only;
they do not authenticate a caller, verify model lineage, establish physical
sensing, or authorize action. Separately supplied stocks are not covered by the
native snapshot's digest. A snapshot older than five simulated seconds has
unknown values; wall-clock domains and future samples are rejected. Missing
values remain null, never synthetic zeros. Export ranges are serialization
limits, not clinical reference ranges or proven safe operating limits.

This catalogue is not a full inventory of every native physics constant. In
particular, calibration of the 78 kg physiology, real sensor attachments, organ
meshes, complete neurovascular dynamics and empirical validation remain gaps.
