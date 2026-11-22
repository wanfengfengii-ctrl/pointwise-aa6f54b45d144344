from contextlib import closing
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from ingest.batches import BatchSubmission, accept_batch
from ingest.records import Observation, RevisionKey
from maintenance.active import list_active_packs
from maintenance.receipts import load_retirement_receipt
from maintenance.retire import retire_pack
from maintenance.transactions import initialize_database, open_database
from packing.addresses import PackAddress
from packing.seal import SealSelection, seal_pack
from packing.store import read_pack_bytes
from reading.open import SnapshotReadError, read_contributions, read_snapshot
from snapshot.catalog import get_manifest_bytes
from snapshot.publish import publish_snapshot, publish_with_contributions


_SAMPLE = Path(__file__).resolve().parent / 'samples' / 'workday.json'


def _submit(source, batch):
    observations = tuple(
        Observation(RevisionKey(source, record, revision), bytes.fromhex(value))
        for record, revision, value in batch['observations']
    )
    return BatchSubmission(source, batch['id'], observations)


def _summarize(audit):
    return [[row.revision.source, row.revision.record, row.revision.revision,
             row.value.hex(), row.byte_length] for row in audit.rows]


def _summarize_contributions(result):
    return [[
        row.revision.source, row.revision.record, row.revision.revision,
        row.value.hex(), row.byte_length,
        [[start, end, key.source, key.record, key.revision, source_start, source_end]
         for start, end, key, source_start, source_end in row.contributions],
    ] for row in result.rows]


def run_workday(path: Path, sample: dict) -> int:
    source = sample['source']
    early, correction = (_submit(source, batch) for batch in sample['batches'])
    target = sample['retire']
    expected = {
        'early-reference': [['chengchuan', 'reference', 'v1', '4344', 2]],
        'shift-signal': [['chengchuan', 'signal', 'v3', '417821', 3]],
    }
    contribution_sample = sample['contribution_snapshot']
    contribution_expected = [[
        'chengchuan', 'signal', 'v3', '417821', 3,
        [[0, 1, 'chengchuan', 'signal', 'v1', 0, 1],
         [1, 2, 'chengchuan', 'signal', 'v2', 1, 2],
         [2, 3, 'chengchuan', 'signal', 'v3', 2, 3]],
    ]]
    with closing(open_database(path)) as db:
        initialize_database(db)
        accepted = accept_batch(db, early)
        print('接纳早班批次', accepted.new_revisions)
        replay = accept_batch(db, early)
        amended = accept_batch(db, correction)
        if replay.revisions != accepted.revisions or replay.new_revisions != 0:
            raise AssertionError('batch replay changed the acceptance')
        print('重投新增及更正新增', replay.new_revisions, amended.new_revisions)
        for pack in sample['packs']:
            selections = tuple(
                SealSelection(
                    RevisionKey(source, *item['revision']),
                    PackAddress(*item['base']) if 'base' in item else None,
                    item.get('prefix', 0),
                ) for item in pack['entries']
            )
            result = seal_pack(db, pack['id'], selections)
            print('封存包', result.pack_id, '包位数', len(result.addresses), '字节数', result.sealed_bytes)
        manifests = {
            name: publish_snapshot(db, name, tuple(PackAddress(*ref) for ref in addresses)).manifest
            for name, addresses in sample['snapshots'].items()
        }
        print('发布快照', ', '.join(manifests))
        before = {name: _summarize(read_snapshot(db, manifest)) for name, manifest in manifests.items()}
        if before != expected:
            raise AssertionError(f'unexpected pre-retirement audit {before!r}')
        contribution_manifest = publish_with_contributions(
            db, contribution_sample['id'],
            tuple(PackAddress(*ref) for ref in contribution_sample['addresses']),
        ).manifest
        before_contributions = _summarize_contributions(read_contributions(db, contribution_manifest))
        if before_contributions != contribution_expected:
            raise AssertionError(f'unexpected pre-retirement provenance {before_contributions!r}')
        print('交班读回', json.dumps(before, ensure_ascii=False))
        print('贡献读回', json.dumps(before_contributions, ensure_ascii=False))
        original = read_pack_bytes(db, target)
        kept = {pack: read_pack_bytes(db, pack) for pack in list_active_packs(db) if pack != target}
        receipt = retire_pack(db, target)
        print('退役包', receipt.pack_id, '移除字节数', receipt.removed_bytes)

    with closing(open_database(path)) as db:
        actual = {}
        for name, manifest in manifests.items():
            try:
                actual[name] = _summarize(read_snapshot(db, manifest))
            except SnapshotReadError as exc:
                actual[name] = {'read_error': str(exc)}
        actual_contributions = _summarize_contributions(read_contributions(db, contribution_manifest))
        downstream_actual = {
            'active_packs': list(list_active_packs(db)),
            'payload_removed': read_pack_bytes(db, target) is None,
            'other_pack_bytes_fixed': all(read_pack_bytes(db, pack) == data for pack, data in kept.items()),
            'manifests_fixed': all(get_manifest_bytes(db, name) == data for name, data in manifests.items()),
            'contribution_manifest_fixed': get_manifest_bytes(
                db, contribution_sample['id']) == contribution_manifest,
            'receipt_fixed': load_retirement_receipt(db, target) == receipt
                             and receipt.removed_bytes == len(original),
        }
    downstream_expected = {
        'active_packs': ['Q', 'R'], 'payload_removed': True, 'other_pack_bytes_fixed': True,
        'manifests_fixed': True, 'contribution_manifest_fixed': True, 'receipt_fixed': True,
    }
    if actual != expected or actual_contributions != contribution_expected \
            or downstream_actual != downstream_expected:
        details = {'actual': actual, 'expected': expected,
                   'contribution_actual': actual_contributions,
                   'contribution_expected': contribution_expected, 'downstream': downstream_actual}
        print('PACK_RETIRE_SNAPSHOT_MISMATCH', json.dumps(details, sort_keys=True), file=sys.stderr)
        return 1
    print('重开后读回', json.dumps(actual, ensure_ascii=False))
    print('重开后贡献读回', json.dumps(actual_contributions, ensure_ascii=False))
    evidence = {
        'case_id': 'V7', 'input': sample, 'expected': expected, 'actual': actual,
        'contribution_expected': contribution_expected, 'contribution_actual': actual_contributions,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': ['packing/delta.py', 'packing/chains.py', 'reading/provenance.py',
                       'snapshot/publish.py', 'snapshot/contributions.py',
                       'maintenance/dependencies.py', 'maintenance/retire.py',
                       'reading/open.py', 'reading/resolve.py'],
        'oracle': 'P:1 is CD. AB[:1] with x gives Ax, then Ax[:2] with ! gives Ax!. '
                  'The provenance row splits Ax! into P:0[0:1] + Q:0[1:2] + R:0[2:3]. '
                  'Compare the kept payloads, fixed manifests, and provenance spans across the reopen.',
    }
    print('POINTWISE_SCENARIO', json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0


def main() -> int:
    sample = json.loads(_SAMPLE.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='chengchuan-') as directory:
        return run_workday(Path(directory) / 'observations.sqlite3', sample)


if __name__ == '__main__':
    raise SystemExit(main())
