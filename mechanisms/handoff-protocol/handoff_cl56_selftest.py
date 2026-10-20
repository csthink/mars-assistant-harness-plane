#!/usr/bin/env python3
"""GitHub 发布适配与独立入口 github-pr-api 的隔离验证。无真实平台写入。"""
import base64
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import github_pr_api as entry
import handoff_platform as plat
import handoff_workflow as flow
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

    def test_P01_missing_config_and_push_url(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(flow.Stop) as caught:
            flow.select_adapter(self.f.repo)
        self.assertEqual((caught.exception.reason, caught.exception.status), ('input-invalid', 'not-checked'))
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


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.g = GitHubTests(); self.g.setUp()
        self.f = self.g.f
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name)/'config.json'; self.config.write_text(json.dumps(self.g.c))
        self.req = Path(self.temp.name)/'request.json'
        self.f.mr()
        self.f.q['mr']['declarations'] = [dict(path='decisions/D-01-test.md', instruction='fixture',
                                            authority_ref='evidence.md#授权', classification='语义级')]
        self.req.write_text(json.dumps(self.f.q))
        self.argv = ['publish', '--root', str(self.f.root), '--request', str(self.req), '--json']

    def tearDown(self):
        self.temp.cleanup(); self.g.tearDown()

    def invoke(self, fn):
        out = io.StringIO()
        with contextlib.redirect_stdout(out): code = fn(self.argv)
        return code, json.loads(out.getvalue())

    def test_missing_or_wrong_config_before_shared_publish(self):
        before = self.f.git('rev-parse', 'HEAD')
        with patch.dict(os.environ, {}, clear=True), patch.object(flow, 'publish') as publish:
            code, out = self.invoke(entry.main)
            self.assertEqual(code, 1); self.assertEqual(out['reason'], 'input-invalid'); publish.assert_not_called()
        self.config.write_text(json.dumps(dict(self.g.c, provider='gitlab')))
        with patch.dict(os.environ, {'HANDOFF_PLATFORM_CONFIG': str(self.config)}, clear=True), patch.object(flow, 'publish') as publish:
            code, out = self.invoke(entry.main); self.assertEqual(code, 1); publish.assert_not_called()
        self.assertEqual(self.f.git('rev-parse', 'HEAD'), before)

    def test_entry_and_direct_flow_share_real_prepare_create_and_idempotent_readback(self):
        def refs(repo, ctx): return dict(main=self.f.base, work=self.f.git('rev-parse', 'HEAD'))
        with patch.dict(os.environ, {'HANDOFF_PLATFORM_CONFIG': str(self.config)}, clear=True), \
             patch.object(plat, 'GitHubAdapter', return_value=self.g.adapter), \
             patch.object(flow, 'remote_refs', side_effect=refs):
            first = self.invoke(entry.main)
            second = self.invoke(flow.main)
        self.assertEqual(first[0], 0); self.assertEqual(second[0], 0)
        for key in ('schema', 'status', 'content_commit', 'handoff_commit', 'mr'):
            self.assertEqual(first[1][key], second[1][key])
        self.assertEqual(len(self.g.created), 1)
        self.assertIn('申报', self.g.created[0]['body'])

    def test_only_publish_no_prepare_merge_cleanup(self):
        for action in ('prepare', 'merge', 'check-cleanup'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): entry.main([action])


if __name__ == '__main__':
    unittest.main(verbosity=2)
