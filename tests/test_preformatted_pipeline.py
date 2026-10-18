"""Real public preformatted consumers: no translation service or checker doubles."""

import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

import web_translator.cli as cli
from web_translator.models import read_segments
from web_translator.preformatted_contract import canonical_bytes, canonical_sha256


SOURCE = (b'<!doctype html><html><head><meta charset="utf-8"></head><body>'
          b'<pre id="manual">Read <a id="guide" href="#manual">the guide</a>. See https://exam\r\n'
          b'ple.test/a?x=1&amp;y=2 today.\r\n'
          b'+---+\r\n| A |</pre><pre id="code"><code>A\r\nB</code></pre></body></html>')
DIMENSIONS = ('semantic_fidelity', 'qualification_preservation', 'naturalness',
              'terminology', 'boundary_consistency', 'protected_content')


def _run(tmp_path):
    run = tmp_path / '작업 공간' / '.web-translator/runs/검토 run'
    output = tmp_path / '작업 공간' / 'translated-pages/검토 run'
    run.mkdir(parents=True)
    output.parent.mkdir(parents=True)
    (run / 'assets').mkdir()
    (run / 'source.html').write_bytes(SOURCE)
    (run / 'assets/theme.css').write_bytes(b'body { margin: 8px; }')
    capture = {'requested_url': 'https://example.com/', 'final_url': 'https://example.com/',
               'captured_at': '2026-10-17T00:00:00Z',
               'asset_map': {'https://example.com/theme.css': 'assets/theme.css'},
               'critical_assets': ['assets/theme.css'], 'optional_assets': [],
               'missing_optional_assets': [],
               'fingerprints': {name: hashlib.sha256((run / name).read_bytes()).hexdigest()
                                for name in ('source.html', 'assets/theme.css')}}
    (run / 'capture.json').write_bytes(canonical_bytes(capture))
    return run, output


def _command(command, run, output=None):
    args = [command, '--run-dir', str(run)]
    if output is not None:
        args += ['--output-dir', str(output)]
    return cli.main(args)


def _review_classification(run):
    analysis = json.loads((run / 'preformatted/analysis.json').read_bytes())
    packages = {p.stem: canonical_sha256(json.loads(p.read_bytes()))
                for p in (run / 'preformatted/packages').glob('*.json')}
    review = {'schema_version': '1.0', 'source_sha256': analysis['source_sha256'],
              'analysis_sha256': canonical_sha256(analysis), 'package_sha256': packages,
              'blocks': [
                  {'id': 'block-000001', 'pre_id': 'pre-000001',
                   'line_ids': ['line-000001', 'line-000002'], 'role': 'prose', 'evidence': 'Read',
                   'metadata': {}, 'literal_spans': [{
                       'kind': 'url', 'start_line_id': 'line-000001', 'start_column': 20,
                       'end_line_id': 'line-000002', 'end_column': 18,
                       'source_sha256': hashlib.sha256(b'https://exam\r\nple.test/a?x=1&y=2').hexdigest()}]},
                  {'id': 'block-000002', 'pre_id': 'pre-000001',
                   'line_ids': ['line-000003', 'line-000004'], 'role': 'literal-table',
                   'evidence': '+---+', 'metadata': {}, 'literal_spans': []}],
              'unresolved_required': []}
    # Deliberately pretty: the file digest and canonical review digest differ.
    (run / 'preformatted/review.json').write_text(json.dumps(review, indent=2) + '\n')


def _assembled(tmp_path):
    run, output = _run(tmp_path)
    assert _command('prepare-preformatted', run) == 0
    _review_classification(run)
    assert _command('materialize-preformatted', run) == 0
    assert _command('extract', run) == 0
    assert _command('plan-zones', run) == 0
    (run / 'glossary.json').write_text('{}\n')
    (run / 'document-summary.txt').write_text('Manual prose with a protected guide link, wrapped URL, fixed grid and code.\n')
    assert _command('prepare-assignments', run) == 0
    segments = [s for s in read_segments(run / 'segments.jsonl') if s.target]
    assert len(segments) == 1
    # These are authored fixture translations; tokens are immutable inline locations.
    text = segments[0].source_text.replace('Read ', '읽기: ').replace('the guide', '안내서')
    assert '읽기: ' in text
    (run / 'translations').mkdir()
    (run / 'translations/zone-001.jsonl').write_text(json.dumps({
        'segment_id': segments[0].id, 'text': text, 'notes': None,
        'glossary_observations': {}}, ensure_ascii=False) + '\n')
    (run / 'review.json').write_text(json.dumps({
        'unresolved_required': [], 'retries': {'zone-001': 0},
        'section_findings': {'zone-001': [
            {'dimension': name, 'verdict': 'pass',
             'evidence': f'Fixture reviewer compared source and Korean {name}.'}
            for name in DIMENSIONS]}}) + '\n')
    assert _command('validate-translations', run) == 0
    assert _command('assemble', run, output) == 0
    return run, output


def _no_pass(output):
    manifest = output / 'manifest.json'
    report = output / 'review-report.md'
    assert not manifest.exists() or json.loads(manifest.read_bytes())['qa_status'] != 'passed'
    assert not report.exists() or '**PASS**' not in report.read_text()


def test_preformatted_pipeline_runs_real_commands_and_preserves_capture(tmp_path, capsys):
    # Missing source selection, CR-preserving QA reads or generated CSS binding breaks this.
    run, output = _assembled(tmp_path)
    captured = {name: (run / name).read_bytes()
                for name in ('source.html', 'capture.json', 'assets/theme.css')}
    assert _command('qa', run, output) == 0
    manifest = json.loads((output / 'manifest.json').read_bytes())
    assert manifest['qa_status'] == 'passed'
    summary = manifest['normalization']
    assert summary['schema_version'] == '1.0'
    assert summary['policy'] == 'prose-reflow-literals-preserved'
    assert summary['translated_blocks'] == 1
    assert summary['preserved_reasons'] == {'literal-table': 1}
    assert summary['source_sha256'] == hashlib.sha256(SOURCE).hexdigest()
    record = json.loads((run / 'preformatted/provenance.json').read_bytes())
    assert record['marked_sha256'] == hashlib.sha256((run / 'preformatted-source.html').read_bytes()).hexdigest()
    assert record['review_sha256'] != summary['review_sha256']
    for asset in summary['generated_assets']:
        assert hashlib.sha256((output / asset['path']).read_bytes()).hexdigest() == asset['sha256']
        assert asset['path'] not in manifest['capture_metadata']['fingerprints']
    assert manifest['capture_metadata'] == json.loads(captured['capture.json'])
    assert '## Preformatted normalization' in (output / 'review-report.md').read_text()
    soup = BeautifulSoup((output / 'index.html').read_bytes().decode(), 'html.parser')
    assert soup.find(id='guide')['href'] == '#manual'
    assert soup.find(id='guide').text == '안내서'
    assert soup.find(id='code').text == 'A\r\nB'
    assert soup.select_one('[data-wt-preformatted-url]').text == 'https://exam\r\nple.test/a?x=1&y=2'
    assert soup.select_one('[data-wt-preformatted-literal]').text == '+---+\r\n| A |'
    assert len(manifest['screenshots']) == 2
    assert all(Path(p).read_bytes().startswith(b'\x89PNG') for p in manifest['screenshots'])
    assert all((run / name).read_bytes() == value for name, value in captured.items())
    statuses = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert all(s['status'] == 'ok' and s['exit_code'] == 0 for s in statuses)


@pytest.mark.parametrize('mutation', ['grid', 'code-newline', 'url', 'href', 'id', 'css',
                                      'source', 'capture', 'analysis', 'package',
                                      'review', 'provenance', 'derived', 'segments'])
def test_preformatted_qa_rejects_literal_or_provenance_tampering(tmp_path, mutation):
    # Omitting either pre-browser provenance or literal/CSS checking would admit these.
    run, output = _assembled(tmp_path)
    if mutation in {'grid', 'code-newline', 'url', 'href', 'id'}:
        path = output / 'index.html'
        before, after = {'grid': (b'| A |', b'| X |'),
                         'code-newline': (b'A\r\nB', b'A\nB'),
                         'url': (b'ple.test/a?x=1', b'ple.test/a?x=9'),
                         'href': (b'href="#manual"', b'href="#code"'),
                         'id': (b'id="guide"', b'id="changed"')}[mutation]
        assert before in path.read_bytes()
        path.write_bytes(path.read_bytes().replace(before, after))
    elif mutation == 'css':
        path = next((output / 'assets').glob('wt-preformatted-*.css'))
        path.write_bytes(path.read_bytes() + b'body { display:none }')
    else:
        path = {'source': run / 'source.html', 'capture': run / 'capture.json',
                'analysis': run / 'preformatted/analysis.json',
                'package': next((run / 'preformatted/packages').glob('*.json')),
                'review': run / 'preformatted/review.json',
                'provenance': run / 'preformatted/provenance.json',
                'derived': run / 'preformatted-source.html',
                'segments': run / 'segments.jsonl'}[mutation]
        if mutation in {'capture', 'provenance'}:
            value = json.loads(path.read_bytes())
            if mutation == 'capture':
                value['fingerprints']['source.html'] = '0' * 64
            else:
                value['source_sha256'] = '0' * 64
            path.write_bytes(canonical_bytes(value))
        else:
            path.write_bytes(path.read_bytes() + b'\n')
    assert _command('qa', run, output) != 0
    _no_pass(output)


@pytest.mark.parametrize('boundary', ['after-browser', 'after-publication'])
@pytest.mark.parametrize('target', ['source', 'capture', 'analysis', 'package', 'review',
                                    'provenance', 'derived', 'segments', 'source-css',
                                    'captured-css', 'output', 'css', 'replacement'])
def test_preformatted_qa_changes_at_acceptance_boundaries_leave_no_pass(
    tmp_path, monkeypatch, boundary, target
):
    # Late verification without owned cleanup would leave a newly published stale PASS.
    run, output = _assembled(tmp_path)
    path = {'source': run / 'source.html', 'capture': run / 'capture.json',
            'analysis': run / 'preformatted/analysis.json',
            'package': next((run / 'preformatted/packages').glob('*.json')),
            'review': run / 'preformatted/review.json',
            'provenance': run / 'preformatted/provenance.json',
            'derived': run / 'preformatted-source.html', 'segments': run / 'segments.jsonl',
            'source-css': next((run / 'assets').glob('wt-preformatted-*.css')),
            'captured-css': run / 'assets/theme.css', 'output': output / 'index.html',
            'replacement': output / 'index.html',
            'css': next((output / 'assets').glob('wt-preformatted-*.css')),
            'capture': run / 'capture.json'}[target]
    def mutate():
        if target == 'replacement':
            replacement = output / 'replacement.html'
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
        else:
            path.write_bytes(path.read_bytes() + b'\n')
    if boundary == 'after-browser':
        import web_translator.qa as qa
        real = qa._run_browser_checks
        def change(*args):
            result = real(*args)
            mutate()
            return result
        monkeypatch.setattr(qa, '_run_browser_checks', change)
    else:
        real = cli._publish_qa_evidence
        def change(*args, **kwargs):
            real(*args, **kwargs)
            mutate()
        monkeypatch.setattr(cli, '_publish_qa_evidence', change)
    assert _command('qa', run, output) != 0
    _no_pass(output)


def test_preformatted_pending_and_projected_state_do_not_allow_wrong_consumers(tmp_path):
    run, output = _run(tmp_path)
    assert _command('prepare-preformatted', run) == 0
    assert _command('extract', run) == 4
    assert not (run / 'segments.jsonl').exists()
    assert _command('materialize-preformatted', run) == 4
    _review_classification(run)
    assert _command('materialize-preformatted', run) == 0
    assert _command('assemble', run, output) != 0
    assert _command('qa', run, output) != 0
    _no_pass(output)


def test_legacy_web_and_pdf_contracts_need_no_preformatted_files(tmp_path):
    # No eligible preformatted state must not make normal source/capture mutation invalid.
    run, _ = _run(tmp_path)
    source = b'<html><body><p>Ordinary legacy source.</p></body></html>'
    (run / 'source.html').write_bytes(source)
    capture = json.loads((run / 'capture.json').read_bytes())
    capture['fingerprints']['source.html'] = hashlib.sha256(source).hexdigest()
    (run / 'capture.json').write_bytes(canonical_bytes(capture))
    assert _command('prepare-preformatted', run) == 0
    assert not (run / 'preformatted').exists()
    assert _command('extract', run) == 0
    assert (run / 'source.html').read_bytes() != source
    assert not (run / 'preformatted').exists()
    updated = json.loads((run / 'capture.json').read_bytes())
    assert set(updated['fingerprints']) == {'source.html', 'assets/theme.css'}
    assert updated['fingerprints']['source.html'] == hashlib.sha256((run / 'source.html').read_bytes()).hexdigest()
    assert set(read_segments(run / 'segments.jsonl')[0].to_dict()) == {
        'id', 'locator', 'semantic_type', 'heading_path', 'source_text',
        'protected', 'context_ids', 'target'}


def test_direct_qa_cannot_omit_normalization_for_known_preformatted_state(tmp_path):
    from web_translator.models import QAInputs, MasterReview
    from web_translator.qa import run_qa
    run, output = _assembled(tmp_path)
    result = run_qa(QAInputs(run / 'preformatted-source.html', output / 'index.html',
                            'https://example.com/', {'s'}, {'s'}, [], [],
                            run / 'qa-screenshots', MasterReview([], {}, {})))
    assert not result.passed
    assert 'preformatted-provenance' in {f.code for f in result.required_findings}
    assert result.screenshots == []


def test_stale_previous_pass_is_quarantined_not_restored_on_invalid_input(tmp_path):
    run, output = _assembled(tmp_path)
    old_manifest = b'{"qa_status":"passed","unrelated":true}\n'
    old_report = b'# Unrelated prior report\n**PASS**\n'
    (output / 'manifest.json').write_bytes(old_manifest)
    (output / 'review-report.md').write_bytes(old_report)
    review = run / 'preformatted/review.json'
    review.write_bytes(review.read_bytes() + b'\n')
    assert _command('qa', run, output) == 6
    _no_pass(output)
    recovery = list(output.glob('.qa-evidence-*'))
    assert len(recovery) == 1
    assert (recovery[0] / 'prior-manifest.json').read_bytes() == old_manifest
    assert (recovery[0] / 'prior-review-report.md').read_bytes() == old_report


def test_preformatted_qa_rejects_foreign_screenshot_directory(tmp_path):
    run, output = _assembled(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'sentinel').write_bytes(b'untouched')
    (run / 'qa-screenshots').symlink_to(outside, target_is_directory=True)
    assert _command('qa', run, output) == 6
    assert list(outside.iterdir()) == [outside / 'sentinel']
    assert (outside / 'sentinel').read_bytes() == b'untouched'
    _no_pass(output)


def test_empty_preformatted_extraction_is_not_successful_translation(tmp_path):
    run, output = _run(tmp_path)
    assert _command('prepare-preformatted', run) == 0
    _review_classification(run)
    path = run / 'preformatted/review.json'
    review = json.loads(path.read_bytes())
    review['blocks'] = [{**review['blocks'][1], 'id': 'block-000001',
                         'line_ids': ['line-000001', 'line-000002', 'line-000003', 'line-000004']}]
    path.write_bytes(canonical_bytes(review))
    assert _command('materialize-preformatted', run) == 0
    assert _command('extract', run) == 0
    assert (run / 'segments.jsonl').read_bytes() == b''
    assert _command('plan-zones', run) == 0
    (run / 'translations').mkdir()
    (run / 'glossary.json').write_text('{}\n')
    (run / 'review.json').write_text('{"unresolved_required":[],"retries":{},"section_findings":{}}\n')
    assert _command('assemble', run, output) != 0
    # A caller can use the old low-level assembler, but neither public QA nor
    # direct typed QA may certify this zero-target extraction as a translation.
    from web_translator.assemble import assemble_page
    from web_translator.models import QAInputs, MasterReview
    from web_translator.preformatted_contract import NormalizationSummary
    from web_translator.qa import run_qa
    assemble_page(run / 'preformatted-source.html', {}, {}, {}, output, 'https://example.com/')
    assert _command('qa', run, output) == 6
    summary = NormalizationSummary.from_dict(json.loads((run / 'preformatted/provenance.json').read_bytes())['summary'])
    result = run_qa(QAInputs(run / 'preformatted-source.html', output / 'index.html',
                            'https://example.com/', set(), set(), [], [],
                            run / 'qa-screenshots', MasterReview([], {}, {}), normalization=summary))
    assert not result.passed
    assert 'translation-coverage' in {f.code for f in result.required_findings}
    assert result.screenshots == []
    _no_pass(output)


def test_foreign_report_replacement_survives_failed_postpublication_check(tmp_path, monkeypatch):
    run, output = _assembled(tmp_path)
    real = cli._publish_qa_evidence
    foreign = b'# Foreign report\nnot transaction owned\n'
    def replace_report(*args, **kwargs):
        real(*args, **kwargs)
        replacement = output / 'foreign.md'
        replacement.write_bytes(foreign)
        replacement.replace(output / 'review-report.md')
    monkeypatch.setattr(cli, '_publish_qa_evidence', replace_report)
    assert _command('qa', run, output) == 6
    assert not (output / 'manifest.json').exists()
    assert (output / 'review-report.md').read_bytes() == foreign


def test_recovery_snapshot_failure_does_not_delete_prior_evidence(tmp_path, monkeypatch):
    import web_translator.pdf_extract_transaction as transaction
    run, output = _assembled(tmp_path)
    prior = {'manifest.json': b'{"qa_status":"failed"}\n',
             'review-report.md': b'# Previous FAIL evidence\n'}
    for name, payload in prior.items():
        (output / name).write_bytes(payload)
    real = transaction._write_private_file
    def fail_backup(directory, name, payload):
        if name == 'prior-manifest.json':
            raise OSError('injected recovery storage failure')
        return real(directory, name, payload)
    monkeypatch.setattr(transaction, '_write_private_file', fail_backup)
    assert _command('qa', run, output) == 6
    assert {(name): (output / name).read_bytes() for name in prior} == prior


def test_dangling_preformatted_state_cannot_leave_prior_pass_or_omit_provenance(tmp_path):
    from web_translator.models import QAInputs, MasterReview
    from web_translator.qa import run_qa
    run, output = _assembled(tmp_path)
    prior = {'manifest.json': b'{"qa_status":"passed"}\n',
             'review-report.md': b'# Prior result\n**PASS**\n'}
    for name, payload in prior.items():
        (output / name).write_bytes(payload)
    (run / 'preformatted').rename(run / 'saved-state')
    (run / 'preformatted').symlink_to(run / 'missing-state', target_is_directory=True)
    (run / 'preformatted-source.html').unlink()
    # The selector already rejects this orphan. The regression is stale PASS
    # cleanup/classification, not a claim that the old selector approves it.
    assert _command('qa', run, output) != 0
    _no_pass(output)
    recovery = next(output.glob('.qa-evidence-*'))
    for name, payload in prior.items():
        assert (recovery / ('prior-' + name)).read_bytes() == payload
    result = run_qa(QAInputs(run / 'source.html', output / 'index.html',
                            'https://example.com/', {'s'}, {'s'}, [], [],
                            run / 'qa-screenshots', MasterReview([], {}, {})))
    assert not result.passed
    assert 'preformatted-provenance' in {f.code for f in result.required_findings}


def _orphan_state(run, kind):
    if kind == 'orphan-css':
        (run / 'assets/wt-preformatted-orphan.css').write_bytes(b'/* orphan */')
    elif kind == 'interrupted':
        (run / '.preformatted-interrupted').mkdir()
    elif kind == 'interrupted-link':
        (run / '.preformatted-interrupted').symlink_to(run / 'missing')
    elif kind == 'sibling-derived':
        (run / 'preformatted-source.html').write_bytes(b'orphan derived')
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize('kind', ['orphan-css', 'interrupted', 'interrupted-link', 'sibling-derived'])
def test_orphan_qa_quarantines_prior_pass_using_the_runtime_state_indicators(tmp_path, kind):
    # A partial state must not select legacy evidence handling on selector rejection.
    run, output = _run(tmp_path)
    _orphan_state(run, kind)
    output.mkdir()
    (output / 'index.html').write_bytes(SOURCE)
    prior = {'manifest.json': b'{"qa_status":"passed","old":true}\n',
             'review-report.md': b'# Prior PASS\n**PASS**\n'}
    for name, payload in prior.items():
        (output / name).write_bytes(payload)
    assert _command('qa', run, output) == 6
    _no_pass(output)
    for name, payload in prior.items():
        assert any(path.read_bytes() == payload
                   for path in output.glob('.qa-evidence-*/prior-' + name))


@pytest.mark.parametrize('kind', ['orphan-css', 'interrupted', 'interrupted-link', 'sibling-derived'])
def test_direct_qa_requires_normalization_for_each_lexical_orphan_indicator(tmp_path, kind):
    from web_translator.models import QAInputs, MasterReview
    from web_translator.qa import run_qa
    run, output = _run(tmp_path)
    _orphan_state(run, kind)
    output.mkdir()
    (output / 'index.html').write_bytes(SOURCE)
    result = run_qa(QAInputs(run / 'source.html', output / 'index.html',
                            'https://example.com/', {'s'}, {'s'}, [], [],
                            run / 'qa-screenshots', MasterReview(['stop before browser'], {}, {})))
    assert not result.passed
    assert {f.code for f in result.required_findings} == {'preformatted-provenance'}
    assert result.screenshots == []


@pytest.mark.parametrize('boundary', ['before-publication', 'after-publication'])
@pytest.mark.parametrize('mutation', ['in-place-edit', 'same-byte-replacement'])
def test_recovery_tampering_resecures_exact_owned_bytes_before_original_cleanup(
    tmp_path, boundary, mutation
):
    from web_translator.models import MasterReview, QAResult
    output = tmp_path / 'output'
    output.mkdir()
    prior = {'manifest.json': b'{"qa_status":"failed","original":true}\n',
             'review-report.md': b'# Exact original FAIL\n'}
    for name, payload in prior.items():
        (output / name).write_bytes(payload)
    failure = ValueError('subsequent acceptance validation failed')
    foreign_identity = None
    with pytest.raises(ValueError) as raised:
        with cli._preformatted_qa_evidence(output) as transaction:
            if boundary == 'after-publication':
                transaction.publish(QAResult(False, [], [], []), MasterReview([], {}, {}), None)
            backup = next(output.glob('.qa-evidence-*/prior-manifest.json'))
            if mutation == 'in-place-edit':
                backup.write_bytes(b'corrupt private recovery\n')
            else:
                foreign = output / 'foreign-backup.json'
                foreign.write_bytes(prior['manifest.json'])
                foreign.replace(backup)
                foreign_identity = backup.stat().st_ino
            if boundary == 'before-publication':
                transaction.publish(QAResult(False, [], [], []), MasterReview([], {}, {}), None)
            raise failure
    assert raised.value is failure
    _no_pass(output)
    for name, payload in prior.items():
        exact = [path for path in output.glob('.qa-evidence-*/prior-' + name)
                 if path.read_bytes() == payload]
        assert exact, f'exact original {name} was lost'
        if name == 'manifest.json' and foreign_identity is not None:
            assert any(path.stat().st_ino != foreign_identity for path in exact)
    if foreign_identity is not None:
        assert backup.stat().st_ino == foreign_identity
        assert backup.read_bytes() == prior['manifest.json']


def test_failed_resecuring_of_edited_backup_preserves_the_unbacked_original(tmp_path, monkeypatch):
    import web_translator.pdf_assemble as storage
    output = tmp_path / 'output'
    output.mkdir()
    prior = {'manifest.json': b'{"qa_status":"failed","original":true}\n',
             'review-report.md': b'# Exact previous report\n'}
    for name, payload in prior.items():
        (output / name).write_bytes(payload)
    failure = ValueError('validation failed before publication')
    with pytest.raises(ValueError) as raised:
        with cli._preformatted_qa_evidence(output):
            backup = next(output.glob('.qa-evidence-*/prior-manifest.json'))
            backup.write_bytes(b'corrupt recovery\n')
            def no_storage(*args):
                raise OSError('fresh recovery storage unavailable')
            monkeypatch.setattr(storage, '_create_anchored_binary_file', no_storage)
            raise failure
    assert raised.value is failure
    assert (output / 'manifest.json').read_bytes() == prior['manifest.json']
    _no_pass(output)


@pytest.mark.parametrize('later_mutation', ['in-place-edit', 'same-byte-replacement'])
def test_recovery_can_repair_again_after_its_first_fresh_snapshot_is_changed(tmp_path, later_mutation):
    from web_translator.models import MasterReview, QAResult
    output = tmp_path / 'output'
    output.mkdir()
    original = b'{"qa_status":"failed","exact_original":true}\n'
    (output / 'manifest.json').write_bytes(original)
    (output / 'review-report.md').write_bytes(b'# Prior exact FAIL\n')
    failure = ValueError('failure after repeated recovery tampering')
    foreign_identity = None
    with pytest.raises(ValueError) as raised:
        with cli._preformatted_qa_evidence(output) as transaction:
            first = next(output.glob('.qa-evidence-*/prior-manifest.json'))
            first.write_bytes(b'first corrupted snapshot\n')
            transaction.publish(QAResult(False, [], [], []), MasterReview([], {}, {}), None)
            fresh = next(path for path in output.glob('.qa-evidence-*/prior-manifest.json')
                         if path.read_bytes() == original)
            assert fresh != first
            if later_mutation == 'in-place-edit':
                fresh.write_bytes(b'second corrupted snapshot\n')
            else:
                replacement = output / 'foreign-second-snapshot.json'
                replacement.write_bytes(original)
                replacement.replace(fresh)
                foreign_identity = fresh.stat().st_ino
            raise failure
    assert raised.value is failure
    _no_pass(output)
    exact = [path for path in output.glob('.qa-evidence-*/prior-manifest.json')
             if path.read_bytes() == original]
    assert exact
    if foreign_identity is not None:
        assert fresh.stat().st_ino == foreign_identity
        assert fresh.read_bytes() == original
        assert any(path.stat().st_ino != foreign_identity for path in exact)
