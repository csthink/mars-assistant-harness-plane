#!/usr/bin/env python3
"""CL-53 S1-S15、S17-S20 本地验收：独立 Git 仓 + 可观察平台替身，无真实网络写入。
S16 须在实际合并整理后由新客户端会话验证，本测试不冒充它。
"""
import copy
import contextlib
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
import handoff_data as data
import handoff_lint as lint
import handoff_status as status
import handoff_workflow as flow

TASK = 'repo-od-01'
PROGRESS = f'HANDOFF/progress/{TASK}.md'
AT = '- 2026-09-07T18:00 · '


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='handoff-contract-')
        self.root = Path(self.temp.name).resolve(); self.repo = status.Repository(str(self.root))
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'local test'); self.git('config', 'user.email', 'local@example.invalid')
        self.git('config', 'commit.gpgsign', 'false'); self.git('config', 'core.hooksPath', '/dev/null')
        self.write('HANDOFF/progress/repo.md', '# task: repo\n- 类别: 仓级\n' + AT + 'open · repo:OD-01 · OD · 本地测试 · 被什么挡住：待授权\n')
        self.write('evidence.md', '# 验证\n已核授权和本批条件。\n')
        self.write('.gitignore', 'ignored-artifact\n')
        self.commit('initial'); self.base = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/main', self.base)
        self.git('checkout', '-b', 'work')
        self.write(PROGRESS, f'# task: {TASK}\n- 类别: 台账任务 · 承载项 repo:OD-01 · 分支意图 old-removed\n')
        self.ctx = dict(version=1, source_branch='work', target_branch='main', base_commit=self.base, authority_ref='evidence.md#授权')
        self.append('context', self.ctx); self.commit('context')
        self.q = dict(schema='handoff-workflow-request/v2', task=TASK, mode='pause', paths=[],
                      authority_refs=['evidence.md#授权'], conditions=[], generators=[], mr=None,
                      handoff=dict(summary=dict(completed=['已核成果'], remaining=['实际新会话待验']),
                                   evidence=[dict(commit=self.base, path='evidence.md', locator='§1')],
                                   entries=[dict(path='evidence.md', role='current')],
                                   next=dict(kind='wait-owner', text='执行下一步', authority_ref=None), after_merge=None))

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')
        p = subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, text=True, env=env)
        if p.returncode:
            raise RuntimeError(p.stderr)
        return p.stdout.strip()

    def write(self, path, value):
        p = self.root / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)

    def commit(self, message):
        paths = self.git('ls-files', '--modified', '--others', '--exclude-standard').splitlines()
        if paths:
            self.git('add', '--', *paths)
        self.git('commit', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def append(self, kind, obj, path=PROGRESS):
        with (self.root / path).open('a') as f:
            f.write(AT + kind + ' · ' + (json.dumps(obj, ensure_ascii=False, separators=(',', ':')) if isinstance(obj, dict) else obj) + '\n')

    def mr(self):
        self.q['handoff']['after_merge'] = dict(next=dict(kind='wait-owner', text='施工后续批次', authority_ref=None), basis_ref='evidence.md#后续计划')
        self.q['mode'] = 'mr'; self.q['conditions'] = [dict(requirement_ref='evidence.md#条件', evidence_ref='evidence.md#证据', result='met')]
        self.q['mr'] = dict(title='本地测试', summary='验证交接先于发布', declarations=[])
        return self.q

    def seal(self):
        return flow.prepare(self.repo, self.q)

    def merge(self, no_ff=False):
        self.git('checkout', 'main'); self.git('merge', '--no-ff' if no_ff else '--ff-only', 'work', '-m', 'merge')
        self.git('branch', '-d', 'work'); self.git('update-ref', 'refs/remotes/origin/main', self.git('rev-parse', 'HEAD'))

    def resume(self, task=None):
        snap = status.compute(str(self.root), task, True)
        self.assert_human_snapshot(snap)
        return snap

    def assert_human_snapshot(self, snap, selected=None):
        before = copy.deepcopy(snap)
        with patch.object(status.Repository, 'run', side_effect=AssertionError('render reads Git')):
            text = status.render(snap, selected)
        self.assertEqual(snap, before)
        for heading in ('## 1 等 Owner 拍板', '## 2 在办', '## 3 刚落地', '## 4 下一步'):
            self.assertEqual(text.splitlines().count(heading), 1)
        for note in snap['notes']:
            self.assertIn(note, text)
        for row in snap['pending_owner']:
            self.assertIn(row['id'], text); self.assertIn(row['blocked_by'], text)
            self.assertIn('登记于 ' + row['opened_at'], text)
        for row in snap['in_progress']:
            for key in ('task', 'category', 'branch', 'state'):
                self.assertIn(row[key], text)
            if row['latest']:
                self.assertIn(row['latest']['text'], text)
            if row['branch_note']:
                self.assertIn(row['branch_note'], text)
            if row.get('handoff'):
                for value in sum(row['handoff']['summary'].values(), []):
                    self.assertIn(value, text)
        for row in snap['landed']:
            self.assertIn(row['commit'], text)
            if row.get('summary') is not None:
                for value in sum(row['summary'].values(), []):
                    self.assertIn(value, text)
            else:
                self.assertIn(row['text'], text)
        for row in snap['next']:
            if row['text'] is not None:
                self.assertIn(row['text'], text)
            if row.get('handoff_next') and row['handoff_next']['authority_ref']:
                self.assertIn(row['handoff_next']['authority_ref'], text)
        if snap.get('resume'):
            for value in snap['resume']['reasons'] + snap['resume']['candidates']:
                self.assertIn(value, text)
            for key in ('status', 'location', 'content_commit', 'handoff_commit'):
                if snap['resume'][key] is not None:
                    self.assertIn(snap['resume'][key], text)
        return text

    def selected_presentation(self, snap):
        r = snap['resume']
        task = self.repo.task_at(r['handoff_commit'], r['task'])
        return dict(task=r['task'], commit=r['handoff_commit'], event=status.last_event(task, 'handoff'))

    def legacy_handoff(self, mode='mr'):
        payload = {k: v for k, v in self.q['handoff'].items() if k != 'after_merge'}
        self.append('handoff', dict(version=1, mode=mode, content_commit=self.git('rev-parse', 'HEAD'), **payload))
        h = self.commit('historical v1 H')
        return status.validate_handoff(self.repo, self.repo.task_at(h, TASK), h)

    def assert_next(self, expected, reason=None):
        for task, resume in ((None, False), (TASK, False), (None, True), (TASK, True)):
            snap = status.compute(str(self.root), task, resume)
            self.assert_human_snapshot(snap)
            self.assertEqual(snap['schema'], 'handoff-status/v3')
            row = next(n for n in snap['next'] if n['task'] == TASK)
            self.assertEqual(row['handoff_next'], expected)
            if snap['resume']:
                self.assertEqual(snap['resume']['next'], expected)
                self.assertEqual(snap['resume']['status'], 'ready')
                if reason:
                    self.assertIn(reason, snap['resume']['reasons'])
            if reason:
                self.assertEqual(row['text'], reason)
            if expected and expected['kind'] == 'none':
                self.assertIsNone(row['text'])
                self.assertIn('本批无后续动作', status.render(snap))

    def test_resume_main_advice_is_not_an_unverified_todo(self):
        self.mr()
        self.q['handoff']['after_merge']['next'] = dict(
            kind='continue-authorized', text='核实同步并清理本批分支；随后继续已授权业务',
            authority_ref='evidence.md#授权')
        self.seal()
        snap = self.resume(TASK)
        source_text = self.assert_human_snapshot(snap)
        self.assertIn('当前下一步', source_text)
        self.assertNotIn('执行状态未核验', source_text)
        self.git('checkout', 'main'); self.git('merge', '--ff-only', 'work')
        for retained in (True, False):
            if not retained:
                self.git('branch', '-d', 'work')
            for task, resume in ((None, False), (TASK, False), (None, True), (TASK, True)):
                with self.subTest(retained=retained, task=task, resume=resume):
                    snap = status.compute(str(self.root), task, resume)
                    text = self.assert_human_snapshot(snap)
                    self.assertEqual(snap['next'][0]['handoff_next'], self.q['handoff']['after_merge']['next'])
                    self.assertIn('交接中的合并后建议', text)
                    self.assertIn('执行状态未核验', text)
                    self.assertIn('不推断已完成', text)
                    self.assertIn('随后继续已授权业务', text)
                    self.assertNotIn('所选恢复来源未列入本次在办清单', text)
                    if resume:
                        if snap['resume']['candidates']:
                            self.assertIn('候选仅用于选择恢复来源，不是在办任务或待办清单。', text)
                        self.assertNotIn('- 当前下一步：', text)

    def test_resume_closed_task_keeps_history_without_reopening(self):
        self.append('answer', 'repo:OD-01 · Owner 原话「完成」'); self.commit('terminal')
        self.mr(); self.seal(); self.merge()
        snap = self.resume(TASK)
        text = self.assert_human_snapshot(snap, self.selected_presentation(snap))
        self.assertEqual(snap['in_progress'], [])
        self.assertEqual(snap['next'], [])
        self.assertEqual(snap['resume']['next'], self.q['handoff']['after_merge']['next'])
        self.assertIn('所选恢复来源未列入本次在办清单', text)
        self.assertIn('交接记录不重开已闭合任务', text)
        self.assertIn('施工后续批次', text)
        self.assertIn('不能直接列为当前待办', text)
        self.assertNotIn('- 当前下一步：', text)

    def test_resume_warehouse_record_is_not_a_task_to_close(self):
        self.q['task'] = 'repo'
        self.append('context', self.ctx, 'HANDOFF/progress/repo.md'); self.commit('repo context')
        self.mr(); self.seal(); self.merge()
        snap = self.resume()
        text = self.assert_human_snapshot(snap)
        self.assertEqual(snap['resume']['task'], 'repo')
        self.assertEqual(snap['resume']['status'], 'ready')
        self.assertNotIn('repo', [e['task'] for e in snap['in_progress']])
        self.assertIn('仓级记录也不据此变成待办', text)
        self.assertIn('交接中的合并后建议', text)
        self.assertNotIn('- 当前下一步：', text)

    def test_C07_same_handoff_once_in_all_human_modes(self):
        self.mr(); self.seal()
        for location in ('source', 'main'):
            if location == 'main':
                self.merge()
            for task, resume in ((None, False), (TASK, False), (None, True), (TASK, True)):
                with self.subTest(location=location, task=task, resume=resume):
                    snap = status.compute(str(self.root), task, resume)
                    selected = self.selected_presentation(snap) if snap['resume'] else None
                    text = self.assert_human_snapshot(snap, selected)
                    self.assertEqual(text.count('成果：已核成果'), 1)
                    self.assertEqual(text.count('残留：实际新会话待验'), 1)
                    self.assertEqual(text.count(snap['next'][0]['handoff_next']['text']), 1)
                    self.assertNotIn('交接完成与残留：', text)
                    if selected:
                        self.assertIn('交接声明见“接手 / ' + TASK, text)

    def test_C07_terminal_missing_landed_uses_cli_H_and_json_never_reads_it(self):
        self.append('answer', 'repo:OD-01 · Owner 原话「完成」'); self.commit('terminal')
        self.mr(); self.seal(); self.merge()
        snap = self.resume(TASK); snap['landed'] = []
        self.assertEqual(snap['in_progress'], [])
        self.assertIn('summary 未随本次呈现输入提供', status.render(snap))
        with patch.object(status, 'compute', return_value=snap):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = status.main(['--root', str(self.root), '--resume', '--task', TASK])
            self.assertEqual(code, 0)
            self.assertEqual(out.getvalue().count('成果：已核成果'), 1)
            self.assertIn('施工后续批次', out.getvalue())
            self.assertNotIn('summary 未随本次呈现输入提供', out.getvalue())
            for args in ([], ['--task', TASK], ['--resume'], ['--resume', '--task', TASK]):
                with patch.object(status.Repository, 'task_at', side_effect=AssertionError('JSON supplemental read')):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        code = status.main(['--root', str(self.root), '--json', *args])
                    self.assertEqual(code, 0)
                    self.assertEqual(out.getvalue(), json.dumps(snap, ensure_ascii=False, indent=1) + '\n')
            with patch.object(status.Repository, 'task_at', side_effect=status.Unavailable('evidence-missing', 'missing H')):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), self.assertRaises(status.Unavailable):
                    status.main(['--root', str(self.root), '--resume'])
                self.assertEqual(out.getvalue(), '')

    def test_C07_identical_text_does_not_merge_other_events_or_array_members(self):
        self.q['handoff']['summary']['completed'] = ['重复成员', '重复成员']
        self.mr(); self.seal(); self.merge(); snap = self.resume(TASK)
        selected = self.selected_presentation(snap)
        other = copy.deepcopy(snap['landed'][0]); other['task'] = 'other-task'
        prior = copy.deepcopy(snap['landed'][0]); prior['commit'] = self.base
        snap['landed'].extend([other, prior])
        text = self.assert_human_snapshot(snap, selected)
        self.assertEqual(text.count('成果：重复成员'), 6)
        self.assertIn('other-task', text); self.assertIn(self.base, text)
        snap['in_progress'][0]['handoff']['summary']['completed'] = ['未核原记录']
        text = self.assert_human_snapshot(snap, selected)
        self.assertIn('未核原记录', text)
        single_old = self.resume(TASK)
        single_old['landed'][0]['commit'] = self.base
        text = self.assert_human_snapshot(single_old, selected)
        self.assertEqual(text.count('成果：重复成员'), 4)
        self.assertIn(self.base, text)
        selected['commit'] = self.base
        with self.assertRaises(ValueError):
            status.render(snap, selected)

    def test_C07_empty_summary_none_authority_and_conflicting_next(self):
        self.q['handoff']['summary'] = dict(completed=[], remaining=[])
        self.q['handoff']['next'] = dict(kind='continue-authorized', text='继续已授权步骤', authority_ref='evidence.md:2')
        self.seal(); snap = self.resume(TASK)
        text = self.assert_human_snapshot(snap, self.selected_presentation(snap))
        self.assertIn('成果声明：无', text); self.assertIn('残留声明：无', text)
        self.assertEqual(text.count('继续已授权步骤'), 1); self.assertIn('授权依据：evidence.md:2', text)
        snap['resume']['next'] = dict(kind='wait-owner', text='不一致建议', authority_ref=None)
        text = status.render(snap)
        self.assertIn('继续已授权步骤', text); self.assertIn('不一致建议', text)
        snap['next'] = []; snap['resume']['next'] = dict(kind='none', text=None, authority_ref=None)
        self.assertIn('本批无后续动作', status.render(snap))

    def test_C11_original_registration_rows_and_existing_targets_only(self):
        self.seal(); snap = self.resume(); row = snap['pending_owner'][0]
        self.assertEqual(row['id'], 'repo:OD-01')
        row['blocked_by'] = '旧阶段仍在办；原始登记时间来自转录说明'
        second = copy.deepcopy(snap['in_progress'][0]); second['task'] = 'another-task'
        snap['in_progress'].append(second)
        text = self.assert_human_snapshot(snap)
        section = text.split('## 1 等 Owner 拍板\n')[1].split('\n## 2 在办\n')[0]
        lines = [line for line in section.splitlines() if line.strip()]
        self.assertEqual(len(lines), len(snap['pending_owner']))
        self.assertTrue(lines[0].startswith('- repo:OD-01 · '))
        self.assertIn('原登记说明：' + row['blocked_by'], lines[0])
        self.assertIn('2 在办 / another-task', lines[0])
        self.assertNotIn('4 下一步 / another-task', lines[0])
        snap['in_progress'] = []
        section = status.render(snap).split('## 1 等 Owner 拍板\n')[1].split('\n## 2 在办\n')[0]
        self.assertNotIn('最近记录见', section)
        self.assertEqual(self.resume(TASK)['pending_owner'], [])
        self.assertIn('## 1 等 Owner 拍板\n- 无\n', status.render(self.resume(TASK)))
        self.append('answer', 'repo:OD-01 · Owner 原话「完成」'); self.commit('closure')
        self.assertEqual(self.resume()['pending_owner'], [])

    def test_C07_human_cli_readonly_and_json_stable_on_same_fixture(self):
        self.mr(); self.seal(); self.merge(); self.write('ignored-artifact', 'retained ignored bytes')
        before = flow.working_fingerprints(self.repo)
        refs = self.git('show-ref'); index = (self.root/'.git/index').read_bytes()
        registration = self.git('worktree', 'list', '--porcelain'); run = status.Repository.run
        def readonly(repo, *args):
            self.assertFalse(set(args) & {'fetch', 'push', 'ls-remote', 'commit', 'update-ref', 'checkout'})
            return run(repo, *args)
        with patch.object(status.Repository, 'run', readonly):
            for args in ([], ['--task', TASK], ['--resume'], ['--resume', '--task', TASK]):
                snap = status.compute(str(self.root), TASK if '--task' in args else None, '--resume' in args)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    human_code = status.main(['--root', str(self.root), *args])
                self.assertEqual(out.getvalue().count('成果：已核成果'), 1)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    json_code = status.main(['--root', str(self.root), '--json', *args])
                self.assertEqual(human_code, json_code)
                self.assertEqual(out.getvalue(), json.dumps(snap, ensure_ascii=False, indent=1) + '\n')
        self.assertEqual(before, flow.working_fingerprints(self.repo))
        self.assertEqual(refs, self.git('show-ref')); self.assertEqual(index, (self.root/'.git/index').read_bytes())
        self.assertEqual(registration, self.git('worktree', 'list', '--porcelain'))

    def test_S17_v2_mr_source_then_main_retained(self):
        self.mr(); proof = self.seal(); self.assert_next(self.q['handoff']['next'])
        self.git('update-ref', 'refs/heads/main', proof['handoff_commit'])
        before, refs = flow.working_fingerprints(self.repo), self.git('show-ref')
        run = status.Repository.run
        def readonly(repo, *args):
            self.assertFalse(set(args) & {'fetch', 'push', 'ls-remote', 'commit', 'update-ref', 'checkout'})
            return run(repo, *args)
        with patch.object(status.Repository, 'run', readonly):
            self.assert_next(self.q['handoff']['after_merge']['next'])
        self.assertEqual(before, flow.working_fingerprints(self.repo)); self.assertEqual(refs, self.git('show-ref'))

    def test_S17_v2_mr_normal_merge_deleted_source(self):
        self.mr(); self.seal(); self.merge(no_ff=True)
        self.assert_next(self.q['handoff']['after_merge']['next'])

    def test_S17_v2_pause_landed_missing_next(self):
        self.seal(); self.merge(); self.assert_next(None, status.MISSING_AFTER_MERGE)

    def test_S17_v1_modes_landed_missing_next(self):
        for mode in ('pause', 'mr'):
            with self.subTest(mode=mode):
                f = Fixture(); f.setUp()
                try:
                    f.legacy_handoff(mode); f.assert_next(f.q['handoff']['next'])
                    f.merge(); f.assert_next(None, status.MISSING_AFTER_MERGE)
                finally:
                    f.tearDown()

    def test_S17_explicit_none_does_not_close_task(self):
        self.mr(); self.q['handoff']['after_merge']['next'] = dict(kind='none', text=None, authority_ref=None)
        self.seal(); self.merge(); self.assert_next(self.q['handoff']['after_merge']['next'])
        self.assertTrue(self.resume()['in_progress'])

    def test_S18_own_event_reference_and_legal_append(self):
        self.append('open', TASK + ':OD-01 · OD · 已核后续 · 待授权'); self.commit('own item')
        self.mr(); self.q['handoff']['entries'].append(dict(path=PROGRESS, role='current'))
        self.q['handoff']['after_merge']['basis_ref'] = PROGRESS + ':3'
        self.seal(); self.merge(); self.append('answer', TASK + ':OD-01 · Owner 原话「记录」'); self.commit('legal answer')
        self.assert_next(self.q['handoff']['after_merge']['next'])

    def test_S18_invalid_reference_no_commit(self):
        self.mr(); original = copy.deepcopy(self.q)
        for ref in ('missing.md#x', 'evidence.md:999', 'evidence.md', PROGRESS + ':1', PROGRESS + ':999', PROGRESS + '#context', 'repo:OD-99'):
            with self.subTest(ref=ref):
                self.q = copy.deepcopy(original); self.q['handoff']['after_merge']['basis_ref'] = ref
                before = self.git('rev-parse', 'HEAD')
                with self.assertRaises(status.Unavailable): self.seal()
                self.assertEqual(before, self.git('rev-parse', 'HEAD'))
        self.q = original; self.q['handoff']['entries'][0]['role'] = 'history'
        with self.assertRaisesRegex(status.Unavailable, 'current'): self.seal()

    def test_S18_both_authorizations_and_new_basis_in_C(self):
        self.mr(); self.write('plan.md', '# 后续计划\n'); self.q['paths'] = ['plan.md']
        self.q['handoff']['entries'].append(dict(path='plan.md', role='current'))
        self.q['handoff']['after_merge']['basis_ref'] = 'plan.md:1'
        for stage in (self.q['handoff'], self.q['handoff']['after_merge']):
            stage['next'] = dict(kind='continue-authorized', text='执行已授权一步', authority_ref='evidence.md:2')
        proof = self.seal(); self.assertEqual(self.repo.file(proof['content_commit'], 'plan.md'), b'# \xe5\x90\x8e\xe7\xbb\xad\xe8\xae\xa1\xe5\x88\x92\n')
        self.merge(); self.write('plan.md', '# changed\n'); self.commit('unhanded basis change')
        snap = self.resume(TASK); self.assertIsNone(snap['resume']['next']); self.assertEqual(snap['conclusion'], 'NOT_CHECKED')
        self.assertIsNone(snap['next'][0]['handoff_next'])

    def test_S18_ambiguous_ledger_reference(self):
        self.mr(); self.q['handoff']['after_merge']['basis_ref'] = 'repo:OD-01'
        self.q['handoff']['entries'].append(dict(path='HANDOFF/progress/repo.md', role='current'))
        self.append('open', 'repo:OD-01 · OD · duplicate · test', 'HANDOFF/progress/repo.md')
        self.commit('ambiguous reference')
        with self.assertRaises(status.Unavailable): self.seal()

    def test_S18_each_missing_authorization_refused(self):
        self.mr(); original = copy.deepcopy(self.q)
        for after in (False, True):
            self.q = copy.deepcopy(original)
            step = self.q['handoff']['after_merge'] if after else self.q['handoff']
            step['next'] = dict(kind='continue-authorized', text='已授权动作', authority_ref='missing.md:1')
            before = self.git('rev-parse', 'HEAD')
            with self.assertRaises(status.Unavailable): self.seal()
            self.assertEqual(before, self.git('rev-parse', 'HEAD'))

    def test_S17_terminal_mr_none_stays_terminal(self):
        self.append('answer', 'repo:OD-01 · Owner 原话「完成」'); self.commit('terminal')
        self.mr(); self.q['handoff']['after_merge']['next'] = dict(kind='none', text=None, authority_ref=None)
        self.seal(); self.merge(); snap = self.resume(TASK)
        self.assertEqual(snap['in_progress'], [])
        self.assertEqual(snap['resume']['next'], self.q['handoff']['after_merge']['next'])
        self.assertEqual(snap['resume']['status'], 'ready')
        self.assertIn('交接写入时', status.render(snap))

    def test_S19_new_task_file_can_enter_C(self):
        new = 'repo-od-02'; path = f'HANDOFF/progress/{new}.md'
        self.write(path, f'# task: {new}\n- 类别: 台账任务 · 承载项 repo:OD-02 · 分支意图 work\n')
        self.append('context', self.ctx, path)
        self.q['task'] = new; self.q['paths'] = [path]; self.mr()
        fake, refs, calls = self.fake_publish()
        def create(adapter, ctx, h, mr, description, target_sha):
            calls.append('POST')
            return dict(iid=1, web_url='https://example.invalid/1', source_branch='work', target_branch='main', sha=h, state='opened')
        fake.create_change_request = create
        with patch.object(flow, 'remote_refs', side_effect=refs):
            proof, mr, reason = flow.publish(self.repo, self.q, fake)
        self.assertEqual(proof['handoff']['version'], 2)
        self.assertIn(path, self.repo.files(proof['content_commit']))

    def test_S19_old_GET_failure_preserves_original_H(self):
        old = self.legacy_handoff(); self.mr(); fake, refs, calls = self.fake_publish()
        def failed(*args):
            raise flow.Stop('tool-unavailable', 'GET failed', 'not-checked')
        with patch.object(fake, 'find_change_requests', failed), patch.object(flow, 'remote_refs', side_effect=refs), self.assertRaises(flow.Stop):
            flow.publish(self.repo, self.q, fake)
        self.assertEqual(self.git('rev-parse', 'HEAD'), old['handoff_commit'])
        self.assertNotIn('POST', calls)

    def test_S19_old_request_rejected_before_any_side_effect(self):
        self.mr(); self.q['schema'] = 'handoff-workflow-request/v1'; self.q['handoff'].pop('after_merge')
        fake, refs, calls = self.fake_publish(); before = self.git('rev-parse', 'HEAD')
        with patch.object(flow, 'remote_refs', side_effect=refs), self.assertRaises(data.Unsupported):
            flow.publish(self.repo, self.q, fake)
        self.assertEqual(calls, []); self.assertEqual(before, self.git('rev-parse', 'HEAD'))
        with tempfile.TemporaryDirectory() as directory:
            request = Path(directory) / 'request.json'; request.write_text(json.dumps(self.q))
            run = subprocess.run([sys.executable, '-B', flow.__file__, 'prepare', '--root', str(self.root), '--request', str(request)], capture_output=True, text=True)
            result = json.loads(run.stdout); self.assertEqual(run.returncode, 2)
            self.assertEqual((result['status'], result['reason']), ('not-checked', 'input-invalid'))
            self.assertIn('v2', result['details'][0]); self.assertEqual(before, self.git('rev-parse', 'HEAD'))

    def test_S19_v1_migration_and_after_merge_comparison(self):
        old = self.legacy_handoff(); old_bytes = self.repo.file(old['handoff_commit'], PROGRESS)
        self.mr(); one = self.seal(); self.assertEqual(one['handoff']['version'], 2)
        self.assertEqual(one['content_commit'], old['handoff_commit']); self.assertEqual(one, self.seal())
        self.q['handoff']['after_merge']['basis_ref'] = 'evidence.md:2'; two = self.seal()
        self.assertNotEqual(one['handoff_commit'], two['handoff_commit'])
        self.q['handoff']['after_merge']['next']['text'] = '另一已核建议'; three = self.seal()
        self.assertNotEqual(two['handoff_commit'], three['handoff_commit'])
        self.assertTrue(self.repo.file(three['handoff_commit'], PROGRESS).startswith(old_bytes))

    def test_S19_old_unknown_uses_original_GET_before_migration(self):
        old = self.legacy_handoff(); self.mr(); h = old['handoff_commit']
        mr = dict(iid=1, web_url='https://example.invalid/1', source_branch='work', target_branch='main', sha=h, state='opened')
        fake, refs, calls = self.fake_publish([mr])
        with patch.object(flow, 'remote_refs', side_effect=refs):
            proof, result, reason = flow.publish(self.repo, self.q, fake)
        self.assertEqual(proof, old); self.assertEqual(self.git('rev-parse', 'HEAD'), h)
        self.assertEqual(calls, ['adapter', 'GET', 'readback'])

    def test_S19_old_landed_no_migration_only_MR(self):
        old = self.legacy_handoff(); self.mr(); h = old['handoff_commit']; self.git('update-ref', 'refs/heads/main', h)
        fake, refs, calls = self.fake_publish()
        with patch.object(flow, 'remote_refs', return_value={'main': h, 'work': h}):
            proof, mr, reason = flow.publish(self.repo, self.q, fake)
        self.assertEqual(proof, old); self.assertEqual(reason, 'already-landed')
        self.assertEqual(self.git('rev-parse', 'HEAD'), h); self.assertNotIn('POST', calls)

    def test_S20_main_successor_replaces_all_fields(self):
        self.mr(); first = self.seal()
        self.q['handoff']['summary']['completed'] = ['后继成果']
        self.q['handoff']['after_merge']['next']['text'] = '后继建议'
        second = self.seal(); self.git('update-ref', 'refs/heads/main', second['handoff_commit'])
        self.git('checkout', '-b', 'advanced')
        self.git('branch', '-f', 'work', first['handoff_commit']); self.git('checkout', 'work')
        snap = self.resume(TASK); self.assertEqual(snap['resume']['handoff_commit'], second['handoff_commit'])
        self.assertEqual(snap['in_progress'][0]['handoff'], second['handoff'])
        self.assertEqual(snap['landed'][0]['commit'], second['handoff_commit'])
        self.assertEqual(snap['landed'][0]['summary'], second['handoff']['summary'])
        self.assert_next(second['handoff']['after_merge']['next'])

    def test_S20_local_unhanded_material_blocks_old_main(self):
        self.mr(); first = self.seal(); self.git('update-ref', 'refs/heads/main', first['handoff_commit'])
        self.write('evidence.md', '# 未交接\n'); self.commit('local change')
        snap = self.resume(TASK); self.assertEqual(snap['resume']['status'], 'unavailable')
        self.assertIsNone(snap['next'][0]['handoff_next']); self.assertEqual(snap['conclusion'], 'NOT_CHECKED')

    def test_S12_v2_closed_shapes(self):
        self.mr(); record = dict(version=2, mode='mr', content_commit=self.base, **self.q['handoff'])
        variants = []
        for key, value in (('version', True), ('version', 3), ('after_merge', None)):
            bad = copy.deepcopy(record); bad[key] = value; variants.append(bad)
        bad = copy.deepcopy(record); bad['after_merge'].pop('basis_ref'); variants.append(bad)
        bad = copy.deepcopy(record); bad['after_merge']['next']['authority_ref'] = 'evidence.md:2'; variants.append(bad)
        bad = copy.deepcopy(record); bad['mode'] = 'pause'; variants.append(bad)
        bad = copy.deepcopy(record); bad['version'] = 1; variants.append(bad)
        for bad in variants:
            with self.subTest(bad=bad), self.assertRaises(data.Invalid): data.handoff(bad)
        data.handoff(record)

    def test_S2_pause_idempotent_and_mr_conversion(self):
        first = self.seal(); second = self.seal()
        self.assertEqual(first, second)
        self.mr(); third = self.seal()
        self.assertEqual(third['content_commit'], first['handoff_commit'])
        self.assertNotEqual(third['handoff_commit'], first['handoff_commit'])
        self.assertEqual(self.git('show', first['handoff_commit'] + ':' + PROGRESS).count(' · handoff · '), 1)

    def test_S4_latest_context_not_birth_branch(self):
        self.assertEqual(self.seal()['context']['source_branch'], 'work')
        snap = self.resume(); self.assertEqual(snap['resume']['status'], 'ready')
        self.assertEqual(snap['in_progress'][0]['branch'], 'work')

    def test_S4_next_context_without_handoff(self):
        self.seal(); self.git('branch', '-m', 'work2'); self.ctx['source_branch'] = 'work2'
        self.append('context', self.ctx); self.commit('new context')
        self.assertEqual(self.resume(TASK)['resume']['status'], 'unavailable')
        self.assertIsNone(self.resume(TASK)['resume']['next'])
        self.assertEqual(self.seal()['context']['source_branch'], 'work2')

    def test_S5_main_deleted_source(self):
        proof = self.seal(); self.merge()
        before = flow.working_fingerprints(self.repo)
        r = self.resume()['resume']
        self.assertEqual((r['status'], r['location'], r['handoff_commit']), ('ready', 'main', proof['handoff_commit']))
        self.assertEqual(before, flow.working_fingerprints(self.repo))
        self.assertEqual(flow.check_cleanup(self.repo, TASK, proof['handoff_commit']), proof)

    def test_S15_normal_merge(self):
        self.seal(); self.merge(no_ff=True)
        self.assertEqual(self.resume()['resume']['status'], 'ready')

    def test_S15_squash_not_remapped(self):
        self.seal(); self.git('checkout', 'main'); self.git('merge', '--squash', 'work'); self.git('commit', '-m', 'squash')
        self.assertEqual(self.resume(TASK)['resume']['status'], 'unavailable')

    def test_S7_other_task_changes_allowed(self):
        self.seal(); self.merge(); self.write('other.txt', 'unrelated\n'); self.commit('other task')
        self.assertEqual(self.resume()['resume']['status'], 'ready')

    def test_S7_current_entry_change_refused(self):
        self.seal(); self.merge(); self.write('evidence.md', '# changed\n'); self.commit('unhanded change')
        r = self.resume()['resume']; self.assertEqual(r['status'], 'unavailable'); self.assertIsNone(r['next'])

    def test_S7_close_only_recomputes_terminal(self):
        self.seal(); self.merge(); self.append('answer', 'repo:OD-01 · Owner 原话「完成」'); self.commit('close')
        snap = self.resume(); self.assertEqual(snap['resume']['status'], 'ready'); self.assertEqual(snap['in_progress'], [])
        self.assertEqual(snap['landed'][0]['summary']['remaining'], ['实际新会话待验'])

    def test_S3_terminal_can_handoff(self):
        self.append('answer', 'repo:OD-01 · Owner 原话「完成」'); self.commit('done')
        self.seal(); self.assertEqual(self.resume()['resume']['status'], 'ready')

    def test_S3_full_milestone_needs_done(self):
        task = 'gov-t99'; self.q['task'] = task
        self.write(f'HANDOFF/progress/{task}.md', f'# task: {task}\n- 类别: 里程碑任务 · 名单项 {task} · 分支意图 work\n')
        self.append('context', self.ctx, f'HANDOFF/progress/{task}.md')
        self.write(f'tasks/{task}/{task}.md', '# Task\n## Acceptance Criteria\n- complete\n'); self.commit('definition')
        self.mr(); self.q['conditions'][0]['requirement_ref'] = f'tasks/{task}/{task}.md'
        with self.assertRaisesRegex(flow.Stop, 'done'):
            self.seal()
        self.write(f'tasks/{task}/rulings/RU-02-done.md', '# Ruling\n> Type: done\n'); self.commit('ruling')
        self.seal()

    def test_S8_wrong_parent_and_extra_path(self):
        c = self.git('rev-parse', 'HEAD')
        self.append('handoff', dict(version=2, mode='pause', content_commit=c, **self.q['handoff']))
        self.write('extra.txt', 'x'); self.commit('invalid H')
        with self.assertRaises(status.Unavailable):
            status.validate_handoff(self.repo, self.repo.task_at('HEAD', TASK))

    def test_S8_duplicate_handoff(self):
        proof = self.seal(); self.append('handoff', proof['handoff']); self.commit('duplicate')
        self.assertEqual(self.resume(TASK)['resume']['status'], 'unavailable')

    def test_S8_context_must_be_in_C(self):
        c = self.base
        self.append('handoff', dict(version=2, mode='pause', content_commit=c, **self.q['handoff'])); self.commit('invalid parent')
        self.assertEqual(self.resume(TASK)['resume']['status'], 'unavailable')

    def test_S8_missing_evidence(self):
        self.q['handoff']['evidence'][0]['path'] = 'absent.md'
        before = self.git('rev-parse', 'HEAD')
        with self.assertRaises(status.Unavailable):self.seal()
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)

    def test_S9_dirty_unknown_and_foreign_index(self):
        self.write('unknown.md', 'x'); self.git('add', '--', 'unknown.md')
        with self.assertRaisesRegex(flow.Stop, '未声明'):self.seal()
        self.assertTrue((self.root/'unknown.md').exists())

    def test_S2_declared_content_before_H(self):
        self.write('change.md', 'new\n'); self.q['paths'] = ['change.md']
        self.q['handoff']['entries'].append(dict(path='change.md', role='current'))
        proof = self.seal(); self.assertEqual(self.repo.file(proof['content_commit'], 'change.md'), b'new\n')
        self.assertEqual(self.repo.changed(proof['content_commit'], proof['handoff_commit']), {PROGRESS})

    def test_S12_separator_inside_json(self):
        self.q['handoff']['summary']['completed'] = ['one · two']
        self.assertEqual(self.seal()['handoff']['summary']['completed'], ['one · two'])

    def test_S12_data_rejections(self):
        cases = [('version', True), ('version', 3), ('source_branch', '../bad'), ('target_branch', 'other'), ('extra', 'x')]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                c = dict(self.ctx); c[key] = value
                with self.assertRaises(data.Invalid):data.context(c)
        for path in ('../outside', '/absolute', 'a//b', 'a/../b', '.git/config', 'tasks/a/attempts/x', '.env', 'a\\b'):
            with self.subTest(path=path), self.assertRaises(data.Invalid):data.path(path)
        with self.assertRaises(data.Invalid):data.loads('{"x":1,"x":2}')
        with self.assertRaises(data.Invalid):data.text('line\nline')
        with self.assertRaises(data.Invalid):data.loads('{"x":NaN}')

    def test_S12_cross_task_and_symlink(self):
        self.q['paths'] = ['HANDOFF/progress/other.md']
        with self.assertRaises(data.Invalid):self.seal()
        self.q['paths'] = ['escape']; (self.root/'escape').symlink_to('/etc/passwd')
        with self.assertRaises(status.Unavailable):self.seal()

    def test_S13_unknown_version_not_checked(self):
        self.ctx['version'] = 2; self.append('context', self.ctx)
        tasks, errors = lint.load_progress(str(self.root))
        self.assertIn('not-checked', [e['severity'] for e in errors])
        self.assertEqual(status.compute(str(self.root))['conclusion'], 'NOT_CHECKED')

    def test_S13_other_task_failure_not_this_task(self):
        self.seal(); self.write('HANDOFF/progress/other.md', '# bad\n'); self.commit('bad other')
        self.assertEqual(self.resume(TASK)['conclusion'], 'PASS')
        self.assertEqual(status.compute(str(self.root))['conclusion'], 'NOT_CHECKED')

    def test_S14_unique_ignored_material_blocks_cleanup(self):
        h = self.seal()['handoff_commit']
        # Keep the source checked out after advancing main to the merged H.
        self.git('update-ref', 'refs/heads/main', h)
        self.write('ignored-artifact', 'only copy')
        with self.assertRaisesRegex(flow.Stop, 'tracked/untracked/ignored'):
            flow.check_cleanup(self.repo, TASK, h)
        self.assertEqual((self.root/'ignored-artifact').read_text(), 'only copy')

    def test_S14_retained_main_ignored_material_is_preserved(self):
        proof = self.seal(); self.merge(); self.write('ignored-artifact', 'retained history')
        before = flow.working_fingerprints(self.repo)
        self.assertEqual(flow.check_cleanup(self.repo, TASK, proof['handoff_commit']), proof)
        self.assertEqual(before, flow.working_fingerprints(self.repo))

    def test_S14_retained_main_tracked_and_untracked_changes_block(self):
        h = self.seal()['handoff_commit']; self.merge()
        for path, value in [('untracked-artifact', 'only copy'), ('.gitignore', 'changed rules')]:
            with self.subTest(path=path):
                self.write(path, value)
                with self.assertRaisesRegex(flow.Stop, 'tracked/untracked'):
                    flow.check_cleanup(self.repo, TASK, h)
                self.assertEqual((self.root/path).read_text(), value)
                if path == 'untracked-artifact':
                    (self.root/path).unlink()

    def test_S14_source_untracked_material_blocks(self):
        h = self.seal()['handoff_commit']; self.git('update-ref', 'refs/heads/main', h)
        self.write('untracked-artifact', 'only copy')
        with self.assertRaisesRegex(flow.Stop, 'tracked/untracked/ignored'):
            flow.check_cleanup(self.repo, TASK, h)
        self.assertEqual((self.root/'untracked-artifact').read_text(), 'only copy')

    def test_S14_not_landed_blocks_cleanup(self):
        h = self.seal()['handoff_commit']
        with self.assertRaises(flow.Stop):flow.check_cleanup(self.repo, TASK, h)

    def test_S11_generator_scoped_and_overreach(self):
        self.write('build.py', 'from pathlib import Path\nPath("generated.md").write_text("generated\\n")\n')
        self.write('generated.md', 'old\n'); self.commit('generator')
        command = [sys.executable, '-B', 'build.py']
        self.q['handoff']['entries'] += [dict(path='build.py', role='current'), dict(path='generated.md', role='generated', sources=['build.py'], generator=command)]
        self.q['paths'] = ['generated.md']; self.q['generators'] = [command]
        self.seal(); self.assertEqual((self.root/'generated.md').read_text(), 'generated\n')
        self.write('build.py', 'from pathlib import Path\nPath("outside.md").write_text("unexpected")\n'); self.commit('changed generator')
        with self.assertRaisesRegex(flow.Stop, '越界'):self.seal()
        self.assertTrue((self.root/'outside.md').exists())

    def test_S11_history_bytes_preserved(self):
        self.q['handoff']['entries'][0]['role'] = 'history'
        self.write('evidence.md', 'changed'); self.q['paths'] = ['evidence.md']
        with self.assertRaisesRegex(flow.Stop, '历史'):self.seal()

    def test_S6_same_merge_multiple_candidates(self):
        first = self.seal()
        self.write('HANDOFF/progress/gov-t99.md', '# task: gov-t99\n- 类别: 里程碑任务 · 名单项 gov-t99 · 分支意图 work\n')
        self.append('context', self.ctx, 'HANDOFF/progress/gov-t99.md'); self.commit('second task')
        self.q['task'] = 'gov-t99'; self.seal(); self.merge(no_ff=True)
        r = self.resume()['resume']; self.assertEqual(r['status'], 'ambiguous'); self.assertEqual(set(r['candidates']), {TASK, 'gov-t99'})
        self.assertEqual(self.resume(TASK)['resume']['status'], 'ready')
        snap = self.resume(); self.assertTrue(all(n['handoff_next'] is None for n in snap['next'] if n['task'] in snap['resume']['candidates']))

    def test_S15_detached_and_shallow_refused(self):
        self.seal(); self.git('checkout', '--detach')
        self.assertEqual(self.resume(TASK)['resume']['status'], 'unavailable')
        self.git('checkout', 'work')
        real = self.repo.need
        with patch.object(self.repo, 'need', side_effect=lambda *args: 'true' if args == ('rev-parse', '--is-shallow-repository') else real(*args)):
            tasks, errors = self.repo.tree_tasks('HEAD'); self.assertIn('浅历史', status.resume_result(self.repo, tasks, errors, TASK)['reasons'][0])

    def test_S5_other_worktree_not_read_or_taken(self):
        self.seal(); self.git('checkout', '-b', 'other')
        with patch.object(status.Repository, 'worktrees', return_value={'work': '/durable/other-owner', 'other': str(self.root)}):
            r = self.resume(TASK)['resume']
        self.assertEqual(r['location'], 'other-worktree')
        self.assertIn('/durable/other-owner', r['reasons'][0])
        self.assertEqual(r['status'], 'unavailable')

    def test_S13_invalid_newest_handoff_does_not_select_old(self):
        self.seal(); self.merge()
        invalid = dict(version=3, mode='pause', content_commit=self.base, **self.q['handoff'])
        self.append('handoff', invalid); self.commit('unknown newer record')
        r = self.resume()['resume']
        self.assertEqual(r['status'], 'unavailable')
        self.assertIn('version', str(r['reasons']))

    def test_S8_terminal_invalid_proof_fails_global_view(self):
        self.append('answer', 'repo:OD-01 · Owner 原话「完成」')
        self.append('handoff', dict(version=2, mode='pause', content_commit=self.base, **self.q['handoff']))
        self.commit('invalid terminal handoff')
        self.assertEqual(status.compute(str(self.root))['conclusion'], 'NOT_CHECKED')

    def test_S13_cli_exit_codes(self):
        script = str(Path(flow.__file__).resolve())
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as request:
            json.dump(self.q, request); request.flush()
            p = subprocess.run([sys.executable, '-B', script, 'prepare', '--root', str(self.root), '--request', request.name, '--json'], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
            self.assertEqual(json.loads(p.stdout)['status'], 'completed')
            self.write('unknown', 'x')
            p = subprocess.run([sys.executable, '-B', script, 'prepare', '--root', str(self.root), '--request', request.name], capture_output=True, text=True)
            self.assertEqual(p.returncode, 1); self.assertEqual(json.loads(p.stdout)['reason'], 'scope-mismatch')
        p = subprocess.run([sys.executable, '-B', script, 'prepare', '--root', str(self.root), '--request', '/absent/input.json'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2); self.assertEqual(json.loads(p.stdout)['status'], 'not-checked')

    def test_S10_prepared_then_HEAD_changes_reprepares(self):
        first = self.seal(); self.write('more.md', 'next'); self.commit('more')
        self.assertEqual(self.resume(TASK)['resume']['status'], 'ready')
        second = self.seal(); self.assertNotEqual(first['handoff_commit'], second['handoff_commit'])

    def test_S11_generator_requires_exact_approved_argv(self):
        self.q['generators'] = [[sys.executable, '-c', 'print(1)']]
        with self.assertRaises(flow.Stop):self.seal()

    def test_S9_frozen_bytes_require_real_freeze(self):
        import hashlib
        p = 'mechanisms/sample/design.md'
        self.write(p, 'frozen')
        record = dict(revision=1, event='freeze', objects=[dict(path=p, bytes=6, sha256=hashlib.sha256(b'frozen').hexdigest())])
        self.write('records/governance/sample/freeze-records.jsonl', json.dumps(record) + '\n')
        base = self.commit('freeze')
        self.write(p, 'changed without authority'); self.commit('bad change')
        self.mr(); proof = self.seal()
        self.q['mr']['declarations'] = [dict(path=p, instruction='test', authority_ref='evidence.md', classification='语义级')]
        with self.assertRaisesRegex(flow.Stop, '冻结字节'):flow.describe(self.repo, self.q, proof, base)
        self.git('rm', '--', p); self.git('commit', '-m', 'bad deletion'); proof = self.seal()
        with self.assertRaisesRegex(flow.Stop, '冻结字节'):flow.describe(self.repo, self.q, proof, base)

    def test_CL52_second_batch_retains_legacy_lock_classification(self):
        from history_read_selftest import Fixture as HistoryFixture
        locked = 'mechanisms/sample/historical-object.md'
        lockfile = 'records/lock-declarations.jsonl'
        self.write(locked, 'before')
        self.write(lockfile, json.dumps(dict(kind='lock', path=locked))+'\n')
        self.commit('old lock')
        fixture = HistoryFixture(self.root)
        fixture.declare([lockfile])
        target_base = self.git('rev-parse', 'HEAD')
        self.write(locked, 'after'); self.commit('second batch change')
        self.mr(); self.q['mr']['declarations'] = [dict(path=locked, instruction='fixture implementation', authority_ref='evidence.md#授权', classification='语义级')]
        proof = self.seal()
        description = flow.describe(self.repo, self.q, proof, target_base)
        self.assertIn('历史活跃 lock', description)
        self.assertIn(locked, description)
        self.assertEqual(flow.identity(self.repo, target_base, locked)['sha256'], __import__('hashlib').sha256(b'before').hexdigest())
        self.assertEqual(flow.identity(self.repo, proof['handoff_commit'], locked)['sha256'], __import__('hashlib').sha256(b'after').hexdigest())
        self.assertNotIn(lockfile, self.repo.files(target_base))

    def test_S9_rewritten_freeze_history_rejected(self):
        p = 'records/governance/sample/freeze-records.jsonl'
        self.write(p, json.dumps(dict(revision=1, event='freeze', objects=[])) + '\n'); base = self.commit('old row')
        self.write(p, json.dumps(dict(revision=2, event='freeze', objects=[])) + '\n'); self.commit('rewrite')
        self.mr(); proof = self.seal()
        with self.assertRaisesRegex(flow.Stop, '历史冻结行'):flow.describe(self.repo, self.q, proof, base)

    def test_S9_multiple_freezes_in_same_MR_use_each_commit(self):
        import hashlib
        p = 'mechanisms/sample/design.md'; rec = 'records/governance/sample/freeze-records.jsonl'
        for revision, content in [(1, 'first'), (2, 'second')]:
            self.write(p, content)
            row = dict(revision=revision, event='freeze' if revision == 1 else 're-freeze', objects=[dict(path=p, bytes=len(content), sha256=hashlib.sha256(content.encode()).hexdigest())])
            (self.root/rec).parent.mkdir(parents=True, exist_ok=True)
            with (self.root/rec).open('a') as f:f.write(json.dumps(row) + '\n')
            self.commit('freeze ' + str(revision))
        self.mr(); self.q['mr']['declarations'] = [dict(path=x, instruction='test', authority_ref='evidence.md', classification='语义级') for x in (p, rec)]
        proof = self.seal(); description = flow.describe(self.repo, self.q, proof, self.base)
        self.assertIn('revision', description); self.assertIn(rec + ':2', description)

    def fake_publish(self, existing=None, create_error=False, target_change=False):
        fixture = self; calls = []
        class Fake:
            def __init__(self, repo):calls.append('adapter')
            def inspect_repository(self): return {'provider': 'gitlab'}
            def find_change_requests(self, source, target):calls.append('GET'); return existing or []
            def read_change_request(self, iid):calls.append('readback'); return existing[0]
            def create_change_request(self, ctx, h, mr, description, target_sha):
                calls.append('POST')
                fixture.assertIn(h, description); fixture.assertEqual(fixture.git('rev-parse', 'HEAD'), h)
                fixture.assertEqual(fixture.repo.task_at(h, TASK)['events'][-1]['type'], 'handoff')
                if create_error:raise flow.Stop('external-unknown', 'simulated unknown create', 'external-unknown')
                return dict(iid=1, web_url='https://example.invalid/mr/1', source_branch='work', target_branch='main', sha=h, state='opened')
        count = [0]
        def refs(repo, ctx):
            count[0] += 1
            target = fixture.base if not target_change or count[0] == 1 else 'f'*40
            return {'main': target, 'work': fixture.git('rev-parse', 'HEAD')}
        return Fake, refs, calls

    def test_S1_publish_contains_prepare_no_extra_handoff(self):
        self.mr(); fake, refs, calls = self.fake_publish()
        with patch.object(flow, 'remote_refs', side_effect=refs):
            proof, mr, reason = flow.publish(self.repo, self.q, fake)
        self.assertEqual(calls, ['adapter', 'GET', 'POST']); self.assertEqual(mr['sha'], proof['handoff_commit'])

    def test_S1_real_local_bare_push_before_create(self):
        with tempfile.TemporaryDirectory(prefix='handoff-bare-') as remote:
            subprocess.run(['git', 'init', '--bare', remote], check=True, capture_output=True)
            self.git('remote', 'add', 'origin', remote)
            self.git('push', 'origin', 'main')
            # A pre-pushed content commit may be fast-forwarded by this authorized MR action.
            self.git('push', 'origin', 'work')
            self.mr(); fake, refs, calls = self.fake_publish()
            proof, mr, reason = flow.publish(self.repo, self.q, fake)
            actual = self.git('ls-remote', '--heads', 'origin', 'refs/heads/work').split()[0]
            self.assertEqual(actual, proof['handoff_commit']); self.assertEqual(calls.count('POST'), 1)


    def test_S1_unmet_no_external_calls(self):
        self.mr(); self.q['conditions'][0]['result'] = 'unmet'; fake, refs, calls = self.fake_publish()
        with patch.object(flow, 'remote_refs', side_effect=refs), self.assertRaises(flow.Stop):flow.publish(self.repo, self.q, fake)
        self.assertEqual(calls, [])

    def test_S9_changed_target_no_POST(self):
        self.mr(); fake, refs, calls = self.fake_publish(target_change=True)
        with patch.object(flow, 'remote_refs', side_effect=refs), self.assertRaises(flow.Stop):flow.publish(self.repo, self.q, fake)
        self.assertNotIn('POST', calls)

    def test_S10_unknown_create_then_GET_existing(self):
        self.mr(); fake, refs, calls = self.fake_publish(create_error=True)
        with patch.object(flow, 'remote_refs', side_effect=refs), self.assertRaisesRegex(flow.Stop, '不确定'):flow.publish(self.repo, self.q, fake)
        self.assertEqual(calls.count('POST'), 1)
        h = self.git('rev-parse', 'HEAD'); obj = dict(iid=1, web_url='https://example.invalid/1', source_branch='work', target_branch='main', sha=h, state='opened')
        fake, refs, calls = self.fake_publish([obj])
        with patch.object(flow, 'remote_refs', side_effect=refs):flow.publish(self.repo, self.q, fake)
        self.assertEqual(calls, ['adapter', 'GET', 'readback'])

    def test_S10_closed_or_wrong_SHA_no_POST(self):
        self.mr(); h = self.seal()['handoff_commit']
        for state, sha in [('closed', h), ('opened', self.base)]:
            fake, refs, calls = self.fake_publish([dict(iid=1, web_url='x', source_branch='work', target_branch='main', sha=sha, state=state)])
            with patch.object(flow, 'remote_refs', side_effect=refs), self.assertRaises(flow.Stop):flow.publish(self.repo, self.q, fake)
            self.assertNotIn('POST', calls)

    def test_S9_no_new_difference_no_empty_MR(self):
        self.mr(); h = self.seal()['handoff_commit']; self.git('update-ref', 'refs/heads/main', h)
        fake, refs, calls = self.fake_publish()
        with patch.object(flow, 'remote_refs', return_value={'main': h, 'work': h}):
            proof, mr, reason = flow.publish(self.repo, self.q, fake)
        self.assertIsNone(mr); self.assertEqual(reason, 'already-landed'); self.assertNotIn('POST', calls)

    def test_S9_required_declaration_missing(self):
        self.write('decisions/D-01-test.md', '# Test\n'); self.commit('decision')
        self.mr(); fake, refs, calls = self.fake_publish()
        with patch.object(flow, 'remote_refs', side_effect=refs), self.assertRaisesRegex(flow.Stop, '申报'):flow.publish(self.repo, self.q, fake)
        self.assertNotIn('POST', calls)
        self.q['mr']['declarations'] = [dict(path='decisions/D-01-test.md', instruction='test authorization', authority_ref='evidence.md', classification='语义级')]
        with patch.object(flow, 'remote_refs', side_effect=refs):flow.publish(self.repo, self.q, fake)
        self.assertEqual(calls.count('POST'), 1)

    def test_S10_GET_failure_no_POST(self):
        self.mr(); fake, refs, calls = self.fake_publish()
        def failed(*args):
            calls.append('GET-failed')
            raise flow.Stop('tool-unavailable', 'GET failed', 'not-checked')
        with patch.object(fake, 'find_change_requests', failed), patch.object(flow, 'remote_refs', side_effect=refs), self.assertRaises(flow.Stop):
            flow.publish(self.repo, self.q, fake)
        self.assertNotIn('POST', calls)

    def test_S10_multiple_MRs_no_POST(self):
        self.mr(); fake, refs, calls = self.fake_publish([{'iid': 1}, {'iid': 2}])
        with patch.object(flow, 'remote_refs', side_effect=refs), self.assertRaises(flow.Stop):flow.publish(self.repo, self.q, fake)
        self.assertNotIn('POST', calls)

    def test_S13_readonly_without_python_B(self):
        self.seal()
        with tempfile.TemporaryDirectory(prefix='handoff-reader-copy-') as tool_dir:
            import shutil
            tool_root = Path(tool_dir)/'handoff-protocol'; tool_root.mkdir()
            shared = Path(tool_dir)/'repo-layout'; shared.mkdir()
            shutil.copyfile(Path(flow.__file__).resolve().parents[1]/'repo-layout/history_read.py', shared/'history_read.py')
            for name in ('handoff_data.py', 'handoff_lint.py', 'handoff_status.py'):
                shutil.copyfile(Path(flow.__file__).with_name(name), tool_root/name)
            p = subprocess.run([sys.executable, str(tool_root/'handoff_status.py'), '--root', str(self.root), '--resume', '--json'], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
            self.assertFalse(list(Path(tool_dir).rglob('__pycache__')))


    def test_S12_config_errors_redacted(self):
        with patch.dict(os.environ, {'GL_HOST': 'https://private.invalid', 'GL_CSTHINK_HARNESS_PLANE_PROJECT': 'secret/project', 'GL_CSTHINK_HARNESS_PLANE_TOKEN': 'token/value'}):
            result = flow.redact_local('https://private.invalid secret/project secret%2Fproject token/value token%2Fvalue')
        self.assertNotIn('private', result); self.assertNotIn('secret', result); self.assertNotIn('token', result)


    def test_S13_missing_adapter_reports_not_checked(self):
        with patch.dict(os.environ, {'HANDOFF_GITLAB_MR_SCRIPT': ''}), self.assertRaises(flow.Stop) as caught:
            flow.Adapter(self.repo)
        self.assertEqual(caught.exception.status, 'not-checked')


if __name__ == '__main__':
    unittest.main(verbosity=2)
