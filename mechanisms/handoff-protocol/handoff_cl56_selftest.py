#!/usr/bin/env python3
"""CL-56 隔离平台契约与真实本地 Git 对象验证。无真实平台写入。"""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import handoff_data as data
import handoff_platform as plat
import handoff_migration as mig
import handoff_workflow as flow
import handoff_status as status
import handoff_workflow_selftest as fixture_module


class GitHubTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture_module.Fixture(); self.f.setUp()
        self.c = dict(schema='handoff-platform-config/v1', provider='github', host='https://github.com',
                      repository='owner/project', repository_id='123', target_branch='main', deployment='private-free',
                      deployment_ref='decisions/D-01-test.md:2')
        self.f.write('decisions/D-01-test.md', '# Decision\nOwner 已批准 owner/project 私有免费部署。\n')
        self.f.commit('deployment')
        self.f.git('remote', 'add', 'origin', 'git@github.com:owner/project.git')
        self.meta = dict(id=123, full_name='owner/project', private=True, archived=False, default_branch='main',
                         permissions=dict(push=True, admin=False), role_name='write', allow_merge_commit=True)
        self.rows = {}; self.calls = []; self.created = []; self.error = None; self.pages = None
        self.adapter = plat.GitHubAdapter(self.f.repo, config=self.c, api=self.api)

    def tearDown(self):
        self.f.tearDown()

    def pr(self, number=1, **changes):
        side = dict(repo=dict(id=123, full_name='owner/project'), sha=self.f.git('rev-parse', 'HEAD'))
        value = dict(number=number, html_url=f'https://github.com/owner/project/pull/{number}', state='open', merged=False,
                     head=dict(side, ref='work'), base=dict(side, ref='main'), title='title', body='body', draft=False)
        value.update(changes)
        return value

    def api(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == '/repos/owner/project':
            return copy.deepcopy(self.meta)
        if path.endswith('/protection'):
            raise self.error or plat.ApiError('GET', 403, True)
        if path.endswith('/branches/main'):
            return dict(commit=dict(sha=self.f.base))
        if '/pulls?' in path:
            from urllib.parse import parse_qs, urlsplit
            page = int(parse_qs(urlsplit(path).query)['page'][0])
            return self.pages[page-1] if self.pages is not None else [dict(number=n) for n in self.rows]
        if method == 'POST':
            self.created.append(body)
            self.rows[1] = self.pr(title=body['title'], body=body['body'])
            return self.rows[1]
        return copy.deepcopy(self.rows[int(path.rsplit('/', 1)[-1])])

    def test_P01_identity_before_prepare_no_commit(self):
        self.meta['id'] = 456
        before = self.f.git('rev-parse', 'HEAD'); self.f.mr()
        with self.assertRaises(plat.PlatformError):
            flow.publish(self.f.repo, self.f.q, lambda repo: self.adapter)
        self.assertEqual(before, self.f.git('rev-parse', 'HEAD')); self.assertFalse(self.created)

    def test_P01_missing_conflicting_config_and_push_url(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(flow.Stop):
            flow.select_adapter(self.f.repo)
        self.f.git('remote', 'set-url', '--push', 'origin', 'git@github.com:owner/other.git')
        with self.assertRaises(plat.PlatformError): self.adapter.inspect_repository()
        self.assertFalse(self.calls)

    def test_P01_config_closed_and_outside(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'platform.json'; p.write_text(json.dumps(self.c))
            with patch.dict(os.environ, {'HANDOFF_PLATFORM_CONFIG': str(p)}, clear=True):
                self.assertEqual(plat.load_config(self.f.repo), self.c)
                p.write_text(json.dumps(dict(self.c, token='test-secret')))
                with self.assertRaises(plat.PlatformError): plat.load_config(self.f.repo)

    def test_P02_full_description_and_normal_pr(self):
        h = self.f.git('rev-parse', 'HEAD'); text = '多行申报\n' * 2000
        value = self.adapter.create_change_request(self.f.ctx, h, dict(title='正常 PR'), text, self.f.base)
        self.assertEqual(value['description'], text); self.assertEqual(value['title'], '正常 PR')
        self.assertIs(self.created[0]['draft'], False)
        self.assertEqual(flow.verify_mr(value, self.f.ctx, h)['id'], 1)
        self.assertEqual([x[0] for x in self.calls].count('POST'), 1)

    def test_P03_pagination_and_fork(self):
        self.rows = {n: self.pr(n) for n in range(1, 102)}
        self.pages = [[dict(number=n) for n in range(1, 101)], [dict(number=101)]]
        found = self.adapter.find_change_requests('work', 'main'); self.assertEqual(len(found), 101)
        self.rows[101]['head']['repo']['id'] = 999
        with self.assertRaises(plat.PlatformError): self.adapter.find_change_requests('work', 'main')

    def test_P03_pagination_exhaustion(self):
        with self.assertRaises(plat.PlatformError): plat.paged(lambda *args: [{}] * 100, '/repos/owner/project/pulls')

    def test_P03_closed_merged_and_multiple(self):
        self.rows[1] = self.pr(state='closed')
        raw = self.adapter.read_change_request(1)
        with self.assertRaises(flow.Stop): flow.verify_mr(raw, self.f.ctx, raw['sha'])
        self.rows[1]['merged'] = True
        self.assertEqual(self.adapter.read_change_request(1)['state'], 'merged')
        self.rows[1] = self.pr(); self.rows[2] = self.pr(2)
        with self.assertRaises(plat.PlatformError):
            self.adapter.create_change_request(self.f.ctx, self.f.base, dict(title='x'), 'x', self.f.base)
        self.assertFalse(self.created)

    def test_P04_post_timeout_readback_no_retry(self):
        self.f.mr()
        self.f.q['mr']['declarations'] = [dict(path='decisions/D-01-test.md', instruction='fixture',
                                            authority_ref='evidence.md#授权', classification='语义级')]
        original = self.api
        def api(method, path, body=None):
            value = original(method, path, body)
            if method == 'POST': raise plat.ApiError('POST')
            return value
        self.adapter.api = api
        def refs(repo, ctx): return dict(main=self.f.base, work=self.f.git('rev-parse', 'HEAD'))
        with patch.object(flow, 'remote_refs', side_effect=refs):
            _, value, _ = flow.publish(self.f.repo, self.f.q, lambda repo: self.adapter)
        self.assertEqual(value['id'], 1); self.assertEqual(len(self.created), 1)

    def test_P05_unknown_403_and_main_refused(self):
        self.adapter.inspect_repository()
        self.error = plat.ApiError('GET', 403, False)
        with self.assertRaises(plat.PlatformError): self.adapter.inspect_repository()
        self.meta['private'] = False
        with self.assertRaises(plat.PlatformError): self.adapter.inspect_repository()
        with self.assertRaises(plat.PlatformError): self.adapter.find_change_requests('main', 'main')

    def test_P04_push_timeout_does_not_post(self):
        self.f.mr()
        self.f.q['mr']['declarations'] = [dict(path='decisions/D-01-test.md', instruction='fixture',
                                            authority_ref='evidence.md#授权', classification='语义级')]
        real_run = subprocess.run
        calls = []
        def run(args, *a, **kw):
            if 'push' in args:
                calls.append(args)
                raise subprocess.TimeoutExpired(args, 60)
            return real_run(args, *a, **kw)
        def refs(repo, ctx):
            return dict(main=self.f.base, work=self.f.git('rev-parse', 'HEAD')) if calls else dict(main=self.f.base)
        with patch.object(flow, 'remote_refs', side_effect=refs), patch.object(subprocess, 'run', side_effect=run):
            with self.assertRaises(flow.Stop) as caught:
                flow.publish(self.f.repo, self.f.q, lambda repo: self.adapter)
        self.assertEqual(caught.exception.status, 'external-unknown'); self.assertEqual(len(calls), 1)
        self.assertFalse(self.created)

    def test_P05_raw_error_is_readonly_exact_and_fail_closed(self):
        client = object.__new__(plat.GitHubAPI); client.root = str(self.f.root)
        endpoint = '/repos/owner/project/branches/main/protection'
        for code, message, expected in (
            (403, 'Upgrade to GitHub Pro or make this repository public to enable this feature.', True),
            (403, 'Resource not accessible by integration', False),
            (404, 'Upgrade to GitHub Pro or make this repository public to enable this feature.', False)):
            raw = f'HTTP/2.0 {code} Forbidden\ncontent-type: application/json\n\n' + json.dumps(dict(message=message))
            with patch.object(plat.shutil, 'which', return_value='/test/gh'), patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, raw, 'secret')) as run:
                self.assertEqual(client.protection_plan_required(endpoint), expected)
                argv = run.call_args.args[0]
                self.assertNotIn('POST', argv); self.assertIn(endpoint, argv)
        with self.assertRaises(plat.PlatformError): client.protection_plan_required('/repos/owner/project/pulls')

    def test_P08_cli_envelope_and_redaction(self):
        body = dict(head=dict(sha='a'*40), body='长文\n'*2000)
        envelope = 'api_response:\n  body: ' + base64.b64encode(json.dumps(body).encode()).decode() + '\n  truncated: false\n'
        client = object.__new__(plat.GitHubAPI); client.cli = '/test/gh-axi'; client.root = str(self.f.root)
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, envelope, '')):
            self.assertEqual(client('GET', '/repos/owner/project'), body)
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'HTTP 403 secret-value')):
            with self.assertRaises(plat.ApiError) as caught: client('GET', '/repos/owner/project')
            self.assertNotIn('secret-value', str(caught.exception)); self.assertFalse(caught.exception.plan_required)
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, envelope.replace('false', 'true'), '')):
            with self.assertRaises(plat.PlatformError): client('GET', '/repos/owner/project')


class LocalTransport(mig.Transport):
    def __init__(self, repo, q, source, target):
        self.repo, self.q = repo, q
        self.urls = dict(source=str(source), target=str(target))


class LocalPlatforms:
    def inspect_source(self): return None
    def inspect_target(self): return None
    def branches(self): return []


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture_module.Fixture(); self.f.setUp()
        # Fixture contains real required implementation bytes at the fixed main.
        for name in ('handoff_platform.py', 'handoff_migration.py', 'github_pr_api.py', 'HarnessPlane_Handoff_Protocol_Design_v1.md'):
            self.f.write('mechanisms/handoff-protocol/' + name, (Path(__file__).parent / name).read_text())
        self.f.commit('migration implementation'); self.h = self.f.seal()['handoff_commit']
        self.f.git('branch', '-f', 'main', self.h)
        self.f.git('tag', '-a', 'v1', '-m', 'annotated tag', self.h)
        tag = self.f.git('rev-parse', 'refs/tags/v1')
        self.f.git('checkout', '-b', 'migration')
        self.q = dict(schema='handoff-migration-request/v2', plan_ref=None, approval_ref=None,
                      source=dict(provider='gitlab', host='https://gitlab.example.test', repository='owner/project', repository_id='1'),
                      target=dict(provider='github', host='https://github.com', repository='owner/project', repository_id='2'),
                      source_git_url='https://gitlab.example.test/owner/project.git',
                      target_git_url='https://github.com/owner/project.git',
                      refs=[dict(ref='refs/heads/main', oid=self.h), dict(ref='refs/tags/v1', oid=tag)])
        plan = dict(schema='handoff-migration-plan/v2', **{k:self.q[k] for k in ('source', 'target', 'source_git_url', 'target_git_url', 'refs')},
                    retained_branch='migration', retained_base=self.h,
                    inventory={k:dict(disposition='retain', evidence='fixture inventory') for k in
                               'git_history large_objects lfs submodules archive_repository review_archives collaboration_assets external_callers in_flight'.split()},
                    verification={k:'evidence.md:2' for k in 'implementation history recovery first_pr'.split()},
                    source_window='fixture exclusive window', writer_exclusion='fixture excludes writers')
        self.plan_path = 'records/diagnostics/migration/2026-09-10/plan.md'
        self.approval_path = 'records/governance/handoff-protocol/Owner_Decisions_fixture.md'
        self.f.write(self.plan_path, '# Plan\n```migration-plan\n'+json.dumps(plan)+'\n```\n')
        p = self.f.commit('plan'); self.q['plan_ref'] = dict(commit=p, path=self.plan_path)
        approval = dict(schema='handoff-migration-approval/v1', plan_ref=self.q['plan_ref'], action='import')
        self.f.write(self.approval_path, '# Owner import approval\n```migration-approval\n'+json.dumps(approval)+'\n```\n')
        a = self.f.commit('approval'); self.q['approval_ref'] = dict(commit=a, path=self.approval_path, locator='Owner import approval')
        self.temp = tempfile.TemporaryDirectory(prefix='migration-test-remotes-')
        self.source, self.target = [Path(self.temp.name)/name for name in ('source.git', 'target.git')]
        for folder in (self.source, self.target):
            folder.mkdir(); mig.run(folder, ['init', '--bare'])
        self.f.git('push', str(self.source), 'refs/heads/main', 'refs/heads/migration', 'refs/tags/v1')
        self.transport = LocalTransport(self.f.repo, self.q, self.source, self.target)

    def tearDown(self):
        self.temp.cleanup(); self.f.tearDown()

    def execute(self, action='check', transport=None):
        out = dict(details=[], ref_results=[])
        mig.execute(self.f.repo, self.q, action, out, platforms=LocalPlatforms(), transport=transport or self.transport)
        return out

    def test_I01_check_readonly_and_exact_binding(self):
        before = self.f.git('show-ref'); head = self.f.git('rev-parse', 'HEAD')
        self.execute(); self.assertEqual(before, self.f.git('show-ref')); self.assertEqual(head, self.f.git('rev-parse', 'HEAD'))
        self.q['refs'][0]['oid'] = self.f.base
        with self.assertRaises(mig.Stop): self.execute()
        self.assertEqual(self.transport.refs('target'), {})

    def test_I02_nonempty_and_concurrent_different_same_extra(self):
        self.f.git('push', str(self.target), self.h+':refs/heads/other')
        with self.assertRaises(mig.Stop) as caught: self.execute('import')
        self.assertEqual(caught.exception.reason, 'target-not-empty')
        # Named-ref conditional creation cannot overwrite an existing different value.
        self.f.git('push', str(self.target), self.f.base+':refs/heads/main')
        self.assertEqual(self.transport.push(self.q['refs']), 'unknown')
        self.assertEqual(self.transport.refs('target')['refs/heads/main'], self.f.base)

    def test_I02_same_oid_not_claimed_as_created(self):
        self.f.git('push', str(self.target), self.h+':refs/heads/main')
        self.assertEqual(self.transport.push(self.q['refs']), 'reconciled')
        self.execute('verify')

    def test_I03_source_drift_and_extra(self):
        self.f.git('push', str(self.source), self.h+':refs/heads/unlisted')
        with self.assertRaises(mig.Stop) as caught: self.execute()
        self.assertEqual(caught.exception.reason, 'source-changed')
        self.assertEqual(self.transport.refs('target'), {})

    def test_I03_shallow_and_missing_history_source(self):
        original = self.f.repo.need
        def shallow(*args):
            return 'true' if args == ('rev-parse', '--is-shallow-repository') else original(*args)
        with patch.object(self.f.repo, 'need', side_effect=shallow), self.assertRaises(mig.Stop): self.execute()
        self.f.write('records/history-locations.jsonl', json.dumps(dict(source_commit='f'*40))+'\n')
        tip = self.f.commit('unreachable history')
        with self.assertRaises(mig.Stop) as caught:
            mig.verify_history(self.f.repo, [dict(ref='refs/heads/main', oid=tip)])
        self.assertEqual(caught.exception.reason, 'object-missing')

    def test_I03_source_rewritten_selected_ref(self):
        mig.run(self.source, ['update-ref', 'refs/heads/main', self.f.base])
        with self.assertRaises(mig.Stop) as caught: self.execute()
        self.assertEqual(caught.exception.reason, 'source-changed')
        self.assertFalse(self.transport.refs('target'))

    def test_I03_approval_not_matching_or_after_plan(self):
        self.q['approval_ref']['commit'] = self.q['plan_ref']['commit']
        with self.assertRaises(mig.Stop): self.execute()

    def test_I04_I06_I08_real_import_objects_tag_handoff_recovery(self):
        before = self.f.git('show-ref'); out = self.execute('import')
        self.assertTrue(all(r['state'] == 'matched' for r in out['ref_results']))
        self.assertEqual(self.transport.refs('target'), {r['ref']:r['oid'] for r in self.q['refs']})
        self.assertNotEqual(self.q['refs'][1]['oid'], self.h)
        self.execute('verify'); self.assertEqual(before, self.f.git('show-ref'))
        self.assertEqual(self.transport.refs('source')['refs/heads/main'], self.h)
        self.assertNotIn(self.q['plan_ref']['commit'], mig.run(self.target, ['rev-list', '--all']).decode())
        self.assertTrue(self.f.repo.ancestor(self.q['plan_ref']['commit'], self.q['approval_ref']['commit']))

    def test_I05_unknown_push_full_reconciliation_no_retry(self):
        original = self.transport.push; calls=[]
        def push(rows):
            calls.append(rows); original(rows); return 'unknown'
        with patch.object(self.transport, 'push', side_effect=push):
            out = self.execute('import')
        self.assertEqual(len(calls), 1); self.assertIn('归属未核', out['details'][-1])

    def test_I05_unknown_partial_and_extra_preserved(self):
        def push(rows):
            self.f.git('push', str(self.target), self.h+':refs/heads/main', self.h+':refs/heads/unlisted')
            return 'unknown'
        with patch.object(self.transport, 'push', side_effect=push), self.assertRaises(mig.Stop) as caught:
            self.execute('import')
        self.assertEqual(caught.exception.status, 'external-unknown')
        self.assertIn('refs/heads/unlisted', self.transport.refs('target'))

    def test_I07_atomic_unsupported_no_fallback(self):
        mig.run(self.target, ['config', 'receive.advertiseAtomic', 'false'])
        with self.assertRaises(mig.Stop) as caught: self.execute('import')
        self.assertEqual(caught.exception.reason, 'transport-unavailable')
        self.assertEqual(self.transport.refs('target'), {})

    def test_I03_bad_ref_closed_request(self):
        for ref in ('HEAD', 'refs/pull/1/head', 'refs/heads/*'):
            q = copy.deepcopy(self.q); q['refs'][0]['ref'] = ref
            with self.assertRaises((mig.Stop, data.Invalid)): mig.request(q)
        q = dict(self.q, force=True)
        with self.assertRaises(data.Invalid): mig.request(q)


if __name__ == '__main__':
    unittest.main(verbosity=2)
