"""Self-contained TEST ONLY resource fixtures, never production assets."""
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import zlib


def aggregate(items):
    parts = [b'MKMF\x01', len(items).to_bytes(4, 'big')]
    for item in sorted(items, key=lambda x: x['path'].encode()):
        path = item['path'].encode()
        parts += [len(path).to_bytes(4, 'big'), path, bytes.fromhex(item['sha256'])]
    return hashlib.sha256(b''.join(parts)).hexdigest()


def archive(files, method=0, prefix='modkit_events/persistence/sql/', descriptor=False):
    """Independent tiny classic ZIP byte oracle; no production parser/writer."""
    local, central = bytearray(), bytearray()
    for name, raw in files.items():
        name = (prefix + name).encode('utf-8')
        flags = 0x800 | (8 if descriptor else 0)
        if method == 8:
            compressor = zlib.compressobj(wbits=-15)
            data = compressor.compress(raw) + compressor.flush()
        else:
            data = raw
        crc = zlib.crc32(raw) & 0xffffffff
        offset = len(local)
        vals = (0, 0, 0) if descriptor else (crc, len(data), len(raw))
        local += struct.pack('<4s5H3I2H', b'PK\x03\x04', 20, flags, method, 0, 0, *vals, len(name), 0)
        local += name + data
        if descriptor:
            local += struct.pack('<4s3I', b'PK\x07\x08', crc, len(data), len(raw))
        central += struct.pack('<4s6H3I5H2I', b'PK\x01\x02', 20, 20, flags, method, 0, 0,
                               crc, len(data), len(raw), len(name), 0, 0, 0, 0, 0, offset) + name
    return bytes(local + central + struct.pack('<4s4H2IH', b'PK\x05\x06', 0, 0, len(files), len(files), len(central), len(local), 0))


class Sandbox:
    def __init__(self, component):
        self.temporary = tempfile.TemporaryDirectory(prefix='modkit-resource-test-', dir=os.environ.get('MODKIT_RESOURCE_TEST_BASE'))
        self.base = Path(self.temporary.name)
        self.component = component
        self.files = {'0001_initial.sql': b'-- TEST ONLY ordinary \xc3\xa9\r\n', 'grants_runtime.sql': b'-- TEST ONLY grants\n'}
        entries = [dict(path=component+'/'+name, sha256=hashlib.sha256(raw).hexdigest()) for name, raw in self.files.items()]
        record = dict(component=component, version=1, resources=entries, migration_digest=aggregate(entries),
                      depends_on=[] if component=='events' else [dict(component='events',version=1,migration_digest='a'*64)],
                      catalog_contract_id='modkit-pg-ab-2',scope_format_id='MKSC-1',intent_format_id='MKPF-1')
        self.files['manifest.json'] = json.dumps(dict(format_version=1,package='modkit-'+component,migrations=[record])).encode()
        self.link_error = None
        try:
            self.root = self.directory('valid', self.files)
            self.directory('container', {})
            try:
                self.link('root-link', 'valid')
                self.link('container/ancestor', '../valid')
                for leaf in self.files:
                    name = leaf.split('.')[0]+'-link'
                    self.directory(name, self.files)
                    (self.base/name/leaf).unlink()
                    self.link(name+'/'+leaf, '../valid/'+leaf)
            except (OSError, NotImplementedError) as error:
                self.link_error = error
        except BaseException:
            self.close()
            raise

    def write_archive(self, data):
        path = self.base/'fixture.zip'
        path.write_bytes(data)
        return path

    def move_root(self):
        self.root.rename(self.base/'held')
        self.directory('valid', {'manifest.json':b'not the original'})

    def directory(self, name, files):
        root = self.base/name
        root.mkdir()
        for leaf, raw in files.items():
            (root/leaf).write_bytes(raw)
        return root

    def link(self, name, target):
        # All supplied specifications are helper-owned, relative inside sandbox.
        destination = self.base/name
        resolved = (destination.parent/target).resolve()
        if not resolved.is_relative_to(self.base):
            raise ValueError('fixture target must remain in sandbox')
        destination.symlink_to(target, target_is_directory=resolved.is_dir())

    def close(self):
        # Remove link entries rather than recursively visiting their targets.
        for root, dirs, files in os.walk(self.base, topdown=False, followlinks=False):
            for name in files:
                Path(root,name).unlink()
            for name in dirs:
                p=Path(root,name)
                p.unlink() if p.is_symlink() else p.rmdir()
        self.temporary.cleanup()
