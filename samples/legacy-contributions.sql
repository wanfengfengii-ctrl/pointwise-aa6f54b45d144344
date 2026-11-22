PRAGMA foreign_keys = OFF;
BEGIN TRANSACTION;
CREATE TABLE revisions (
    source TEXT NOT NULL, record_id TEXT NOT NULL, revision_id TEXT NOT NULL, value BLOB NOT NULL,
    PRIMARY KEY (source, record_id, revision_id)
) WITHOUT ROWID;
INSERT INTO revisions VALUES
    ('station','ax','v1',X'4178'), ('station','base','v1',X'4142'), ('station','empty','v1',X''),
    ('station','fresh','v1',X'007A'), ('station','positive','v1',X'4179');
CREATE TABLE batches (
    source TEXT NOT NULL, batch_id TEXT NOT NULL, PRIMARY KEY (source, batch_id)
) WITHOUT ROWID;
INSERT INTO batches VALUES ('station','legacy-inputs');
CREATE TABLE batch_items (
    source TEXT NOT NULL, batch_id TEXT NOT NULL, position INTEGER NOT NULL CHECK (position >= 0),
    record_id TEXT NOT NULL, revision_id TEXT NOT NULL, PRIMARY KEY (source, batch_id, position),
    FOREIGN KEY (source, batch_id) REFERENCES batches(source, batch_id),
    FOREIGN KEY (source, record_id, revision_id) REFERENCES revisions(source, record_id, revision_id)
) WITHOUT ROWID;
INSERT INTO batch_items VALUES
    ('station','legacy-inputs',0,'base','v1'), ('station','legacy-inputs',1,'ax','v1'),
    ('station','legacy-inputs',2,'positive','v1'), ('station','legacy-inputs',3,'fresh','v1'),
    ('station','legacy-inputs',4,'empty','v1');
CREATE TABLE pack_activity (
    pack_id TEXT NOT NULL PRIMARY KEY, active INTEGER NOT NULL CHECK (active IN (0, 1))
) WITHOUT ROWID;
INSERT INTO pack_activity VALUES ('P',1), ('Q',0);
CREATE TABLE pack_payloads (
    pack_id TEXT NOT NULL PRIMARY KEY REFERENCES pack_activity(pack_id), payload BLOB NOT NULL
) WITHOUT ROWID;
INSERT INTO pack_payloads VALUES ('P',X'43435041434B0100000001460000000773746174696F6E00000004626173650000000276310000000241424A413DE263FF36BDBA4EDE2A01C9DBC5137F99D02B9A4A922177408B35B35147');
CREATE TABLE snapshots (snapshot_id TEXT NOT NULL PRIMARY KEY, manifest BLOB NOT NULL) WITHOUT ROWID;
INSERT INTO snapshots VALUES ('legacy',X'5B312C226C6567616379222C5B5B2251222C302C2273746174696F6E222C226178222C227631225D5D5D');
CREATE TABLE publication_receipts (
    snapshot_id TEXT NOT NULL PRIMARY KEY REFERENCES snapshots(snapshot_id),
    record_count INTEGER NOT NULL CHECK (record_count >= 0),
    total_bytes INTEGER NOT NULL CHECK (total_bytes >= 0),
    manifest_sha256 TEXT NOT NULL
) WITHOUT ROWID;
INSERT INTO publication_receipts VALUES ('legacy',1,2,'897d0c8228ff7aa955121554bcf1ebd2c461a593e4c295dc1641af82fa7a592c');
CREATE TABLE replacement_payloads (payload_id INTEGER PRIMARY KEY, payload BLOB NOT NULL);
INSERT INTO replacement_payloads VALUES (1,X'43435041434B0100000001460000000773746174696F6E000000026178000000027631000000024178003402B46160E099C972E28013E370DB6876B76597396B1546F2455E6D9EAF3B');
CREATE TABLE replacement_bindings (
    original_pack TEXT NOT NULL REFERENCES pack_activity(pack_id),
    original_slot INTEGER NOT NULL CHECK (original_slot >= 0),
    payload_id INTEGER NOT NULL UNIQUE REFERENCES replacement_payloads(payload_id),
    PRIMARY KEY (original_pack, original_slot)
) WITHOUT ROWID;
INSERT INTO replacement_bindings VALUES ('Q',0,1);
CREATE TABLE retirement_receipts (
    pack_id TEXT NOT NULL PRIMARY KEY REFERENCES pack_activity(pack_id),
    removed_bytes INTEGER NOT NULL CHECK (removed_bytes >= 0),
    preserved_addresses INTEGER NOT NULL CHECK (preserved_addresses >= 0)
) WITHOUT ROWID;
INSERT INTO retirement_receipts VALUES ('Q',93,1);
COMMIT;
PRAGMA foreign_keys = ON;
