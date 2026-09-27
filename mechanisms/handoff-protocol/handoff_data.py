"""CL-53 JSON value validation; no Git, network or state writes."""
import json
import re
import subprocess


class Invalid(ValueError):
    pass


class Unsupported(Invalid):
    pass


def require(ok, message):
    if not ok:
        raise Invalid(message)


def obj(value, keys):
    require(type(value) is dict and set(value) == set(keys.split()),
            '对象字段必须恰为 ' + keys)
    return value


def text(value):
    require(isinstance(value, str) and bool(value.strip()) and
            all(ord(c) >= 32 and ord(c) != 127 for c in value), '需要非空、无控制字符的字符串')
    return value


def array(value, validate, nonempty=False):
    require(type(value) is list and (value or not nonempty), '需要数组' + ('且非空' if nonempty else ''))
    for v in value:
        validate(v)
    return value


def unique(value):
    keys = [json.dumps(v, sort_keys=True, ensure_ascii=False) for v in value]
    require(len(keys) == len(set(keys)), '数组不允许重复成员')


def sha(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{40}', value), '需要完整小写 40 位 SHA')
    return value


def path(value):
    text(value)
    bits = value.split('/')
    require(not value.startswith('/') and '\\' not in value and
            all(b not in ('', '.', '..', '.git', 'attempts', 'review-attempts') for b in bits),
            '需要仓内文件路径，禁止 Git 元数据与本地暂存')
    require(not any(b.lower() in ('credentials', 'credentials.json', 'id_rsa', 'id_ed25519') or
                    b.lower().startswith('.env') or b.lower().endswith(('.pem', '.key')) for b in bits),
            '路径不能指向凭据')
    return value


def branch(value):
    text(value)
    require(not value.startswith(('refs/', '-', '@{-')) and value != 'HEAD', '需要短分支名')
    try:
        p = subprocess.run(['git', 'check-ref-format', '--branch', value], capture_output=True)
    except OSError as e:
        raise Unsupported('git 不可用') from e
    require(p.returncode == 0, '非法 Git 分支名')


def version(value, supported=(1,)):
    require(type(value) is int, 'version 必须是整数，不能是布尔')
    if value not in supported:
        raise Unsupported('未知 version: ' + str(value))


def context(value):
    obj(value, 'version source_branch target_branch base_commit authority_ref')
    version(value['version'])
    branch(value['source_branch']); branch(value['target_branch'])
    require(value['target_branch'] == 'main' and value['source_branch'] != 'main', 'target 必须为 main，且不同于 source')
    sha(value['base_commit']); text(value['authority_ref'])


def next_step(value):
    obj(value, 'kind text authority_ref')
    k = value['kind']
    require(k in ('wait-owner', 'continue-authorized', 'none'), '未知 next.kind')
    if k == 'none':
        require(value['text'] is None and value['authority_ref'] is None, 'none 不带下一步')
    else:
        text(value['text'])
        if k == 'wait-owner':
            require(value['authority_ref'] is None, '待授权动作不能自带授权')
        else:
            text(value['authority_ref'])


def evidence(value):
    obj(value, 'commit path locator')
    sha(value['commit']); path(value['path']); text(value['locator'])


def argv(value):
    array(value, text, True)


def entry(value):
    require(type(value) is dict and value.get('role') in ('current', 'history', 'generated'), '未知 entry.role')
    obj(value, 'path role sources generator' if value['role'] == 'generated' else 'path role')
    path(value['path'])
    if value['role'] == 'generated':
        array(value['sources'], path, True); unique(value['sources']); argv(value['generator'])


def payload(value, event_version=1, mode=None):
    obj(value, 'summary evidence entries next' + (' after_merge' if event_version == 2 else ''))
    obj(value['summary'], 'completed remaining')
    for v in value['summary'].values():
        array(v, text)
    array(value['evidence'], evidence); unique(value['evidence'])
    array(value['entries'], entry)
    require(len({v['path'] for v in value['entries']}) == len(value['entries']), 'entries 路径重复')
    sources = {e['path'] for e in value['entries'] if e['role'] in ('current', 'history')}
    for e in value['entries']:
        if e['role'] == 'generated':
            require(set(e['sources']) <= sources, 'generated 源必须列为 current/history')
    next_step(value['next'])
    if event_version == 2:
        if mode == 'pause':
            require(value['after_merge'] is None, 'pause 的 after_merge 必须为 null')
        else:
            obj(value['after_merge'], 'next basis_ref')
            next_step(value['after_merge']['next']); text(value['after_merge']['basis_ref'])


def handoff(value):
    require(type(value) is dict and 'version' in value, 'handoff 需要 version')
    version(value['version'], (1, 2))
    obj(value, 'version mode content_commit summary evidence entries next' +
        (' after_merge' if value['version'] == 2 else ''))
    sha(value['content_commit'])
    require(value['mode'] in ('pause', 'mr'), 'mode 必须为 pause/mr')
    payload({k: v for k, v in value.items() if k not in ('version', 'mode', 'content_commit')},
            value['version'], value['mode'])
    require(value['mode'] != 'mr' or value['evidence'], 'mr 必须有证据')


def declaration(value):
    # Human inputs only. Identity, change kind, state and commands are derived from Git.
    require(type(value) is dict, 'declaration 必须为对象')
    keys = 'path instruction authority_ref classification'
    if value.get('classification') == '对齐级':
        keys += ' before_after semantic_statement'
    obj(value, keys); path(value['path']); text(value['instruction']); text(value['authority_ref'])
    require(value['classification'] in ('语义级', '对齐级'), '分级必须为语义级/对齐级')
    if value['classification'] == '对齐级':
        array(value['before_after'], lambda x: (obj(x, 'before after'), text(x['before']), text(x['after'])), True)
        require(value['semantic_statement'] == '语义零变化', '对齐级需声明语义零变化')


def request(value):
    obj(value, 'schema task mode paths authority_refs conditions handoff generators mr')
    if value['schema'] != 'handoff-workflow-request/v2':
        raise Unsupported('需要 handoff-workflow-request/v2；请迁移输入并按 mode 补齐 after_merge')
    require(isinstance(value['task'], str) and re.fullmatch('[a-z0-9][a-z0-9-]*', value['task']), '非法 task id')
    require(value['mode'] in ('pause', 'mr'), '未知 mode')
    array(value['paths'], path); unique(value['paths'])
    for p in value['paths']:
        require(not p.startswith('HANDOFF/progress/') or p == f"HANDOFF/progress/{value['task']}.md", '不允许写他任务进度')
    array(value['authority_refs'], text, True); unique(value['authority_refs'])
    array(value['conditions'], lambda c: (obj(c, 'requirement_ref evidence_ref result'),
          text(c['requirement_ref']), text(c['evidence_ref']),
          require(c['result'] in ('met', 'unmet', 'not-checked'), '未知条件结果')))
    require(len({c['requirement_ref'] for c in value['conditions']}) == len(value['conditions']), '条件要求重复')
    payload(value['handoff'], 2, value['mode']); array(value['generators'], argv); unique(value['generators'])
    if value['mode'] == 'pause':
        require(value['mr'] is None, 'pause 不带 MR')
    else:
        require(bool(value['conditions']), 'mr 必须列本批条件')
        obj(value['mr'], 'title summary declarations'); text(value['mr']['title']); text(value['mr']['summary'])
        array(value['mr']['declarations'], declaration)
        require(len({d['path'] for d in value['mr']['declarations']}) == len(value['mr']['declarations']), '申报路径重复')
        require(bool(value['handoff']['evidence']), 'mr 必须有证据')


def loads(raw):
    def pairs(items):
        d = {}
        for k, v in items:
            require(k not in d, '重复 JSON 键: ' + k)
            d[k] = v
        return d
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(Invalid('非法 JSON 数值')))
    except (ValueError, TypeError) as e:
        if isinstance(e, Invalid):
            raise
        raise Invalid('非法 JSON: ' + str(e)) from e
