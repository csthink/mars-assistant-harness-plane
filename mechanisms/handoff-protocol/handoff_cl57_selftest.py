#!/usr/bin/env python3
"""CL-57 隔离回归：精确批准、SSH、目标独立验证与共用 PR 入口。"""
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
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.dont_write_bytecode = True
import github_pr_api as entry
import handoff_cl56_selftest as fixtures
import handoff_data as data
import handoff_migration as mig
import handoff_platform as platform
import handoff_workflow as flow


class MigrationTests(unittest.TestCase):
    setUp = fixtures.MigrationTests.setUp
    tearDown = fixtures.MigrationTests.tearDown
    execute = fixtures.MigrationTests.execute

    def reapprove(self, change=None, disclosure=''):
        plan = mig.block(self.f.repo, self.q['plan_ref'], 'migration-plan')
        plan.update({key: self.q[key] for key in ('source', 'target', 'source_git_url', 'target_git_url', 'refs')})
        if change:
            change(plan)
        self.f.write(self.plan_path, '# Plan\n' + disclosure + '\n```migration-plan\n' + json.dumps(plan) + '\n```\n')
        self.q['plan_ref'] = dict(commit=self.f.commit('updated plan'), path=self.plan_path)
        approval = dict(schema='handoff-migration-approval/v1', plan_ref=self.q['plan_ref'], action='import')
        self.f.write(self.approval_path, '# Owner import approval\n```migration-approval\n' + json.dumps(approval) + '\n```\n')
        self.q['approval_ref']['commit'] = self.f.commit('updated approval')
        self.f.git('push', str(self.source), 'refs/heads/migration')

    def http_source(self, disclosure):
        self.q['source']['host'] = 'http://gitlab.example.test'
        self.q['source_git_url'] = 'git@gitlab.example.test:owner/project.git'
        self.q['target_git_url'] = 'git@github.com:owner/project.git'
        self.reapprove(disclosure=disclosure)

    def test_http_valid_plan_and_bound_approval_before_connections(self):
        self.http_source('http://gitlab.example.test；HTTP 本身不加密 API 凭据；读取和停写窗口见 source_window。')
        self.execute()
        self.q['approval_ref']['commit'] = 'f' * 40
        with patch.object(mig, 'Platforms') as apis, patch.object(mig, 'Transport') as transport:
            with self.assertRaises(mig.Stop) as caught:
                mig.execute(self.f.repo, self.q, 'import', dict(details=[]))
        self.assertEqual(caught.exception.reason, 'object-missing')
        apis.assert_not_called(); transport.assert_not_called()

    def test_http_missing_disclosure_before_any_platform_construction(self):
        self.http_source('目标 VPN 可用')
        with patch.object(mig, 'Platforms') as apis, patch.object(mig, 'Transport') as transport:
            with self.assertRaises(mig.Stop) as caught:
                mig.execute(self.f.repo, self.q, 'check', dict(details=[]))
        self.assertEqual(caught.exception.reason, 'conditions-unmet')
        apis.assert_not_called(); transport.assert_not_called()

    def test_old_versions_missing_extra_fields_and_redacted_result(self):
        for q in (dict(self.q, schema='handoff-migration-request/v1'), dict(self.q, extra=True),
                  {k:v for k,v in self.q.items() if k != 'target_git_url'}):
            with self.subTest(keys=list(q)), patch.object(mig, 'Platforms') as apis:
                with self.assertRaises((mig.Stop, data.Invalid)):
                    mig.execute(self.f.repo, q, 'import', dict(details=[]))
                apis.assert_not_called()
        q = dict(self.q, source_git_url='https://secret-user:secret-password@gitlab.example.test/owner/project.git')
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'request.json'; p.write_text(json.dumps(q))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = mig.main(['verify','--root', str(self.f.root),'--request',str(p),'--json'])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1); self.assertEqual(result['schema'], mig.RESULT_SCHEMA)
        self.assertIsNone(result['source_git_url']); self.assertNotIn('secret-', output.getvalue())
        self.assertEqual(set(result), set('schema action status reason plan_ref source target source_git_url target_git_url ref_results details'.split()))
        self.reapprove(lambda p: p.update(schema='handoff-migration-plan/v1'))
        with self.assertRaises(mig.Stop): self.execute()

    def test_both_git_urls_exact_plan_binding(self):
        for side in ('source','target'):
            old = self.q[side+'_git_url']
            self.q[side+'_git_url'] = 'git@' + old.removeprefix('https://').replace('/', ':', 1)
            with patch.object(mig, 'Platforms') as apis, self.assertRaises(mig.Stop):
                mig.execute(self.f.repo,self.q,'check',dict(details=[]))
            apis.assert_not_called(); self.q[side+'_git_url'] = old

    def test_verify_no_source_adapter_credentials_refs_after_head_and_origin_change(self):
        self.execute('import')
        self.f.write('target-first-pr.txt', 'authorized target fixture content')
        self.f.commit('target extra content after approval')
        self.f.git('remote','add','origin','git@github.com:owner/project.git')
        c = dict(schema='handoff-platform-config/v1', **self.q['target'], target_branch='main',
                 deployment='private-free', deployment_ref='evidence.md:2')
        target = Mock()
        target.inspect_repository.return_value = self.q['target']
        target.repository = dict(private=True, clone_url=self.q['target_git_url'], ssh_url='git@github.com:owner/project.git')
        target.endpoint = '/repos/owner/project'
        original = self.transport.refs
        def refs(side):
            self.assertEqual(side,'target')
            return original(side)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'config.json'; p.write_text(json.dumps(c))
            with patch.dict(os.environ, {'HANDOFF_PLATFORM_CONFIG':str(p)},clear=True), \
                 patch.object(flow,'Adapter',side_effect=AssertionError('source constructed')) as source, \
                 patch.object(platform,'GitHubAdapter',return_value=target) as factory, \
                 patch.object(self.transport,'refs',side_effect=refs):
                out=dict(details=[])
                mig.execute(self.f.repo,self.q,'verify',out,transport=self.transport)
                source.assert_not_called()
                self.assertIs(factory.call_args.kwargs['bind_origin'],False)
        self.assertEqual(target.inspect_repository.call_count,2)
        self.assertTrue(all(row['state']=='matched' for row in out['ref_results']))

    def test_verify_missing_local_objects_no_network(self):
        self.q['refs'][0]['oid']='e'*40
        with patch.object(mig,'Platforms') as apis, patch.object(mig,'Transport') as transport:
            with self.assertRaises(mig.Stop) as caught:
                mig.execute(self.f.repo,self.q,'verify',dict(details=[]))
        self.assertEqual(caught.exception.reason,'object-missing')
        apis.assert_not_called(); transport.assert_not_called()

    def test_local_proof_rejects_reverted_unapproved_commit(self):
        self.f.write('unapproved.txt','not allowed')
        self.f.commit('unapproved path')
        self.f.git('revert','--no-edit','HEAD')
        self.reapprove()
        with self.assertRaises(mig.Stop) as caught: self.execute('verify')
        self.assertEqual(caught.exception.reason,'source-changed')

    def test_source_approval_tip_drift_and_target_extra_refs_remain_blocked(self):
        self.execute('import')
        self.f.write('after.txt','after approval'); self.f.commit('extra')
        self.f.git('push',str(self.source),'refs/heads/migration')
        with self.assertRaises(mig.Stop) as caught: self.execute('check')
        self.assertEqual(caught.exception.reason,'source-changed')
        self.execute('verify')
        self.f.git('push',str(self.target),self.h+':refs/heads/first-pr')
        with self.assertRaises(mig.Stop): self.execute('verify')
        self.assertIn('refs/heads/first-pr',self.transport.refs('target'))

    def test_import_write_after_source_loss_only_reads_target(self):
        api=fixtures.LocalPlatforms(); pushed=[]; original=self.transport.push
        def source(): self.assertFalse(pushed, 'source inspected after push')
        def push(rows):
            value=original(rows); pushed.append(True); return value
        original_refs=self.transport.refs
        def refs(side):
            if side=='source': self.assertFalse(pushed,'source refs after push')
            return original_refs(side)
        with patch.object(api,'inspect_source',side_effect=source) as source_calls, \
             patch.object(self.transport,'push',side_effect=push) as push_calls, \
             patch.object(self.transport,'refs',side_effect=refs):
            mig.execute(self.f.repo,self.q,'import',dict(details=[]),platforms=api,transport=self.transport)
        self.assertEqual(source_calls.call_count,2); self.assertEqual(push_calls.call_count,1)

    def test_malformed_postwrite_readback_is_external_unknown(self):
        def invalid(*args): raise data.Invalid('fixture bad readback')
        with patch.object(mig,'verify_target',side_effect=invalid), self.assertRaises(mig.Stop) as caught:
            self.execute('import')
        self.assertEqual(caught.exception.status,'external-unknown')
        self.assertEqual(self.transport.refs('target'),{r['ref']:r['oid'] for r in self.q['refs']})

    def test_fixed_main_requires_v2_implementation(self):
        original=self.f.repo.file
        def file(commit,path):
            raw=original(commit,path)
            if commit==self.h and path.endswith('handoff_migration.py'):
                return raw.replace(b"REQUEST_SCHEMA = 'handoff-migration-request/v2'",b"REQUEST_SCHEMA = 'handoff-migration-request/v1'")
            return raw
        with patch.object(self.f.repo,'file',side_effect=file), self.assertRaises(mig.Stop) as caught:
            self.execute()
        self.assertEqual(caught.exception.reason,'conditions-unmet')


class AddressTests(unittest.TestCase):
    def setUp(self):
        self.source=dict(provider='gitlab',host='http://gitlab.example.test',repository='owner/project',repository_id='1')
        self.target=dict(provider='github',host='https://github.com',repository='owner/project',repository_id='2')

    def test_api_and_git_address_rejections(self):
        for host in ('http://user:secret@gitlab.example.test','https://gitlab.example.test/api','https://gitlab.example.test:444','https://gitlab.example.test?q=x'):
            with self.subTest(host=host), self.assertRaises(mig.Stop): mig.identity(dict(self.source,host=host),'gitlab')
        for address in ('http://github.com/owner/project.git','ssh://git@github.com:443/owner/project.git',
                        'https://github.com:22/owner/project.git','git@alias:owner/project.git',
                        'git@github.com:owner/other.git','ssh://root@github.com/owner/project.git',
                        'https://github.com/owner/project.git?token=secret'):
            with self.subTest(address=address), self.assertRaises(mig.Stop): mig.git_url(address,self.target)
        for address in ('https://github.com/owner/project.git','git@github.com:owner/project.git','ssh://git@github.com/owner/project.git'):
            mig.git_url(address,self.target)

    def test_api_advertised_addresses_match_without_replacing_transport(self):
        metadata=dict(http_url_to_repo='http://gitlab.example.test/owner/project.git',ssh_url_to_repo='git@gitlab.example.test:owner/project.git')
        mig.api_git_urls(metadata,self.source,metadata['ssh_url_to_repo'])
        for key in metadata:
            wrong=dict(metadata); wrong[key]=wrong[key].replace('owner/project','owner/other')
            with self.assertRaises(mig.Stop): mig.api_git_urls(wrong,self.source,metadata['ssh_url_to_repo'])

    def test_transport_only_target_and_rewrite_rejected(self):
        q=dict(source=self.source,target=self.target,source_git_url='git@gitlab.example.test:owner/project.git',target_git_url='git@github.com:owner/project.git')
        repo=Mock(root='/fixture')
        with patch.object(mig.Transport,'check_address') as check:
            transport=mig.Transport(repo,q,target_only=True)
            self.assertEqual(transport.urls,dict(target=q['target_git_url']))
            check.assert_called_once_with('/fixture',q['target_git_url'])
        with patch.object(mig,'run',return_value=b'git@wrong:owner/project.git\n'), self.assertRaises(mig.Stop):
            mig.Transport.check_address('/fixture',q['target_git_url'])

    def test_ssh_effective_host_and_noninteractive_strict_command(self):
        url='git@github.com:owner/project.git'
        good='hostname github.com\nuser git\nport 22\n'
        with patch.object(mig,'run',return_value=(url+'\n').encode()), \
             patch.object(subprocess,'run',return_value=subprocess.CompletedProcess([],0,good,'')) as run:
            mig.Transport.check_address('/fixture',url)
            args=run.call_args.args[0]
            self.assertIn('-G',args); self.assertIn('-oBatchMode=yes',args)
            self.assertIn('-oStrictHostKeyChecking=yes',args); self.assertIn('-oUpdateHostKeys=no',args)
            for raw in (good.replace('github.com','alias.example'),good.replace('22','2222'),good+'hostkeyalias other\n'):
                run.return_value=subprocess.CompletedProcess([],0,raw,'')
                with self.assertRaises(mig.Stop): mig.Transport.check_address('/fixture',url)

    def test_source_config_mismatch_before_credential_client_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            script=Path(folder)/'adapter.py'; script.write_text('# fixture')
            module=SimpleNamespace(load_config=Mock(return_value=SimpleNamespace(host='http://wrong.example',project='owner/project')),
                                   GitLabClient=Mock(),run_preflight=Mock(),verify_created_merge_request=Mock(),main=Mock())
            spec=SimpleNamespace(name='_fixture_gitlab',loader=SimpleNamespace(exec_module=Mock()))
            with patch.dict(os.environ,{'HANDOFF_GITLAB_MR_SCRIPT':str(script)},clear=True), \
                 patch.object(flow.importlib.util,'spec_from_file_location',return_value=spec), \
                 patch.object(flow.importlib.util,'module_from_spec',return_value=module), \
                 self.assertRaises(flow.Stop) as caught:
                flow.Adapter(Mock(),expected_identity=self.source)
            self.assertEqual(caught.exception.reason,'remote-mismatch')
            module.GitLabClient.assert_not_called()

    def test_ssh_push_atomic_empty_lease_and_no_prompt_configuration(self):
        transport=object.__new__(mig.Transport)
        transport.repo=SimpleNamespace(root='/fixture')
        transport.urls=dict(target='git@github.com:owner/project.git')
        rows=[dict(ref='refs/heads/main',oid='a'*40)]
        result=subprocess.CompletedProcess([],0,b'*\tnew:refs/heads/main\t[new branch]\n',b'')
        with patch.object(transport,'check_address'), patch.object(subprocess,'run',return_value=result) as run:
            self.assertEqual(transport.push(rows),'created')
        args=run.call_args.args[0]
        self.assertIn('--atomic',args); self.assertIn('--force-with-lease=refs/heads/main:',args)
        self.assertIn('a'*40+':refs/heads/main',args)
        self.assertIn('core.sshCommand='+mig.SSH_COMMAND,args)
        self.assertEqual(run.call_args.kwargs['env']['GIT_TERMINAL_PROMPT'],'0')
        self.assertEqual(run.call_count,1)


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.g=fixtures.GitHubTests(); self.g.setUp()
        self.f=self.g.f
        self.temp=tempfile.TemporaryDirectory()
        self.config=Path(self.temp.name)/'config.json'; self.config.write_text(json.dumps(self.g.c))
        self.req=Path(self.temp.name)/'request.json'
        self.f.mr()
        self.f.q['mr']['declarations']=[dict(path='decisions/D-01-test.md',instruction='fixture',authority_ref='evidence.md#授权',classification='语义级')]
        self.req.write_text(json.dumps(self.f.q))
        self.argv=['publish','--root',str(self.f.root),'--request',str(self.req),'--json']

    def tearDown(self): self.temp.cleanup(); self.g.tearDown()

    def invoke(self, fn):
        out=io.StringIO()
        with contextlib.redirect_stdout(out): code=fn(self.argv)
        return code,json.loads(out.getvalue())

    def test_missing_wrong_conflicting_config_before_shared_publish(self):
        before=self.f.git('rev-parse','HEAD')
        for env in ({},{'HANDOFF_PLATFORM_CONFIG':str(self.config),'HANDOFF_GITLAB_MR_SCRIPT':'unused'}):
            with patch.dict(os.environ,env,clear=True), patch.object(flow,'publish') as publish:
                code,out=self.invoke(entry.main)
                self.assertEqual(code,1); self.assertEqual(out['reason'],'input-invalid'); publish.assert_not_called()
        self.config.write_text(json.dumps(dict(self.g.c,provider='gitlab')))
        with patch.dict(os.environ,{'HANDOFF_PLATFORM_CONFIG':str(self.config)},clear=True), patch.object(flow,'publish') as publish:
            code,out=self.invoke(entry.main); self.assertEqual(code,1); publish.assert_not_called()
        self.assertEqual(self.f.git('rev-parse','HEAD'),before)

    def test_entry_and_direct_flow_share_real_prepare_create_and_idempotent_readback(self):
        def refs(repo,ctx): return dict(main=self.f.base,work=self.f.git('rev-parse','HEAD'))
        with patch.dict(os.environ,{'HANDOFF_PLATFORM_CONFIG':str(self.config)},clear=True), \
             patch.object(platform,'GitHubAdapter',return_value=self.g.adapter), \
             patch.object(flow,'remote_refs',side_effect=refs):
            first=self.invoke(entry.main)
            second=self.invoke(flow.main)
        self.assertEqual(first[0],0); self.assertEqual(second[0],0)
        for key in ('schema','status','content_commit','handoff_commit','mr'):
            self.assertEqual(first[1][key],second[1][key])
        self.assertEqual(len(self.g.created),1)
        self.assertIn('申报',self.g.created[0]['body'])

    def test_only_publish_no_prepare_merge_cleanup(self):
        for action in ('prepare','merge','check-cleanup'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): entry.main([action])


if __name__=='__main__':
    unittest.main(verbosity=2)
