"""One supervised maintenance-adapter worker. Not a general command runner."""
import base64
import json
import os
from pathlib import Path
import sys
import time
import hashlib
from datetime import datetime, timezone


def atomic(path,value):
    temp=path.with_suffix('.tmp')
    with temp.open('x') as f:
        json.dump(value,f);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def main():
    job_path=Path(sys.argv[1]);job=json.loads(job_path.read_text());directory=job_path.parent
    sys.path.insert(0,job['mechanism'])
    import review_channel_base as B
    import review_channel_runtime as RT
    import review_channel_secrets as S
    token=B.process_start_token(os.getpid())
    # OS process birth time, not the time at which the identity was recorded.
    if sys.platform=='darwin':start=datetime.strptime(token,'%a %b %d %H:%M:%S %Y').astimezone().isoformat()
    elif sys.platform.startswith('linux'):
        ticks=int(token.split('@')[0]);boot=[x for x in Path('/proc/stat').read_text().splitlines() if x.startswith('btime ')][0]
        start=datetime.fromtimestamp(int(boot.split()[1])+ticks/os.sysconf('SC_CLK_TCK'),timezone.utc).isoformat()
    else:raise RuntimeError('process birth time unsupported')
    atomic(directory/'ready.json',dict(pid=os.getpid(),token=token,start_time=start))
    deadline=time.monotonic()+30
    while not (directory/'go.json').exists():
        if time.monotonic()>deadline:return 3
        time.sleep(.02)
    ctx=job['context'];ctx['secrets']=S.SecretHandle()
    try:
        S.resolve_for_provider(ctx['provider'],ctx['secrets'],S.ZSHRC_PATH)
        adapter=RT.load_adapter(ctx['provider']['runtime'],str(Path(job['mechanism'])/'adapters'))
        facts=adapter.preflight(ctx)
        binary=facts.get('binary');version=facts.get('tool_version')
        if not isinstance(binary,str) or not isinstance(version,str):raise RuntimeError('program identity unsupported')
        actual_program=dict(launcher=str(Path(binary).resolve(strict=True)),binaryDigest=hashlib.sha256(Path(binary).read_bytes()).hexdigest(),version=version)
        if actual_program!=job['program_identity']:raise RuntimeError('program identity changed')
        ctx['expected_program_identity']=actual_program
        # Check sealed originals immediately before any model-capable adapter run.
        for item in ctx['manifest']['inputs']:
            path=Path(ctx['seal_dir'])/item['bundle_name']
            if path.is_symlink():raise ValueError('material symlink')
            data=path.read_bytes()
            if len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('material identity')
        result=adapter.run(ctx)
        answer=result['final_message'];clean,hit=B.scrub_secrets(answer,ctx['secrets'].scan_set())
        actual=result['identity_claim']
        out=dict(answer=base64.b64encode(clean).decode(),model=actual,process=result['process'],failure=result['failure'],secret_redacted=hit,program_identity=actual_program)
        if hit:out.update(answer='',failure='execution_port_failure')
        atomic(directory/'result.json',out)
        return 0
    except BaseException as exc:
        atomic(directory/'result.json',dict(answer='',model=None,process=dict(exit_code=None,timed_out=False,stderr_summary=type(exc).__name__),failure='execution_port_failure',secret_redacted=False))
        return 1

if __name__=='__main__':sys.exit(main())
