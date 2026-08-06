import hashlib
import os
import re
import sqlite3
import threading
import time
import unicodedata


KONGMING_INDEX_SCHEMA_VERSION = '1'
KONGMING_INDEX_DEFAULT_INTERVAL = 60
KONGMING_INDEX_MAX_QUERY_KEYS = 700

_CJK_PATTERN = re.compile(r'[\u3400-\u9fff]{2,}')
_IDENTIFIER_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{1,159}|\d{4,}')

_watcher_lock = threading.Lock()
_watcher_event = threading.Event()
_watcher_thread = None
_watcher_config = {}
_watcher_pending_reason = ''
_runtime_status = {}


def _now_text():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _relative_path(path, root):
    return os.path.relpath(path, root).replace('\\', '/')


def _index_keys(value):
    normalized = unicodedata.normalize('NFKC', str(value or ''))
    keys = set()
    for chunk in _CJK_PATTERN.findall(normalized):
        keys.update(chunk[index:index + 2] for index in range(len(chunk) - 1))
    for raw_value in _IDENTIFIER_PATTERN.findall(normalized):
        clean = raw_value.lower().strip('._-')
        if len(clean) < 2:
            continue
        keys.add(clean)
        keys.update(
            part for part in re.split(r'[._-]+', clean)
            if len(part) >= 2
        )
    return keys


def _query_keys_by_term(terms):
    result = {}
    total = 0
    for term in terms:
        clean = unicodedata.normalize('NFKC', str(term or '')).strip()
        if not clean:
            continue
        keys = _index_keys(clean)
        if not keys:
            continue
        remaining = KONGMING_INDEX_MAX_QUERY_KEYS - total
        if remaining <= 0:
            break
        selected = set(sorted(keys)[:remaining])
        result[clean] = selected
        total += len(selected)
    return result


def _connect(index_path):
    os.makedirs(os.path.dirname(os.path.abspath(index_path)), exist_ok=True)
    connection = sqlite3.connect(index_path, timeout=30)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA synchronous=NORMAL')
    connection.execute('PRAGMA temp_store=MEMORY')
    connection.execute('PRAGMA cache_size=-131072')
    connection.execute('PRAGMA mmap_size=268435456')
    return connection


def _metadata(connection):
    try:
        rows = connection.execute('SELECT key, value FROM metadata').fetchall()
    except sqlite3.DatabaseError:
        return {}
    return {str(key): str(value) for key, value in rows}


def _set_metadata(connection, values):
    connection.executemany(
        '''INSERT INTO metadata(key, value) VALUES(?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
        [(str(key), str(value)) for key, value in values.items()],
    )


def _ensure_schema(connection):
    connection.execute(
        'CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)'
    )
    metadata = _metadata(connection)
    if metadata.get('schema_version') not in (None, KONGMING_INDEX_SCHEMA_VERSION):
        connection.execute('DROP TABLE IF EXISTS terms')
        connection.execute('DROP TABLE IF EXISTS files')
        connection.execute('DELETE FROM metadata')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS files(
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            term_count INTEGER NOT NULL,
            indexed_at REAL NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS terms(
            term TEXT NOT NULL,
            path TEXT NOT NULL,
            PRIMARY KEY(term, path)
        ) WITHOUT ROWID
    ''')
    connection.execute('CREATE INDEX IF NOT EXISTS terms_path_idx ON terms(path)')
    _set_metadata(connection, {'schema_version': KONGMING_INDEX_SCHEMA_VERSION})
    connection.commit()


def _iter_json_files(json_root):
    for base, directories, names in os.walk(json_root):
        directories[:] = sorted(
            name for name in directories
            if name not in ('.git', '__pycache__')
        )
        for name in sorted(names):
            if not name.lower().endswith('.json'):
                continue
            path = os.path.abspath(os.path.join(base, name))
            try:
                stat = os.stat(path)
            except OSError:
                continue
            yield _relative_path(path, json_root), path, stat


def _report(progress, **values):
    if progress:
        try:
            progress(dict(values))
        except Exception:
            pass


def sync_kongming_index(json_root, index_path, force=False, progress=None):
    started_at = time.time()
    json_root = os.path.abspath(json_root)
    index_path = os.path.abspath(index_path)
    if not os.path.isdir(json_root):
        raise FileNotFoundError(f'配置 JSON 目录不存在：{json_root}')

    connection = _connect(index_path)
    try:
        _ensure_schema(connection)
        metadata = _metadata(connection)
        ready_before = metadata.get('ready') == '1'
        state = 'updating' if ready_before else 'building'
        _set_metadata(connection, {
            'state': state,
            'ready': '1' if ready_before else '0',
            'json_root': json_root,
            'last_started_at': _now_text(),
            'last_error': '',
        })
        connection.commit()

        disk_files = {
            relative: (path, stat)
            for relative, path, stat in _iter_json_files(json_root)
        }
        existing_rows = connection.execute(
            'SELECT path, size, mtime_ns, sha256, term_count FROM files'
        ).fetchall()
        existing = {
            row[0]: {
                'size': int(row[1]),
                'mtime_ns': int(row[2]),
                'sha256': row[3],
                'term_count': int(row[4]),
            }
            for row in existing_rows
        }
        changed_paths = []
        for relative, (_path, stat) in disk_files.items():
            previous = existing.get(relative)
            if (
                force or previous is None or
                previous['size'] != stat.st_size or
                previous['mtime_ns'] != stat.st_mtime_ns
            ):
                changed_paths.append(relative)
        removed_paths = sorted(set(existing) - set(disk_files))
        changed_paths.sort()
        total_work = max(1, len(changed_paths) + len(removed_paths))
        _report(
            progress,
            state=state,
            percent=1,
            scanned_file_count=len(disk_files),
            pending_file_count=len(changed_paths) + len(removed_paths),
            current_path='',
        )

        content_changes = 0
        touched_files = 0
        processed = 0
        for relative in changed_paths:
            path, _initial_stat = disk_files[relative]
            try:
                with open(path, 'rb') as source:
                    raw = source.read()
                stat = os.stat(path)
            except OSError:
                processed += 1
                continue
            digest = hashlib.sha256(raw).hexdigest()
            previous = existing.get(relative)
            if previous and previous.get('sha256') == digest and not force:
                with connection:
                    connection.execute(
                        'UPDATE files SET size=?, mtime_ns=?, indexed_at=? WHERE path=?',
                        (stat.st_size, stat.st_mtime_ns, time.time(), relative),
                    )
                touched_files += 1
            else:
                text = raw.decode('utf-8', errors='ignore')
                keys = _index_keys(text)
                keys.update(_index_keys(relative))
                with connection:
                    connection.execute('DELETE FROM terms WHERE path=?', (relative,))
                    connection.execute(
                        '''INSERT INTO files(path, size, mtime_ns, sha256, term_count, indexed_at)
                           VALUES(?, ?, ?, ?, ?, ?)
                           ON CONFLICT(path) DO UPDATE SET
                             size=excluded.size,
                             mtime_ns=excluded.mtime_ns,
                             sha256=excluded.sha256,
                             term_count=excluded.term_count,
                             indexed_at=excluded.indexed_at''',
                        (relative, stat.st_size, stat.st_mtime_ns, digest, len(keys), time.time()),
                    )
                    connection.executemany(
                        'INSERT OR IGNORE INTO terms(term, path) VALUES(?, ?)',
                        ((key, relative) for key in sorted(keys)),
                    )
                content_changes += 1
            processed += 1
            _report(
                progress,
                state=state,
                percent=min(98, max(2, int(processed / total_work * 98))),
                scanned_file_count=len(disk_files),
                pending_file_count=total_work - processed,
                current_path=relative,
            )

        if removed_paths:
            with connection:
                connection.executemany(
                    'DELETE FROM terms WHERE path=?',
                    ((path,) for path in removed_paths),
                )
                connection.executemany(
                    'DELETE FROM files WHERE path=?',
                    ((path,) for path in removed_paths),
                )
            processed += len(removed_paths)

        file_count = int(connection.execute('SELECT COUNT(*) FROM files').fetchone()[0])
        term_count = int(connection.execute('SELECT COUNT(*) FROM terms').fetchone()[0])
        old_generation = int(metadata.get('generation') or 0)
        generation = old_generation + (1 if content_changes or removed_paths or not ready_before else 0)
        duration_ms = int((time.time() - started_at) * 1000)
        completed_at = _now_text()
        _set_metadata(connection, {
            'state': 'ready',
            'ready': '1',
            'generation': generation,
            'file_count': file_count,
            'term_count': term_count,
            'last_completed_at': completed_at,
            'last_duration_ms': duration_ms,
            'last_changed_count': content_changes,
            'last_removed_count': len(removed_paths),
            'last_touched_count': touched_files,
            'last_error': '',
        })
        connection.commit()
        result = {
            'ok': True,
            'ready': True,
            'state': 'ready',
            'generation': generation,
            'file_count': file_count,
            'term_count': term_count,
            'changed_count': content_changes,
            'removed_count': len(removed_paths),
            'touched_count': touched_files,
            'duration_ms': duration_ms,
            'completed_at': completed_at,
            'index_path': index_path,
        }
        _report(progress, percent=100, **result)
        return result
    except Exception as exc:
        try:
            metadata = _metadata(connection)
            _set_metadata(connection, {
                'state': 'failed',
                'ready': metadata.get('ready', '0'),
                'last_error': str(exc),
                'last_failed_at': _now_text(),
            })
            connection.commit()
        except sqlite3.DatabaseError:
            pass
        raise
    finally:
        connection.close()


def get_kongming_index_status(index_path):
    index_path = os.path.abspath(index_path)
    result = {
        'available': False,
        'ready': False,
        'state': 'missing',
        'index_path': index_path,
        'generation': 0,
        'file_count': 0,
        'term_count': 0,
        'size_bytes': os.path.getsize(index_path) if os.path.isfile(index_path) else 0,
    }
    if os.path.isfile(index_path):
        try:
            connection = sqlite3.connect(index_path, timeout=5)
            metadata = _metadata(connection)
            connection.close()
            result.update({
                'available': metadata.get('schema_version') == KONGMING_INDEX_SCHEMA_VERSION,
                'ready': metadata.get('ready') == '1',
                'state': metadata.get('state') or 'missing',
                'generation': int(metadata.get('generation') or 0),
                'file_count': int(metadata.get('file_count') or 0),
                'term_count': int(metadata.get('term_count') or 0),
                'last_completed_at': metadata.get('last_completed_at', ''),
                'last_duration_ms': int(metadata.get('last_duration_ms') or 0),
                'last_changed_count': int(metadata.get('last_changed_count') or 0),
                'last_removed_count': int(metadata.get('last_removed_count') or 0),
                'last_error': metadata.get('last_error', ''),
            })
        except (OSError, sqlite3.DatabaseError, ValueError):
            result.update({'state': 'failed', 'last_error': '索引文件无法读取'})
    with _watcher_lock:
        runtime = dict(_runtime_status)
    if runtime.get('index_path') == index_path and runtime.get('state') in (
        'queued', 'building', 'updating', 'failed'
    ):
        result.update(runtime)
        result['ready'] = bool(result.get('ready') or runtime.get('ready'))
    return result


def search_kongming_index(index_path, json_root, terms, limit=500):
    status = get_kongming_index_status(index_path)
    if not status.get('ready'):
        return {}, status
    keys_by_term = _query_keys_by_term(terms)
    all_keys = sorted({key for keys in keys_by_term.values() for key in keys})
    if not all_keys:
        return {}, status
    placeholders = ','.join('?' for _key in all_keys)
    try:
        connection = sqlite3.connect(os.path.abspath(index_path), timeout=5)
        rows = connection.execute(
            f'SELECT path, term FROM terms WHERE term IN ({placeholders})',
            all_keys,
        ).fetchall()
        connection.close()
    except sqlite3.DatabaseError:
        return {}, {**status, 'state': 'failed', 'last_error': '索引查询失败'}

    path_keys = {}
    for relative, key in rows:
        path_keys.setdefault(relative, set()).add(key)
    ranked = []
    for relative, matched_keys in path_keys.items():
        matched_terms = {
            term for term, required_keys in keys_by_term.items()
            if required_keys.issubset(matched_keys)
        }
        lowered_path = relative.lower()
        matched_terms.update(term for term in terms if str(term).lower() in lowered_path)
        if not matched_terms:
            continue
        score = len(matched_terms) * 100 + len(matched_keys)
        if '/common/' in '/' + lowered_path:
            score += 10
        if '/language/' in '/' + lowered_path:
            score -= 50
        ranked.append((score, relative, matched_terms))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    json_root = os.path.abspath(json_root)
    matches = {}
    for _score, relative, matched_terms in ranked[:max(1, int(limit))]:
        path = os.path.abspath(os.path.join(json_root, relative.replace('/', os.sep)))
        try:
            if os.path.commonpath((json_root, path)) != json_root or not os.path.isfile(path):
                continue
        except ValueError:
            continue
        matches[path] = set(matched_terms)
    return matches, status


def _set_runtime_status(**values):
    with _watcher_lock:
        _runtime_status.update(values)


def request_kongming_index_sync(reason='manual'):
    global _watcher_pending_reason
    with _watcher_lock:
        if _watcher_thread is None or not _watcher_thread.is_alive():
            return False
        _watcher_pending_reason = str(reason or 'manual')
        _runtime_status.update({
            'state': 'queued',
            'reason': _watcher_pending_reason,
            'percent': 0,
        })
    _watcher_event.set()
    return True


def start_kongming_index_watcher(
    json_root, index_path, on_updated=None, interval=KONGMING_INDEX_DEFAULT_INTERVAL
):
    global _watcher_thread, _watcher_config, _watcher_pending_reason
    json_root = os.path.abspath(json_root)
    index_path = os.path.abspath(index_path)
    with _watcher_lock:
        _watcher_config = {
            'json_root': json_root,
            'index_path': index_path,
            'on_updated': on_updated,
            'interval': max(10, int(interval)),
        }
        _watcher_pending_reason = 'startup'
        if _watcher_thread is not None and _watcher_thread.is_alive():
            _watcher_event.set()
            already_running = True
        else:
            already_running = False

        def worker():
            global _watcher_pending_reason
            while True:
                with _watcher_lock:
                    config = dict(_watcher_config)
                    reason = _watcher_pending_reason or 'periodic'
                    _watcher_pending_reason = ''
                _watcher_event.clear()
                base_status = get_kongming_index_status(config['index_path'])
                _set_runtime_status(
                    index_path=config['index_path'],
                    state='updating' if base_status.get('ready') else 'building',
                    ready=base_status.get('ready', False),
                    reason=reason,
                    percent=0,
                    last_error='',
                )

                def progress(values):
                    _set_runtime_status(**{
                        'index_path': config['index_path'],
                        'reason': reason,
                        **values,
                    })

                try:
                    result = sync_kongming_index(
                        config['json_root'],
                        config['index_path'],
                        progress=progress,
                    )
                    _set_runtime_status(**{
                        'index_path': config['index_path'],
                        'reason': reason,
                        **result,
                    })
                    callback = config.get('on_updated')
                    if callback:
                        callback(result)
                except Exception as exc:
                    _set_runtime_status(
                        index_path=config['index_path'],
                        state='failed',
                        reason=reason,
                        percent=100,
                        last_error=str(exc),
                    )
                _watcher_event.wait(config['interval'])

        if not already_running:
            _watcher_thread = threading.Thread(
                target=worker,
                name='kongming-index-watcher',
                daemon=True,
            )
            _watcher_thread.start()
    return get_kongming_index_status(index_path)
