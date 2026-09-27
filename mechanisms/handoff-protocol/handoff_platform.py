"""CL-56 GitHub adapter. Connection configuration never grants action authority."""
import base64
import json
import os
from pathlib import Path
import re
import shutil
import sys
import subprocess
from urllib.parse import quote, urlencode, urlsplit

import handoff_data as data


class PlatformError(RuntimeError):
    def __init__(self, reason, message, status='blocked'):
        super().__init__(message)
        self.reason, self.status = reason, status


def require(ok, reason, message, status='blocked'):
    if not ok:
        raise PlatformError(reason, message, status)


def git_address(value):
    """Compare transport addresses without printing credential-bearing inputs."""
    if '://' in value:
        u = urlsplit(value)
        require(u.scheme in ('https', 'ssh') and not u.password and
                (u.username is None or u.scheme == 'ssh' and u.username == 'git') and
                not u.query and not u.fragment and u.port in (None, 22, 443),
                'remote-mismatch', '不支持的 Git 地址或含凭据地址')
        host, path = u.hostname, u.path.lstrip('/')
    else:
        m = re.fullmatch(r'git@([A-Za-z0-9.-]+):([^\s]+)', value)
        require(m is not None, 'remote-mismatch', '不是可验证的 Git 地址')
        host, path = m.groups()
    return host, path.removesuffix('.git')


def load_config(repo, allow_gitlab=False):
    filename = os.environ.get('HANDOFF_PLATFORM_CONFIG')
    require(bool(filename), 'input-invalid', 'GitHub 需要 HANDOFF_PLATFORM_CONFIG')
    path = Path(filename).resolve()
    require(not path.is_relative_to(Path(repo.root).resolve()), 'input-invalid', '平台配置须位于仓外')
    try:
        c = data.loads(path.read_text())
        data.obj(c, 'schema provider host repository repository_id target_branch deployment deployment_ref')
        require(c['schema'] == 'handoff-platform-config/v1' and c['provider'] == 'github' and
                c['host'] == 'https://github.com' and c['target_branch'] == 'main',
                'input-invalid', '未知平台配置或目标')
        require(isinstance(c['repository'], str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', c['repository']) and
                isinstance(c['repository_id'], str) and re.fullmatch(r'[1-9][0-9]*', c['repository_id']),
                'input-invalid', '仓库身份格式错误')
        require(c['deployment'] in ('protected', 'private-free'), 'input-invalid', '未知部署类型')
        data.text(c['deployment_ref'])
    except (OSError, data.Invalid) as exc:
        raise PlatformError('input-invalid', '平台配置不可读或字段错误', 'not-checked') from exc
    require(allow_gitlab or not os.environ.get('HANDOFF_GITLAB_MR_SCRIPT'), 'input-invalid', 'GitHub 与 GitLab 发布配置冲突')
    return c


class ApiError(PlatformError):
    def __init__(self, method, code=None, plan_required=False):
        self.code, self.plan_required = code, plan_required
        write = method != 'GET'
        super().__init__('external-unknown' if write else 'tool-unavailable',
                         'GitHub ' + method + ' 未查成' + (f' (HTTP {code})' if code else ''),
                         'external-unknown' if write else 'not-checked')


class GitHubAPI:
    def __init__(self, root):
        self.root = root
        configured = os.environ.get('HANDOFF_GITHUB_CLI')
        self.cli = configured or shutil.which('gh-axi')
        require(self.cli and Path(self.cli).is_absolute() and Path(self.cli).is_file() and os.access(self.cli, os.X_OK),
                'tool-unavailable', '可执行 gh-axi 不可用', 'not-checked')

    def __call__(self, method, endpoint, body=None):
        require(method in ('GET', 'POST') and endpoint.startswith('/repos/'),
                'input-invalid', '适配只允许所选仓库 GET 与 PR POST')
        require(method == 'GET' or re.fullmatch(r'/repos/[^/]+/[^/]+/pulls', endpoint),
                'input-invalid', '适配不允许此写入接口')
        args = [self.cli, 'api', method, endpoint, '--hostname', 'github.com', '--jq', '@base64', '--full']
        if body is not None:
            args += ['--input', '-']
        try:
            p = subprocess.run(args, input=None if body is None else json.dumps(body),
                               capture_output=True, text=True, cwd=self.root, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ApiError(method) from exc
        if p.returncode:
            # Classify only. Never propagate raw stdout/stderr, URL, headers or secrets.
            m = re.search(r'HTTP (403|404|409|422)\b', p.stderr + p.stdout)
            code = int(m[1]) if m else 403 if re.search(r'(?m)^code: FORBIDDEN\s*$', p.stderr + p.stdout) else None
            plan = code == 403 and ('Upgrade to GitHub Pro or make this repository public' in p.stderr + p.stdout or
                                   'Upgrade to GitHub Team or make this repository public' in p.stderr + p.stdout)
            raise ApiError(method, code, plan)
        # gh-axi preserves jq values but wraps non-JSON output in a TOON envelope.
        m = re.fullmatch(r'api_response:\n  body: "?([A-Za-z0-9+/=]+)"?\n  truncated: false\s*', p.stdout.strip())
        require(m is not None, 'tool-unavailable', 'gh-axi 返回非预期或截断格式', 'not-checked')
        try:
            return data.loads(base64.b64decode(m[1], validate=True).decode())
        except (ValueError, UnicodeError, data.Invalid) as exc:
            raise PlatformError('tool-unavailable', 'gh-axi JSON 解码失败', 'not-checked') from exc


    def protection_plan_required(self, endpoint):
        """Only recover the reason gh-axi discards, via its same underlying gh identity.

        The accepted CL-56 input owner-check.md documents this read-only limitation.
        No PR read/write uses this path; no alternate host, credential or permission.
        """
        require(re.fullmatch(r'/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/branches/main/protection', endpoint),
                'input-invalid', '原始错误核查仅允许已绑定目标 main 保护接口')
        cli = shutil.which('gh')
        require(cli, 'tool-unavailable', 'gh-axi 的底层 gh 不可用，保护原因无法核查', 'not-checked')
        try:
            result = subprocess.run([cli, 'api', endpoint, '--hostname', 'github.com', '--include'],
                                    capture_output=True, text=True, cwd=self.root, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return False
        raw = result.stdout.replace('\r\n', '\n')
        # HTTP status and exact known capability message must both survive. No stderr inference.
        headers, separator, body = raw.partition('\n\n')
        if not separator or not re.match(r'HTTP/\S+ 403\b', headers):
            return False
        try:
            value = data.loads(body)
        except data.Invalid:
            return False
        return value.get('message') in (
            'Upgrade to GitHub Pro or make this repository public to enable this feature.',
            'Upgrade to GitHub Team or make this repository public to enable this feature.')


def paged(api, endpoint, params=None):
    rows = []
    for page in range(1, 101):
        value = api('GET', endpoint + '?' + urlencode(dict(params or {}, per_page=100, page=page)))
        require(type(value) is list, 'tool-unavailable', '分页响应不是数组', 'not-checked')
        rows.extend(value)
        if len(value) < 100:
            return rows
    raise PlatformError('tool-unavailable', '分页未穷尽', 'not-checked')


class GitHubAdapter:
    provider = 'github'
    display_name = 'PR'

    def __init__(self, repo, config=None, api=None, bind_origin=True):
        self.repo, self.config = repo, config if config is not None else load_config(repo)
        self.api = api if api is not None else GitHubAPI(repo.root)
        self.endpoint = '/repos/' + self.config['repository']
        self.bind_origin = bind_origin

    def inspect_repository(self):
        c = self.config
        if self.bind_origin:
            expected = ('github.com', c['repository'])
            require(git_address(self.repo.need('remote', 'get-url', 'origin')) == expected,
                    'remote-mismatch', 'origin 与 GitHub 配置不一致')
            push_urls = self.repo.need('remote', 'get-url', '--push', '--all', 'origin').splitlines()
            require(len(push_urls) == 1 and git_address(push_urls[0]) == expected,
                    'remote-mismatch', 'origin push URL 与 GitHub 配置不一致')
        path = self.repo.locate('HEAD', c['deployment_ref'], strict=True)
        require(path.startswith(('records/governance/', 'decisions/', 'HANDOFF/progress/')),
                'conditions-unmet', 'deployment_ref 须定位当前正式决定')
        v = self.api('GET', self.endpoint)
        require(type(v) is dict and str(v.get('id')) == c['repository_id'] and v.get('full_name') == c['repository'],
                'remote-mismatch', 'GitHub API 仓库身份不符')
        require(v.get('archived') is False and v.get('disabled', False) is False and
                v.get('default_branch') == 'main' and v.get('permissions', {}).get('push') is True and
                v.get('allow_merge_commit') is True,
                'conditions-unmet', '仓库归档、默认分支、当前写权限或 merge commit 条件不满足')
        self.repository = v
        if c['deployment'] == 'private-free':
            require(v.get('private') is True, 'conditions-unmet', 'private-free 目标不是私有仓')
            try:
                self.api('GET', self.endpoint + '/branches/main/protection')
            except ApiError as exc:
                known = exc.plan_required
                if not known and exc.code == 403 and isinstance(self.api, GitHubAPI):
                    known = self.api.protection_plan_required(self.endpoint + '/branches/main/protection')
                require(known, 'conditions-unmet', '保护能力未核成；普通权限错误不构成免费部署依据', 'not-checked')
                self.deployment_evidence = '目标保护接口明确要求升级套餐；目标 private=true'
            else:
                raise PlatformError('conditions-unmet', '保护可读，须按实际部署重新核差配置')
        else:
            protection = self.api('GET', self.endpoint + '/branches/main/protection')
            require(type(protection) is dict and protection.get('enforce_admins', {}).get('enabled') is True and
                    bool(protection.get('required_pull_request_reviews')) and
                    not protection.get('allow_force_pushes', {}).get('enabled') and
                    not protection.get('allow_deletions', {}).get('enabled') and
                    not protection.get('required_linear_history', {}).get('enabled'),
                    'conditions-unmet', '主干保护或 merge commit 约束未核成')
            # A callable token with admin/custom bypass cannot claim server enforcement.
            require(v.get('permissions', {}).get('admin') is False and
                    v.get('role_name') == 'write' and
                    not any(protection['required_pull_request_reviews'].get('bypass_pull_request_allowances', {}).values()),
                    'conditions-unmet', '当前身份绕过权限未排除')
        # Archive repository ID is a domain identity, not the numeric hosting ID.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'review-channel'))
        import review_evidence as evidence
        try:
            if evidence.storage_mode(self.repo.root) == 'archive-v1':
                archive = evidence.Archive(self.repo.root)
                require(evidence.switch_record(self.repo.root)['repository_id'] == archive.repository_id,
                        'remote-mismatch', '归档与正式切换决定身份不符')
        except AttributeError as exc:
            raise PlatformError('tool-unavailable', '归档绑定校验接口不可用', 'not-checked') from exc
        except evidence.EvidenceError as exc:
            raise PlatformError('remote-mismatch', '归档绑定身份或库存不可核') from exc
        return dict(provider='github', host=c['host'], repository=c['repository'], repository_id=c['repository_id'])

    def normalize(self, raw):
        c = self.config
        require(type(raw) is dict and type(raw.get('number')) is int and raw['number'] > 0,
                'duplicate-mr', 'PR 身份不可核')
        for side in ('head', 'base'):
            r = raw.get(side, {}).get('repo') or {}
            require(str(r.get('id')) == c['repository_id'] and r.get('full_name') == c['repository'],
                    'duplicate-mr', 'PR 仓库身份不符或 fork 来源')
        require(raw.get('state') in ('open', 'closed') and type(raw.get('merged')) is bool,
                'tool-unavailable', 'PR 状态不可核', 'not-checked')
        require(raw.get('html_url') == c['host'] + '/' + c['repository'] + '/pull/' + str(raw['number']),
                'duplicate-mr', 'PR 地址不符')
        data.sha(raw['head']['sha'])
        state = 'merged' if raw['state'] == 'closed' and raw['merged'] else ('opened' if raw['state'] == 'open' and not raw['merged'] else 'closed')
        return dict(iid=raw['number'], web_url=raw['html_url'], source_branch=raw['head']['ref'],
                    target_branch=raw['base']['ref'], sha=raw['head']['sha'], state=state,
                    title=raw.get('title'), description=raw.get('body'), draft=raw.get('draft'))

    def find_change_requests(self, source, target):
        data.branch(source)
        require(source != 'main' and target == 'main', 'conditions-unmet', '日常发布只允许任务分支到 main')
        rows = paged(self.api, self.endpoint + '/pulls', dict(state='all', head=self.config['repository'].split('/')[0] + ':' + source, base=target))
        numbers = []
        for row in rows:
            require(type(row) is dict and type(row.get('number')) is int, 'tool-unavailable', 'PR 列表身份不可核', 'not-checked')
            numbers.append(row['number'])
        require(len(set(numbers)) == len(numbers), 'duplicate-mr', '分页出现重复 PR 身份')
        return [self.read_change_request(n) for n in numbers]

    def read_change_request(self, number):
        require(type(number) is int and number > 0, 'input-invalid', 'PR number 非法')
        value = self.normalize(self.api('GET', self.endpoint + '/pulls/' + str(number)))
        require(value['iid'] == number, 'duplicate-mr', 'PR 回读 number 不一致')
        return value

    def create_change_request(self, ctx, h, mr, description, target_sha):
        self.inspect_repository()
        require(not self.find_change_requests(ctx['source_branch'], ctx['target_branch']), 'duplicate-mr', '创建前出现已有 PR')
        branch = self.api('GET', self.endpoint + '/branches/main')
        require(branch.get('commit', {}).get('sha') == target_sha, 'remote-mismatch', '创建前 main 改变')
        body = dict(title=mr['title'], body=description, head=ctx['source_branch'], base=ctx['target_branch'], draft=False)
        try:
            raw = self.api('POST', self.endpoint + '/pulls', body)
            value = self.read_change_request(raw.get('number'))
        except (PlatformError, data.Invalid, KeyError, TypeError, AttributeError) as exc:
            raise PlatformError('external-unknown', 'PR POST 或回读结果不确定；需要 GET 对账', 'external-unknown') from exc
        require(value['title'] == mr['title'] and value['description'] == description and value['draft'] is False,
                'external-unknown', 'PR 标题、完整申报或普通 PR 属性回读不符', 'external-unknown')
        return value
