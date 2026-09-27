#!/usr/bin/env python3
"""Offline isolated repositories for CL-52 history reads and consumer regressions."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import history_read as H


class Fixture:
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.git('init', '-q'); self.git('config', 'user.name', 'Fixture'); self.git('config', 'user.email', 'fixture@example.invalid')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def write(self, path, data):
        p = self.root/path; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())

    def commit(self, *paths):
        present = [p for p in paths if (self.root/p).exists() or (self.root/p).is_symlink()]
        if present: self.git('add', '--', *present)
        self.git('commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def declare(self, paths, source=None, locator='approval-1'):
        source = source or self.git('rev-parse', 'HEAD')
        approval = 'records/governance/example/approval.md'
        old = (self.root/approval).read_text() if (self.root/approval).exists() else ''
        self.write(approval, old+'\n## '+locator+'\n\nFixture approval for '+', '.join(paths)+'\n')
        self.commit(approval)
        paths = sorted(paths, key=lambda s:s.encode())
        row = dict(version=1, source_commit=source, selection=dict(roots=[],paths=paths,exclude=[]),
                   paths_sha256=hashlib.sha256(''.join(p+'\n' for p in paths).encode()).hexdigest(),
                   objects_sha256=hashlib.sha256(''.join(p+'\t'+self.git('rev-parse', source+':'+p)+'\n' for p in paths).encode()).hexdigest(),
                   authority_ref=approval+'#'+locator)
        old = (self.root/H.LOCATIONS).read_bytes() if (self.root/H.LOCATIONS).exists() else b''
        self.write(H.LOCATIONS, old+json.dumps(row).encode()+b'\n')
        self.git('rm', '--', *paths)
        return row, self.commit(H.LOCATIONS, *paths)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.f = Fixture(self.tmp.name); self.p='records/lineage/example/fact.md'
        self.f.write(self.p,b'fact\n'); self.source=self.f.commit(self.p)

    def raises_code(self, code, fn, *args):
        with self.assertRaises(H.HistoryReadError) as ctx: fn(*args)
        self.assertEqual(ctx.exception.code,code)

    def test_unenabled_and_explicit_exact_bytes(self):
        self.assertEqual(H.list_history(self.f.root,self.source,''),[])
        self.assertEqual(H.read_history(self.f.root,self.source,self.p,self.source)['content'],b'fact\n')
        self.raises_code('history-integrity',H.read_history,self.f.root,self.source,self.p,self.source,'0'*64)
        self.raises_code('history-invalid',H.read_history,self.f.root,self.source,'../secret',self.source)

    def test_archive_identity_and_no_write(self):
        row,view=self.f.declare([self.p]);before=self.f.git('status','--porcelain')
        item=H.read_history(self.f.root,view,self.p)
        self.assertEqual(item['content'],b'fact\n');self.assertEqual(item['source_commit'],self.source)
        self.assertEqual(len(H.list_history(self.f.root,view,'records/lineage/')),1)
        self.assertEqual(self.f.git('status','--porcelain'),before)
        self.assertFalse((self.f.root/self.p).exists())

    def test_deleted_or_rewritten_locations_fail(self):
        row,view=self.f.declare([self.p]);self.f.git('rm',H.LOCATIONS);bad=self.f.commit(H.LOCATIONS)
        self.raises_code('history-invalid',H.list_history,self.f.root,bad,'')

    def test_bad_syntax_and_digest(self):
        row,view=self.f.declare([self.p])
        for change in [dict(version=True),dict(extra=1),dict(selection=dict(roots=[],paths=['../x'],exclude=[]))]:
            bad=dict(row,**change)
            self.raises_code('history-invalid',H.validate_locations_syntax,json.dumps(bad)+'\n')
        self.raises_code('history-invalid',H.validate_locations_syntax,'{"version":1,"version":1}\n')
        self.raises_code('history-invalid',H.validate_locations_syntax,json.dumps(row)+'\n'+json.dumps(row)+'\n')
        # Fresh branch without an old declaration, so this tests integrity rather than append-only.
        self.f.git('checkout','-q','-b','bad',view+'^')
        row['objects_sha256']='0'*64;self.f.write(H.LOCATIONS,json.dumps(row)+'\n');bad=self.f.commit(H.LOCATIONS)
        self.raises_code('history-integrity',H.list_history,self.f.root,bad,'')

    def test_versions_require_explicit_source(self):
        _,v1=self.f.declare([self.p]);self.f.write(self.p,'changed\n');s2=self.f.commit(self.p)
        _,v2=self.f.declare([self.p],s2,'approval-2')
        self.raises_code('history-ambiguous',H.read_history,self.f.root,v2,self.p)
        self.assertEqual(H.read_history(self.f.root,v2,self.p,self.source)['content'],b'fact\n')
        self.assertEqual(H.read_history(self.f.root,v2,self.p,s2)['content'],b'changed\n')

    def test_symlink_replace_graft_and_nonancestor(self):
        (self.f.root/'link').symlink_to(self.p);view=self.f.commit('link')
        self.raises_code('history-invalid',H.read_history,self.f.root,view,'link',view)
        self.raises_code('history-unavailable',H.read_history,self.f.root,self.source,self.p,view)
        self.f.git('replace',self.source,view)
        self.raises_code('history-invalid',H.read_history,self.f.root,view,self.p,view)
        self.f.git('replace','-d',self.source)
        self.f.write('.git/info/grafts','')
        self.raises_code('history-invalid',H.read_history,self.f.root,view,self.p,view)

    def test_shallow_missing_object_cli_and_no_network(self):
        _,view=self.f.declare([self.p]);clone=Path(self.tmp.name)/'shallow'
        subprocess.run(['git','clone','-q','--depth=1','file://'+str(self.f.root),str(clone)],check=True)
        self.raises_code('history-unavailable',H.list_history,clone,view,'')
        cli=Path(H.__file__)
        p=subprocess.run([sys.executable,'-B',str(cli),'read','--repo-root',str(self.f.root),'--view-commit',view,'--path',self.p],capture_output=True)
        self.assertEqual(p.returncode,0);self.assertEqual(p.stdout,b'fact\n');self.assertEqual(json.loads(p.stderr)['source_commit'],self.source)
        p=subprocess.run([sys.executable,'-B',str(cli),'list','--repo-root',str(self.f.root),'--view-commit',view,'--path',self.p],capture_output=True)
        self.assertEqual(p.returncode,2);self.assertFalse(p.stdout);self.assertEqual(json.loads(p.stderr)['code'],'usage-error')

    def test_missing_blob_does_not_lazy_fetch(self):
        _,view=self.f.declare([self.p]);oid=self.f.git('rev-parse',self.source+':'+self.p)
        self.f.git('config','remote.origin.url','https://127.0.0.1:1/must-not-contact')
        self.f.git('config','remote.origin.promisor','true')
        (self.f.root/'.git/objects'/oid[:2]/oid[2:]).unlink()
        self.raises_code('history-unavailable',H.read_history,self.f.root,view,self.p,self.source)
        self.assertFalse((self.f.root/'.git/FETCH_HEAD').exists())

    def test_truncated_rebuilt_index_and_prefix_isolation(self):
        row,view=self.f.declare([self.p]);self.f.write(H.LOCATIONS,'');bad=self.f.commit(H.LOCATIONS)
        self.raises_code('history-invalid',H.list_history,self.f.root,bad,'')
        self.f.write(H.LOCATIONS,json.dumps(row)+'\n');rebuilt=self.f.commit(H.LOCATIONS)
        self.raises_code('history-invalid',H.list_history,self.f.root,rebuilt,'')

    def test_roots_exclusions_dedup_and_invalid_exclusion(self):
        self.f.write('records/lineage/example/other.md','other\n');source=self.f.commit('records/lineage/example/other.md')
        row,view=self.f.declare([self.p],source)
        self.f.git('checkout','-q','-b','roots',view+'^')
        row['selection']=dict(roots=['records/lineage/example/'],paths=[self.p],exclude=['records/lineage/example/other.md'])
        self.f.write(H.LOCATIONS,json.dumps(row)+'\n');view=self.f.commit(H.LOCATIONS)
        self.assertEqual(len(H.list_history(self.f.root,view,'')),1)
        self.assertEqual(H.list_history(self.f.root,view,'unrelated/'),[])

    def test_gitlink_and_missing_tree_commit_rejected(self):
        self.f.git('update-index','--add','--cacheinfo','160000,'+self.source+',external')
        self.f.git('commit','-qm','gitlink fixture'); view=self.f.git('rev-parse','HEAD')
        self.raises_code('history-invalid',H.read_history,self.f.root,view,'external',view)
        self.raises_code('history-unavailable',H.read_history,self.f.root,view,self.p,'0'*40)
        tree=self.f.git('rev-parse',view+':records')
        (self.f.root/'.git/objects'/tree[:2]/tree[2:]).unlink()
        self.raises_code('history-unavailable',H.read_history,self.f.root,view,self.p,view)

    def test_authority_resolved_at_introduction_and_bad_selection(self):
        row,view=self.f.declare([self.p]);approval=row['authority_ref'].split('#')[0]
        self.f.write(approval,'changed current authority text\n');later=self.f.commit(approval)
        self.assertEqual(H.read_history(self.f.root,later,self.p)['content'],b'fact\n')
        self.f.git('checkout','-q','-b','invalid-exclusion',view+'^')
        row['selection']['exclude']=['not-selected.md']
        self.f.write(H.LOCATIONS,json.dumps(row)+'\n');bad=self.f.commit(H.LOCATIONS)
        self.raises_code('history-invalid',H.list_history,self.f.root,bad,'')

    def test_sha256_repository_and_cli_read_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(['git','init','-q','--object-format=sha256',tmp],check=True)
            fixture=Fixture(tmp); fixture.write(self.p,b'wide oid\n');source=fixture.commit(self.p)
            self.assertEqual(len(source),64)
            result=subprocess.run([sys.executable,'-B',str(Path(H.__file__)),'read','--repo-root',tmp,
                                   '--view-commit',source,'--path',self.p,'--source-commit',source],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,b'wide oid\n');self.assertEqual(json.loads(result.stderr)['source_commit'],source)

    def test_owner_sequence_uses_history(self):
        p='records/governance/example/HarnessPlane_Example_Owner_Decisions_D9.md'
        self.f.write(p,'## old\n');self.f.commit(p);self.f.declare([p])
        self.assertEqual(H.next_owner_decision(self.f.root,'example','HarnessPlane_Example_Owner_Decisions_D'),(10,p))


if __name__=='__main__':
    unittest.main()
