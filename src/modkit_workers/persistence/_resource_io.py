"""Private finite origin/POSIX/Z1 reader; inert at import, no Windows backend."""
from __future__ import annotations

import errno
import io
import os
import stat
import struct
import sys
import zipfile
import zipimport
import zlib
from importlib import resources
from importlib.machinery import SourceFileLoader
from pathlib import Path

MANIFEST_LIMIT = 65536
SQL_LIMIT = 16777216
ARCHIVE_LIMIT = 268435456
DIRECTORY_LIMIT = 16777216
ENTRY_LIMIT = 65534
FIELD_LIMIT = 4096
_NAMES = ('manifest.json', '0001_initial.sql', 'grants_runtime.sql')
_NOTE = 'Migration resource cleanup failed; close outcome is uncertain.'


def _unsupported():
    raise ValueError('unsupported migration resource backend')


def _containment():
    raise ValueError('migration resource containment failure')


def _archive_error():
    raise ValueError('invalid migration resource archive')


def _large(name=None):
    raise ValueError('migration manifest too large' if name == 'manifest.json' else 'migration resource too large')


def _limit(name, limit):
    if type(name) is not str or name not in _NAMES:
        _containment()
    bound = MANIFEST_LIMIT if name == 'manifest.json' else SQL_LIMIT
    if limit is not None:
        if type(limit) is not int or limit < 0:
            _containment()
        bound = min(bound, limit)
    return bound


def _cleanup(owned, primary):
    first = None
    while owned:
        fd = owned.pop()  # Detach before uncertain close; never retry.
        try:
            os.close(fd)
        except BaseException as error:
            if first is None:
                first = error
    if first is not None:
        if primary is None:
            raise first
        BaseException.add_note(primary, _NOTE)


def _platform():
    if os.name != 'posix' or os.open not in os.supports_dir_fd or not all(
        hasattr(os, flag) for flag in ('O_DIRECTORY', 'O_NOFOLLOW', 'O_NONBLOCK')
    ):
        _unsupported()


def _read_fd(fd, bound, name=None):
    chunks, total = [], 0
    while True:
        chunk = os.read(fd, min(65536, bound + 1 - total))
        if not chunk:
            return b''.join(chunks)
        total += len(chunk)
        if total > bound:
            _large(name)
        chunks.append(chunk)


class PosixLease:
    """One trusted directory object; only fixed no-follow direct child reads."""
    def __init__(self, root):
        _platform()
        self.owned = []
        self.root_fd = None
        try:
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            self.owned.append(fd)
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                _containment()
            self.root_fd = fd
        except BaseException as error:
            _cleanup(self.owned, error)
            raise

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        self.root_fd = None
        _cleanup(self.owned, error)
        return False

    def read(self, name, limit=None):
        bound = _limit(name, limit)
        if self.root_fd is None:
            _containment()
        owned = []
        primary = None
        try:
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.root_fd)
            except OSError as error:
                if error.errno in (errno.ELOOP, errno.ENOTDIR):
                    _containment()
                raise
            owned.append(fd)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                _containment()
            return _read_fd(fd, bound, name)
        except BaseException as error:
            primary = error
            raise
        finally:
            _cleanup(owned, primary)


def _snapshot(path):
    _platform()
    owned, primary = [], None
    try:
        # The container locator is trusted, unlike a resource descendant.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        owned.append(fd)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            _containment()
        return _read_fd(fd, ARCHIVE_LIMIT)
    except BaseException as error:
        primary = error
        raise
    finally:
        _cleanup(owned, primary)


def _name(raw, flags):
    if not raw or b'\0' in raw:
        _containment()
    try:
        value = raw.decode('utf-8' if flags & 0x800 else 'cp437')
    except UnicodeError:
        _containment()
    if '\\' in value or ':' in value or value.startswith('/'):
        _containment()
    parts = value[:-1].split('/') if value.endswith('/') else value.split('/')
    if any(p in ('', '.', '..') for p in parts):
        _containment()
    return value


def _extra(raw):
    cursor, seen = 0, set()
    while cursor < len(raw):
        if cursor + 4 > len(raw):
            _archive_error()
        tag, length = struct.unpack_from('<HH', raw, cursor)
        cursor += 4
        if tag in seen or cursor + length > len(raw):
            _archive_error()
        seen.add(tag)
        value = raw[cursor:cursor+length]
        cursor += length
        if tag == 0x5455:
            if not value or value[0] & ~7 or len(value) != 1 + 4 * value[0].bit_count():
                _archive_error()
        elif tag == 0x7875:
            if len(value) < 4 or value[0] != 1 or not 1 <= value[1] <= 8:
                _archive_error()
            pos = 2 + value[1]
            if pos >= len(value) or not 1 <= value[pos] <= 8 or pos + 1 + value[pos] != len(value):
                _archive_error()
        else:
            _unsupported()


def _central_candidate(data, pos, end):
    """Scalar/range and complete central framing, before candidate selection."""
    _, disk, cd_disk, disk_count, count, size, offset, _ = end
    if not count or count != disk_count or offset + size != pos:
        _archive_error()
    if disk or cd_disk or count == 65535 or size == 0xffffffff or offset == 0xffffffff:
        _unsupported()
    if size > DIRECTORY_LIMIT or count > ENTRY_LIMIT:
        _large()
    cursor, actual = offset, 0
    while cursor < pos:
        if cursor + 46 > pos or data[cursor:cursor+4] != b'PK\x01\x02':
            _archive_error()
        n, x, c = struct.unpack_from('<3H', data, cursor+28)
        if max(n, x, c) > FIELD_LIMIT:
            _large()
        cursor += 46+n+x+c
        actual += 1
        if cursor > pos or actual > ENTRY_LIMIT:
            _archive_error()
    if cursor != pos or actual != count:
        _archive_error()
    return offset, pos, count


def _directory(data):
    if len(data) > ARCHIVE_LIMIT:
        _large()
    selected = None
    trailing = []
    failure = None
    # Fixed tail window. No unbounded search for arbitrary embedded archives.
    for pos in range(max(0, len(data)-65557), max(0, len(data)-21)):
        if data[pos:pos+4] != b'PK\x05\x06':
            continue
        end = struct.unpack_from('<4s4H2IH', data, pos)
        declared_end = pos + 22 + end[7]
        if declared_end > len(data):
            continue
        try:
            candidate = _central_candidate(data, pos, end)
        except ValueError as error:
            if declared_end == len(data):
                # A false comment signature must not veto a valid candidate.
                # Preserve genuine budget/profile errors only if none is valid.
                if failure is None or str(error) != 'invalid migration resource archive':
                    failure = error
            continue
        if declared_end == len(data):
            if selected is not None:
                _archive_error()
            selected = candidate
        else:
            trailing.append(candidate)
    if selected is not None:
        return selected
    # Positive trailing recognition requires full original record agreement.
    # Failed recognizers do not turn arbitrary malformed bytes into a profile.
    for candidate in trailing:
        try:
            _records(data, candidate)
        except ValueError:
            continue
        _unsupported()
    if failure is not None:
        raise failure
    _archive_error()


def _records(data, directory=None):
    offset, end, count = _directory(data) if directory is None else directory
    records, names, intervals = [], {}, []
    unsupported_descriptor = False
    cursor = offset
    for _ in range(count):
        v = struct.unpack_from('<4s6H3I5H2I', data, cursor)
        (_, made, needed, flags, method, tm, date, crc, compressed, size,
         n, x, c, disk, internal, external, local) = v
        if needed > 20 or made >> 8 not in (0, 3) or method not in (0, 8) or disk:
            _unsupported()
        if flags & ~(0x808 | (6 if method == 8 else 0)):
            _unsupported()
        if compressed == 0xffffffff or size == 0xffffffff or local == 0xffffffff:
            _unsupported()
        raw_name = data[cursor+46:cursor+46+n]
        name = _name(raw_name, flags)
        _extra(data[cursor+46+n:cursor+46+n+x])
        cursor += 46+n+x+c
        key = name.rstrip('/')
        if key in names:
            _containment()
        is_dir = name.endswith('/')
        dos, mode = external & 0xffff, external >> 16
        kind = mode & 0xf000
        if dos & ~0x37 or kind not in (0, 0x4000, 0x8000) or (made >> 8 == 0 and mode):
            _containment()
        if (dos & 0x10 and not is_dir) or (kind == 0x4000 and not is_dir) or (kind == 0x8000 and is_dir):
            _containment()
        if is_dir and (size or compressed or crc or method):
            _archive_error()
        names[key] = is_dir
        if local + 30 > offset or data[local:local+4] != b'PK\x03\x04':
            _archive_error()
        lv = struct.unpack_from('<4s5H3I2H', data, local)
        _, ln, lf, lm, lt, ld, lc, lcomp, lsize, nn, xx = lv
        if max(nn, xx) > FIELD_LIMIT:
            _large()
        start = local+30+nn+xx
        stop = start+compressed
        if start > offset or stop > offset or (ln,lf,lm,lt,ld) != (needed,flags,method,tm,date):
            _archive_error()
        if data[local+30:local+30+nn] != raw_name:
            _archive_error()
        _extra(data[local+30+nn:start])
        if flags & 8:
            expected = (crc, compressed, size)
            if (lc, lcomp, lsize) not in ((0, 0, 0), expected):
                _archive_error()
            # A CRC may equal the signature. Keep every complete alternative
            # until the actual next local/central boundary selects its length.
            finishes = []
            if (stop+16 <= offset and data[stop:stop+4] == b'PK\x07\x08'
                    and struct.unpack_from('<3I', data, stop+4) == expected):
                finishes.append((stop+16, False))
            if stop+12 <= offset and struct.unpack_from('<3I', data, stop) == expected:
                finishes.append((stop+12, True))
            if not finishes:
                _archive_error()
            if (lc, lcomp, lsize) != (0, 0, 0):
                unsupported_descriptor = True
        else:
            if (lc,lcomp,lsize) != (crc,compressed,size):
                _archive_error()
            finishes = [(stop, False)]
        intervals.append((local, finishes))
        records.append((name,flags,method,crc,compressed,size,local,made,needed,external,start,stop))
    for key in names:
        parts=key.split('/')
        for i in range(1,len(parts)):
            ancestor='/'.join(parts[:i])
            if ancestor in names and not names[ancestor]:
                _containment()
    ordered = sorted(intervals)
    initial = ordered[0][0]
    for index, (start, finishes) in enumerate(ordered):
        boundary = ordered[index+1][0] if index+1 < len(ordered) else offset
        matches = [unsigned for finish, unsigned in finishes if finish == boundary]
        if boundary < start or len(matches) != 1:
            _archive_error()
        unsupported_descriptor |= matches[0]
    if initial or unsupported_descriptor:
        _unsupported()
    return records


class ZipLease:
    """Owned immutable snapshot, finite Z1 metadata, bounded raw decompression."""
    def __init__(self, data, prefix):
        if type(data) is not bytes:
            _unsupported()
        self.data = data
        self.prefix = prefix
        directory = _directory(data)
        records = _records(data, directory)
        # One immutable projection allocation; memoryview avoids a prefix copy.
        # Raw resource bytes remain in self.data, not this metadata-only view.
        projection = b''.join((memoryview(data)[:directory[1]+20], b'\x00\x00'))
        # ZipFile is only an independent metadata interpreter, not output oracle.
        owned, primary = [], None
        try:
            stream = io.BytesIO(projection)
            owned.append(stream)
            try:
                archive = zipfile.ZipFile(stream)
                owned.append(archive)
                infos = archive.infolist()
                if len(infos) != len(records):
                    _archive_error()
                for info, rec in zip(infos, records):
                    got = (info.filename, info.flag_bits, info.compress_type, info.CRC, info.compress_size,
                           info.file_size, info.header_offset, info.create_system*256+info.create_version,
                           info.extract_version, info.external_attr)
                    if got != rec[:10]:
                        _archive_error()
            except (zipfile.BadZipFile, UnicodeError, struct.error):
                _archive_error()
        except BaseException as error:
            primary = error
            raise
        finally:
            first = None
            while owned:
                item = owned.pop()
                try:
                    item.close()
                except BaseException as error:
                    if first is None:
                        first = error
            if first is not None:
                if primary is None:
                    raise first
                BaseException.add_note(primary, _NOTE)
        self.entries={r[0]:r for r in records}

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        self.data=b''
        self.entries.clear()
        return False

    def read(self,name,limit=None):
        bound=_limit(name,limit)
        rec=self.entries.get(self.prefix+name)
        if rec is None:
            if self.prefix+name+'/' in self.entries:
                _containment()
            raise FileNotFoundError(name)
        _,_,method,crc,compressed,size,_,_,_,_,start,stop=rec
        if size > bound:
            _large(name)
        if method==0:
            if compressed != size:
                _archive_error()
            output=self.data[start:stop]
            if zlib.crc32(output)&0xffffffff != crc:
                _archive_error()
            return output
        decompressor=zlib.decompressobj(-15)
        chunks=[]
        total=checksum=0
        cursor=start
        pending=b''
        try:
            while True:
                if not pending and cursor < stop:
                    pending=self.data[cursor:min(stop,cursor+65536)]
                    cursor+=len(pending)
                before=len(pending)
                output=decompressor.decompress(pending,min(65536,bound-total+1))
                total+=len(output)
                if total > bound:
                    _large(name)
                if total > size:
                    _archive_error()
                checksum=zlib.crc32(output,checksum)
                chunks.append(output)
                pending=decompressor.unconsumed_tail
                if decompressor.eof:
                    if pending or decompressor.unused_data or cursor != stop:
                        _archive_error()
                    break
                if not output and len(pending)==before and cursor==stop:
                    _archive_error()
            if total != size or checksum&0xffffffff != crc:
                _archive_error()
        except zlib.error:
            _archive_error()
        return b''.join(chunks)


def _absolute(value):
    if type(value) is not str or not value or '\0' in value:
        _unsupported()
    value=value.replace('\\','/') if os.name=='nt' else value
    if not Path(value).is_absolute() or any(p in ('.','..','') for p in value.split('/')[1:]):
        _unsupported()
    return value


def open_lease(anchor):
    if anchor not in ('modkit_events.persistence.sql','modkit_workers.persistence.sql'):
        _unsupported()
    module=sys.modules.get(anchor)
    spec=getattr(module,'__spec__',None)
    loader=getattr(module,'__loader__',None)
    if spec is None or spec.name != anchor or spec.loader is not loader or type(loader) not in (SourceFileLoader,zipimport.zipimporter):
        _unsupported()
    locations=spec.submodule_search_locations
    if locations is None or len(locations)!=1 or type(locations[0]) is not str:
        _unsupported()
    if type(loader) is SourceFileLoader:
        origin=_absolute(spec.origin)
        location=_absolute(locations[0])
        if loader.name != anchor or _absolute(loader.path)!=origin or Path(origin).name!='__init__.py' or str(Path(origin).parent)!=location:
            _unsupported()
        root=resources.files(anchor)
        if type(root) is not type(Path()) or str(root)!=location:
            _unsupported()
        return PosixLease(root)
    archive=_absolute(loader.archive)
    prefix=loader.prefix.replace('\\','/')
    if prefix and (not prefix.endswith('/') or _name(prefix.encode('utf-8'),0x800)!=prefix):
        _unsupported()
    package=anchor.split('.')[0]
    if not prefix.endswith(package+'/persistence/'):
        _unsupported()
    prefix+='sql/'
    if _absolute(spec.origin) != archive+'/'+prefix+'__init__.py' or _absolute(locations[0]) != archive+'/'+prefix.rstrip('/'):
        _unsupported()
    return ZipLease(_snapshot(archive),prefix)
