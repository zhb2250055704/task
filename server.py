#!/usr/bin/env python3
"""
GM 命令管理工具 - 本地服务器
提供 GM 命令与分类的增、删、改、查 REST API
数据存储于 gm_commands.json / gm_categories.json
"""
import os
import sys
import io
import json
import time
import uuid
import hashlib
import secrets
import socket
import threading
import webbrowser
import zipfile
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

if os.name == 'nt':
    try:
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    except Exception:
        pass

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gm_server.log')
if sys.stdout is None:
    sys.stdout = open(LOG_FILE, 'a', encoding='utf-8', buffering=1)
elif sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr is None:
    sys.stderr = sys.stdout
elif sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(TOOL_DIR, 'gm_commands.json')
CATEGORY_FILE = os.path.join(TOOL_DIR, 'gm_categories.json')
SCRIPT_FILE = os.path.join(TOOL_DIR, 'gm_scripts.json')
FORMULA_FILE = os.path.join(TOOL_DIR, 'gm_formulas.json')
USER_FILE = os.path.join(TOOL_DIR, 'gm_users.json')
ITEM_FILE = os.path.join(TOOL_DIR, 'gm_items.json')

GIT_REPOS = {
    'client': {
        'label': '客户端',
        'path': r'C:\Users\TU\Documents\client',
    },
    'excel': {
        'label': '配置表',
        'path': r'C:\Users\TU\Documents\excel',
    },
}
GIT_TIMEOUT = 180

# item 源表（游戏配表项目内的 COA_Item.xlsx）
ITEM_XLSX = os.environ.get(
    'GM_ITEM_XLSX',
    r'C:\Users\TU\Documents\excel\csv\common\COA_Item.xlsx'
)
# 表头字段名所在行（第2行）与数据起始行（第11行），遵循项目 AGENTS.md 约定
ITEM_HEADER_ROW = 2
ITEM_DATA_START_ROW = 11

COMMAND_FIELDS = [
    'name', 'command', 'category', 'tags',
    'params', 'example', 'permission', 'description'
]

SCRIPT_FIELDS = [
    'name', 'content', 'category', 'tags', 'description'
]

FORMULA_FIELDS = [
    'name', 'expression', 'variables', 'category', 'description'
]

DEFAULT_CATEGORIES = ['活动', '资源', '武将', '南征北战']

ROLES = ['admin', 'user']
ROLE_LABELS = {'admin': '管理员', 'user': '普通用户'}
DEFAULT_ADMIN = {'username': 'admin', 'password': 'admin123', 'role': 'admin'}

_lock = threading.Lock()
_session_lock = threading.Lock()
_sessions = {}


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_data(items):
    tmp = DATA_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def load_scripts():
    if os.path.exists(SCRIPT_FILE):
        try:
            with open(SCRIPT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_scripts(items):
    tmp = SCRIPT_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SCRIPT_FILE)


def load_formulas():
    if os.path.exists(FORMULA_FILE):
        try:
            with open(FORMULA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_formulas(items):
    tmp = FORMULA_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, FORMULA_FILE)


# ---------- item 道具表（标准库解析 xlsx） ----------
_XL_NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def _col_to_index(ref):
    """从单元格引用（如 'B12'）取列字母，换算为 0 基列号。"""
    letters = ''.join(ch for ch in ref if ch.isalpha())
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - ord('A') + 1)
    return idx - 1


def _row_of_ref(ref):
    digits = ''.join(ch for ch in ref if ch.isdigit())
    return int(digits) if digits else 0


def parse_item_xlsx(path=ITEM_XLSX):
    """用标准库解析 COA_Item.xlsx，返回 (fields, rows)。
    fields: 字段名列表（第 ITEM_HEADER_ROW 行）
    rows: 从第 ITEM_DATA_START_ROW 行起的道具 dict 列表
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f'找不到 item 源表: {path}')

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        # 共享字符串表
        shared = []
        if 'xl/sharedStrings.xml' in names:
            sroot = ET.fromstring(zf.read('xl/sharedStrings.xml'))
            for si in sroot.findall(f'{_XL_NS}si'):
                texts = [t.text or '' for t in si.iter(f'{_XL_NS}t')]
                shared.append(''.join(texts))
        # 第一个工作表
        sheet_name = None
        for n in names:
            if n.startswith('xl/worksheets/sheet') and n.endswith('.xml'):
                sheet_name = n
                break
        if sheet_name is None:
            raise ValueError('xlsx 中找不到工作表')
        wroot = ET.fromstring(zf.read(sheet_name))

    sheet_data = wroot.find(f'{_XL_NS}sheetData')
    if sheet_data is None:
        return [], []

    # 解析成 {行号: {列号: 值}}
    grid = {}
    max_col = 0
    for row in sheet_data.findall(f'{_XL_NS}row'):
        r_attr = row.get('r')
        rnum = int(r_attr) if r_attr else 0
        for c in row.findall(f'{_XL_NS}c'):
            ref = c.get('r') or ''
            ctype = c.get('t')
            col = _col_to_index(ref) if ref else 0
            value = ''
            if ctype == 's':
                v = c.find(f'{_XL_NS}v')
                if v is not None and v.text is not None:
                    try:
                        value = shared[int(v.text)]
                    except (ValueError, IndexError):
                        value = ''
            elif ctype == 'inlineStr':
                isnode = c.find(f'{_XL_NS}is')
                if isnode is not None:
                    value = ''.join(t.text or '' for t in isnode.iter(f'{_XL_NS}t'))
            else:
                v = c.find(f'{_XL_NS}v')
                if v is not None and v.text is not None:
                    value = v.text
            grid.setdefault(rnum, {})[col] = value
            if col > max_col:
                max_col = col

    # 字段名
    header = grid.get(ITEM_HEADER_ROW, {})
    fields = []
    for col in range(max_col + 1):
        name = str(header.get(col, '')).strip()
        if not name:
            name = f'col{col + 1}'
        fields.append(name)

    rows = []
    for rnum in sorted(k for k in grid if k >= ITEM_DATA_START_ROW):
        rowmap = grid[rnum]
        # 跳过空行
        if not any(str(rowmap.get(c, '')).strip() for c in rowmap):
            continue
        rec = {}
        for col in range(max_col + 1):
            rec[fields[col]] = str(rowmap.get(col, ''))
        rows.append(rec)
    return fields, rows


def _col_label(idx):
    idx = int(idx)
    label = ''
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        label = chr(ord('A') + rem) + label
    return label or 'A'


def _xlsx_shared_strings(zf):
    shared = []
    if 'xl/sharedStrings.xml' not in zf.namelist():
        return shared
    root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
    for si in root.findall(f'{_XL_NS}si'):
        shared.append(''.join(t.text or '' for t in si.iter(f'{_XL_NS}t')))
    return shared


def _xlsx_sheet_paths(zf):
    names = set(zf.namelist())
    result = []
    if 'xl/workbook.xml' in names and 'xl/_rels/workbook.xml.rels' in names:
        workbook = ET.fromstring(zf.read('xl/workbook.xml'))
        rels = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
        rel_map = {}
        for rel in rels:
            rid = rel.get('Id')
            target = rel.get('Target') or ''
            if rid and target:
                if not target.startswith('/'):
                    target = 'xl/' + target.lstrip('/')
                else:
                    target = target.lstrip('/')
                rel_map[rid] = target.replace('\\', '/')
        for sheet in workbook.iter(f'{_XL_NS}sheet'):
            title = sheet.get('name') or ('Sheet' + str(len(result) + 1))
            rid = sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            path = rel_map.get(rid, '')
            if path in names:
                result.append((title, path))
    if result:
        return result
    for path in sorted(n for n in names if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')):
        result.append((os.path.basename(path).replace('.xml', ''), path))
    return result


def parse_xlsx_bytes(raw):
    if not raw:
        return []
    sheets = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        shared = _xlsx_shared_strings(zf)
        for title, path in _xlsx_sheet_paths(zf):
            root = ET.fromstring(zf.read(path))
            sheet_data = root.find(f'{_XL_NS}sheetData')
            cells = {}
            if sheet_data is not None:
                for row in sheet_data.findall(f'{_XL_NS}row'):
                    r_attr = row.get('r')
                    fallback_row = int(r_attr) if r_attr else 0
                    for cell in row.findall(f'{_XL_NS}c'):
                        ref = cell.get('r') or ''
                        rnum = _row_of_ref(ref) or fallback_row
                        cnum = _col_to_index(ref) + 1 if ref else 1
                        ctype = cell.get('t')
                        value = ''
                        if ctype == 's':
                            v = cell.find(f'{_XL_NS}v')
                            if v is not None and v.text is not None:
                                try:
                                    value = shared[int(v.text)]
                                except (ValueError, IndexError):
                                    value = ''
                        elif ctype == 'inlineStr':
                            inode = cell.find(f'{_XL_NS}is')
                            if inode is not None:
                                value = ''.join(t.text or '' for t in inode.iter(f'{_XL_NS}t'))
                        elif ctype == 'b':
                            v = cell.find(f'{_XL_NS}v')
                            value = 'TRUE' if v is not None and v.text == '1' else 'FALSE'
                        else:
                            v = cell.find(f'{_XL_NS}v')
                            if v is not None and v.text is not None:
                                value = v.text
                        if rnum and cnum and str(value) != '':
                            cells[(rnum, cnum)] = str(value)
            sheets.append({'name': title, 'cells': cells})
    return sheets


def run_git_command_bytes(repo, args, timeout=60):
    path = repo.get('path', '')
    if not os.path.isdir(path):
        return {'ok': False, 'code': -1, 'stdout': b'', 'stderr': b'', 'output': f'目录不存在: {path}'}
    env = os.environ.copy()
    env['GIT_TERMINAL_PROMPT'] = '0'
    try:
        proc = subprocess.run(
            [git_executable()] + list(args),
            cwd=path,
            capture_output=True,
            timeout=timeout,
            env=env,
            **git_subprocess_options(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {'ok': False, 'code': -1, 'stdout': b'', 'stderr': b'', 'output': str(e)}
    stderr = proc.stderr.decode('utf-8', errors='replace') if proc.stderr else ''
    return {'ok': proc.returncode == 0, 'code': proc.returncode, 'stdout': proc.stdout,
            'stderr': proc.stderr, 'output': stderr.strip()}


def parse_git_name_status_rows(output):
    rows = []
    for line in (output or '').splitlines():
        parts = line.split('\t')
        if not parts:
            continue
        status = parts[0]
        if status.startswith('R') and len(parts) >= 3:
            rows.append({'status': status, 'old_path': parts[1], 'path': parts[2]})
        elif len(parts) >= 2:
            rows.append({'status': status, 'old_path': parts[1], 'path': parts[1]})
    return rows


def _xlsx_used_bounds(*cell_maps):
    max_row = 0
    max_col = 0
    for cells in cell_maps:
        for rnum, cnum in cells.keys():
            max_row = max(max_row, rnum)
            max_col = max(max_col, cnum)
    return max_row, max_col


def _xlsx_header_rows(before_cells, after_cells, max_col, max_header_rows=10):
    header_rows = []
    max_scan = min(max_header_rows, max((r for r, _ in set(before_cells.keys()) | set(after_cells.keys())), default=0))
    for rnum in range(1, max_scan + 1):
        values = []
        has_value = False
        for cnum in range(1, max_col + 1):
            value = after_cells.get((rnum, cnum), before_cells.get((rnum, cnum), ''))
            values.append(value)
            if str(value).strip():
                has_value = True
        if has_value:
            header_rows.append({'row': rnum, 'values': values})
    return header_rows


def _xlsx_column_headers(before_cells, after_cells, max_col, header_rows):
    columns = []
    for cnum in range(1, max_col + 1):
        parts = []
        for header in header_rows:
            values = header.get('values') or []
            value = values[cnum - 1] if cnum - 1 < len(values) else ''
            value = str(value or '').strip()
            if value and value not in parts:
                parts.append(value)
        columns.append({
            'index': cnum,
            'label': _col_label(cnum),
            'header': ' / '.join(parts),
            'headers': parts,
        })
    return columns


def compare_xlsx_sheets(before_sheets, after_sheets, max_rows=80, max_cols=120):
    before_map = {s['name']: s for s in before_sheets}
    after_map = {s['name']: s for s in after_sheets}
    names = list(dict.fromkeys(list(before_map.keys()) + list(after_map.keys())))
    results = []
    for name in names[:8]:
        before_cells = before_map.get(name, {}).get('cells', {})
        after_cells = after_map.get(name, {}).get('cells', {})
        coords = sorted(set(before_cells.keys()) | set(after_cells.keys()))
        changed = [coord for coord in coords if before_cells.get(coord, '') != after_cells.get(coord, '')]
        if not changed:
            continue
        changed_rows = sorted(set(r for r, _ in changed))
        changed_cols = sorted(set(c for _, c in changed))
        rows_to_show = changed_rows[:max_rows]
        _, max_used_col = _xlsx_used_bounds(before_cells, after_cells)
        all_cols = list(range(1, max_used_col + 1))
        cols_to_show = all_cols[:max_cols]
        header_rows = _xlsx_header_rows(before_cells, after_cells, max_used_col)
        column_headers = _xlsx_column_headers(before_cells, after_cells, max_used_col, header_rows)
        column_header_map = {col['index']: col for col in column_headers}
        changed_col_set = set(changed_cols)
        table_rows = []
        for rnum in rows_to_show:
            row_cells = []
            for cnum in cols_to_show:
                before = before_cells.get((rnum, cnum), '')
                after = after_cells.get((rnum, cnum), '')
                if before == after:
                    status = 'same'
                elif before == '':
                    status = 'added'
                elif after == '':
                    status = 'deleted'
                else:
                    status = 'changed'
                col_header = column_header_map.get(cnum, {})
                row_cells.append({'col': cnum, 'label': _col_label(cnum),
                                  'header': col_header.get('header', ''),
                                  'headers': col_header.get('headers', []),
                                  'before': before, 'after': after,
                                  'status': status, 'changed': cnum in changed_col_set})
            table_rows.append({'row': rnum, 'cells': row_cells})
        results.append({
            'name': name,
            'total_changes': len(changed),
            'shown_rows': len(rows_to_show),
            'shown_cols': len(cols_to_show),
            'total_cols': max_used_col,
            'changed_cols': [_col_label(c) for c in changed_cols],
            'truncated': len(changed_rows) > max_rows or max_used_col > max_cols,
            'headers': header_rows,
            'columns': [column_header_map.get(c, {'index': c, 'label': _col_label(c), 'header': '', 'headers': []}) for c in cols_to_show],
            'rows': table_rows,
        })
    return results


def git_show_file_bytes(repo, spec):
    return run_git_command_bytes(repo, ['show', spec], timeout=60)


def git_excel_diffs(repo_id, commit_hash):
    if repo_id != 'excel' or not safe_git_hash(commit_hash):
        return []
    repo = GIT_REPOS[repo_id]
    files = run_git_command(repo, ['diff-tree', '--no-commit-id', '--name-status', '-r', '--find-renames', str(commit_hash)], timeout=60)
    if not files.get('ok'):
        return []
    rows = parse_git_name_status_rows(files.get('stdout', ''))
    excel_rows = []
    for row in rows:
        path = row.get('path', '')
        base = os.path.basename(path)
        if base.startswith('~$'):
            continue
        if path.lower().endswith(('.xlsx', '.xlsm')):
            excel_rows.append(row)
    results = []
    for row in excel_rows[:4]:
        status = row.get('status', '')
        path = row.get('path', '')
        old_path = row.get('old_path') or path
        before_raw = b''
        after_raw = b''
        if not status.startswith('A'):
            before = git_show_file_bytes(repo, f'{commit_hash}^:{old_path}')
            before_raw = before.get('stdout', b'') if before.get('ok') else b''
        if not status.startswith('D'):
            after = git_show_file_bytes(repo, f'{commit_hash}:{path}')
            after_raw = after.get('stdout', b'') if after.get('ok') else b''
        try:
            before_sheets = parse_xlsx_bytes(before_raw) if before_raw else []
            after_sheets = parse_xlsx_bytes(after_raw) if after_raw else []
            sheets = compare_xlsx_sheets(before_sheets, after_sheets)
            results.append({'file': path, 'old_file': old_path, 'status': status,
                            'sheet_count': len(sheets), 'sheets': sheets})
        except Exception as e:
            results.append({'file': path, 'old_file': old_path, 'status': status,
                            'sheet_count': 0, 'sheets': [], 'error': str(e)})
    return results


def load_items():
    if os.path.exists(ITEM_FILE):
        try:
            with open(ITEM_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
    return {'fields': [], 'items': [], 'updated_at': '', 'source': ITEM_XLSX}


def save_items(data):
    tmp = ITEM_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ITEM_FILE)


def refresh_items():
    """重新读取 xlsx，生成 gm_items.json，返回写入的数据。"""
    fields, rows = parse_item_xlsx()
    data = {
        'fields': fields,
        'items': rows,
        'updated_at': now_str(),
        'source': ITEM_XLSX,
    }
    save_items(data)
    return data


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return salt, digest


def verify_password(password, salt, digest):
    return hash_password(password, salt)[1] == digest


def load_users():
    if os.path.exists(USER_FILE):
        try:
            with open(USER_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_users(users):
    tmp = USER_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USER_FILE)


def ensure_default_admin():
    users = load_users()
    if not users:
        salt, digest = hash_password(DEFAULT_ADMIN['password'])
        users = [{
            'id': uuid.uuid4().hex[:12],
            'username': DEFAULT_ADMIN['username'],
            'role': DEFAULT_ADMIN['role'],
            'salt': salt,
            'password': digest,
            'create_time': now_str(),
        }]
        save_users(users)
        print(f'[INIT] 已创建默认管理员账号: {DEFAULT_ADMIN["username"]} / {DEFAULT_ADMIN["password"]}')


def public_user(u):
    return {
        'id': u.get('id'),
        'username': u.get('username'),
        'role': u.get('role'),
        'role_label': ROLE_LABELS.get(u.get('role'), u.get('role')),
        'create_time': u.get('create_time', ''),
    }


def create_session(user):
    token = secrets.token_urlsafe(24)
    with _session_lock:
        _sessions[token] = {
            'id': user['id'],
            'username': user['username'],
            'role': user['role'],
            'login_time': time.time(),
        }
    return token


def get_session(token):
    if not token:
        return None
    with _session_lock:
        return _sessions.get(token)


def drop_session(token):
    with _session_lock:
        _sessions.pop(token, None)


def load_categories():
    if os.path.exists(CATEGORY_FILE):
        try:
            with open(CATEGORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [str(c).strip() for c in data if str(c).strip()]
        except (json.JSONDecodeError, OSError):
            pass
    return list(DEFAULT_CATEGORIES)


def save_categories(cats):
    tmp = CATEGORY_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cats, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CATEGORY_FILE)


def now_str():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ''


def normalize(item):
    result = {'id': item.get('id') or uuid.uuid4().hex[:12]}
    for field in COMMAND_FIELDS:
        result[field] = item.get(field, '')
    if not isinstance(result['tags'], list):
        result['tags'] = [t.strip() for t in str(result['tags']).split(',') if t.strip()]
    result['create_time'] = item.get('create_time') or now_str()
    result['update_time'] = item.get('update_time') or result['create_time']
    return result


def matches(item, keyword):
    if not keyword:
        return True
    kw = keyword.lower()
    fields = [item.get('name', ''), item.get('command', ''),
              item.get('category', ''), item.get('description', ''),
              item.get('params', ''), item.get('example', ''),
              item.get('permission', '')]
    fields.append(' '.join(item.get('tags', [])))
    return any(kw in str(v).lower() for v in fields)


def normalize_script(item):
    result = {'id': item.get('id') or uuid.uuid4().hex[:12]}
    for field in SCRIPT_FIELDS:
        result[field] = item.get(field, '')
    if not isinstance(result['tags'], list):
        result['tags'] = [t.strip() for t in str(result['tags']).split(',') if t.strip()]
    result['create_time'] = item.get('create_time') or now_str()
    result['update_time'] = item.get('update_time') or result['create_time']
    return result


def matches_script(item, keyword):
    if not keyword:
        return True
    kw = keyword.lower()
    fields = [item.get('name', ''), item.get('content', ''),
              item.get('category', ''), item.get('description', '')]
    fields.append(' '.join(item.get('tags', [])))
    return any(kw in str(v).lower() for v in fields)


def normalize_formula(item):
    result = {'id': item.get('id') or uuid.uuid4().hex[:12]}
    for field in FORMULA_FIELDS:
        result[field] = item.get(field, '')
    if not isinstance(result['variables'], list):
        result['variables'] = [v.strip() for v in str(result['variables']).split(',') if v.strip()]
    result['create_time'] = item.get('create_time') or now_str()
    result['update_time'] = item.get('update_time') or result['create_time']
    return result


def matches_formula(item, keyword):
    if not keyword:
        return True
    kw = keyword.lower()
    fields = [item.get('name', ''), item.get('expression', ''),
              item.get('category', ''), item.get('description', '')]
    fields.append(' '.join(item.get('variables', [])))
    return any(kw in str(v).lower() for v in fields)


def git_executable():
    return os.environ.get('GM_GIT_EXE') or shutil.which('git') or 'git'


def git_subprocess_options():
    if os.name != 'nt':
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        'creationflags': subprocess.CREATE_NO_WINDOW,
        'startupinfo': startupinfo,
    }


def run_git_command(repo, args, timeout=60):
    path = repo.get('path', '')
    if not os.path.isdir(path):
        return {'ok': False, 'code': -1, 'stdout': '', 'stderr': '',
                'output': f'目录不存在: {path}'}
    if not os.path.isdir(os.path.join(path, '.git')):
        return {'ok': False, 'code': -1, 'stdout': '', 'stderr': '',
                'output': f'不是 Git 仓库: {path}'}

    env = os.environ.copy()
    env['GIT_TERMINAL_PROMPT'] = '0'
    try:
        proc = subprocess.run(
            [git_executable()] + list(args),
            cwd=path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            env=env,
            **git_subprocess_options(),
        )
    except FileNotFoundError:
        return {'ok': False, 'code': -1, 'stdout': '', 'stderr': '',
                'output': '找不到 git 命令，请安装 Git 或设置 GM_GIT_EXE。'}
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ''
        stderr = e.stderr or ''
        if isinstance(stdout, bytes):
            stdout = stdout.decode('utf-8', errors='replace')
        if isinstance(stderr, bytes):
            stderr = stderr.decode('utf-8', errors='replace')
        return {'ok': False, 'code': -1, 'stdout': stdout, 'stderr': stderr,
                'output': (stdout + '\n' + stderr + '\n执行超时').strip()}

    output = (proc.stdout + ('\n' if proc.stdout and proc.stderr else '') + proc.stderr).strip()
    return {'ok': proc.returncode == 0, 'code': proc.returncode,
            'stdout': proc.stdout, 'stderr': proc.stderr, 'output': output}


def git_tracked_changes(repo):
    worktree = run_git_command(repo, ['diff', '--quiet'], timeout=30)
    staged = run_git_command(repo, ['diff', '--cached', '--quiet'], timeout=30)
    for item in (worktree, staged):
        if item.get('code') not in (0, 1):
            return {'ok': False, 'changed': False, 'output': item.get('output', '检查本地改动失败')}
    return {'ok': True, 'changed': worktree.get('code') == 1 or staged.get('code') == 1, 'output': ''}


def git_changed_paths(repo):
    paths = []
    for args in (['diff', '--name-only'], ['diff', '--cached', '--name-only']):
        result = run_git_command(repo, args, timeout=30)
        if not result.get('ok'):
            return {'ok': False, 'paths': [], 'output': result.get('output', '读取本地改动文件失败')}
        for line in result.get('stdout', '').splitlines():
            path = line.strip()
            if path and path not in paths:
                paths.append(path)
    return {'ok': True, 'paths': paths, 'output': ''}


def git_tool_repo_prefix(repo):
    try:
        repo_path = os.path.abspath(repo.get('path', ''))
        tool_path = os.path.abspath(TOOL_DIR)
        if os.path.commonpath([repo_path, tool_path]) != repo_path:
            return ''
        return os.path.relpath(tool_path, repo_path).replace(os.sep, '/') + '/'
    except ValueError:
        return ''


def git_filter_stash_paths(repo, paths):
    prefix = git_tool_repo_prefix(repo)
    filtered = []
    for path in paths:
        clean = str(path or '').strip().replace('\\', '/')
        if not clean:
            continue
        if prefix and (clean == prefix.rstrip('/') or clean.startswith(prefix)):
            continue
        if clean not in filtered:
            filtered.append(clean)
    return filtered


def git_office_lock_files(repo):
    root = repo.get('path', '')
    if not os.path.isdir(root):
        return []
    locks = []
    skip_prefix = git_tool_repo_prefix(repo)
    for dirpath, dirnames, filenames in os.walk(root):
        if '.git' in dirnames:
            dirnames.remove('.git')
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, '/')
        rel_prefix = '' if rel_dir == '.' else rel_dir + '/'
        if skip_prefix and (rel_prefix == skip_prefix or rel_prefix.startswith(skip_prefix)):
            dirnames[:] = []
            continue
        for name in filenames:
            lower = name.lower()
            if not name.startswith('~$') or not lower.endswith(('.xls', '.xlsx', '.xlsm')):
                continue
            rel = (rel_prefix + name).replace('\\', '/')
            locks.append(rel)
    return locks[:20]


def git_office_lock_message(paths):
    if not paths:
        return ''
    body = '\n'.join(' - ' + path for path in paths)
    return '检测到表格文件正在被 Excel/WPS 占用，请关闭这些表格后再拉取：\n' + body


def git_stash_paths(repo, repo_id, paths, include_untracked=False, reason='local'):
    paths = git_filter_stash_paths(repo, paths)
    if not paths:
        return {'ok': True, 'skipped': True, 'output': '没有需要暂存的文件'}
    message = f'gm-tool-before-pull-{repo_id}-{reason}-{time.strftime("%Y%m%d-%H%M%S")}'
    args = ['stash', 'push', '-m', message]
    if include_untracked:
        args.append('--include-untracked')
    args.append('--')
    args.extend(paths)
    result = run_git_command(repo, args, timeout=GIT_TIMEOUT)
    result['message'] = message
    result['paths'] = paths
    return result


def git_stash_before_pull(repo, repo_id):
    tracked = git_tracked_changes(repo)
    if not tracked.get('ok'):
        return tracked
    if not tracked.get('changed'):
        return {'ok': True, 'skipped': True, 'output': '没有需要暂存的已跟踪本地改动'}
    changed = git_changed_paths(repo)
    if not changed.get('ok'):
        return changed
    return git_stash_paths(repo, repo_id, changed.get('paths', []), reason='tracked')


def git_parse_overwrite_paths(output):
    paths = []
    capture = False
    for line in str(output or '').splitlines():
        text = line.rstrip()
        if 'would be overwritten by merge' in text:
            capture = True
            continue
        if capture:
            if text.startswith('\t') or text.startswith('    '):
                path = text.strip()
                if path and path not in paths:
                    paths.append(path)
                continue
            if text.startswith('Please ') or text.startswith('Aborting'):
                break
    return paths


def git_pull_failure_hint(output):
    text = str(output or '')
    m = re.search(r"unable to unlink old '([^']+)': Invalid argument", text)
    if m:
        return '文件被占用，Git 无法覆盖：' + m.group(1) + '。请关闭 Excel/WPS 或其他正在打开该文件的程序后重试。'
    if 'Your local changes to the following files would be overwritten by merge' in text:
        return '本地改动会被远端覆盖，工具会尝试自动暂存后重试；如果仍失败，请检查这些文件是否被其他程序占用。'
    if 'untracked working tree files would be overwritten by merge' in text:
        return '未跟踪文件会被远端覆盖，工具会尝试自动暂存阻塞文件后重试。'
    return ''



def parse_git_commit_lines(output):
    commits = []
    for line in (output or '').splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split('\t', 3)
        if len(parts) == 4:
            h, author, when, subject = parts
        else:
            chunks = line.split(' ', 1)
            h = chunks[0]
            author = ''
            when = ''
            subject = chunks[1] if len(chunks) > 1 else ''
        commits.append({
            'hash': h,
            'author': author,
            'time': when,
            'subject': subject,
            'text': f'{h} {subject}'.strip(),
        })
    return commits


def parse_git_change_path(line):
    line = str(line or '').strip()
    if not line:
        return ''
    parts = line.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else line


def safe_git_hash(value):
    return bool(re.fullmatch(r'[0-9a-fA-F]{6,40}', str(value or '').strip()))


def git_commit_detail(repo_id, commit_hash):
    if repo_id not in GIT_REPOS or not safe_git_hash(commit_hash):
        return {'ok': False, 'msg': '参数错误'}
    repo = GIT_REPOS[repo_id]
    stat = run_git_command(repo, ['show', '--stat', '--summary', '--find-renames', '--format=fuller', str(commit_hash)], timeout=60)
    patch = run_git_command(repo, ['show', '--find-renames', '--format=', '--patch', '--stat', str(commit_hash)], timeout=60)
    excel_diffs = git_excel_diffs(repo_id, commit_hash)
    return {
        'ok': stat.get('ok') and patch.get('ok'),
        'repo': repo_id,
        'title': f'{repo["label"]} {commit_hash}',
        'summary': stat.get('output', ''),
        'diff': patch.get('output', ''),
        'excel_diffs': excel_diffs,
        'msg': stat.get('output', '') if not stat.get('ok') else patch.get('output', ''),
    }


def git_change_detail(repo_id, change_line):
    if repo_id not in GIT_REPOS:
        return {'ok': False, 'msg': '参数错误'}
    repo = GIT_REPOS[repo_id]
    rel = parse_git_change_path(change_line)
    args = ['diff', '--', rel] if rel else ['diff']
    diff = run_git_command(repo, args, timeout=60)
    if not diff.get('output') and rel:
        diff = run_git_command(repo, ['diff', '--cached', '--', rel], timeout=60)
    return {
        'ok': diff.get('ok'),
        'repo': repo_id,
        'title': f'{repo["label"]} 本地改动 {rel or ""}'.strip(),
        'summary': change_line,
        'diff': diff.get('output', '') or '没有可显示的 diff，可能是未跟踪文件或二进制文件。',
        'msg': diff.get('output', ''),
    }


def parse_git_name_status(output):
    files = []
    for line in (output or '').splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split('	')
        status = parts[0] if parts else ''
        path = ' -> '.join(parts[1:]) if len(parts) > 1 else line
        files.append({'status': status, 'path': path, 'text': f'{status} {path}'.strip()})
    return files


def enrich_git_commits(repo, commits):
    for commit in commits:
        h = commit.get('hash', '')
        if not safe_git_hash(h):
            commit['files'] = []
            commit['file_count'] = 0
            continue
        files = run_git_command(repo, ['show', '--name-status', '--format=', '--find-renames', h], timeout=30)
        parsed = parse_git_name_status(files.get('stdout', '') if files.get('ok') else '')
        commit['files'] = parsed
        commit['file_count'] = len(parsed)
    return commits


def git_repo_status(repo_id):
    repo = GIT_REPOS[repo_id]
    item = {'id': repo_id, 'label': repo['label'], 'path': repo['path']}

    # 先 fetch，确保远端提交列表基于最新远端引用；失败时仍展示本地状态。
    fetch = run_git_command(repo, ['fetch', '--prune'], timeout=GIT_TIMEOUT)
    status = run_git_command(repo, ['status', '-sb'], timeout=30)
    if not status.get('ok'):
        item.update({'ok': False, 'branch': '', 'commit': '', 'upstream': '',
                     'status_line': '', 'changes': [], 'dirty': False,
                     'remote_commits': [], 'remote_count': 0,
                     'local_commits': [], 'local_count': 0,
                     'recent_commits': [], 'recent_count': 0,
                     'fetch_ok': fetch.get('ok'), 'fetch_msg': fetch.get('output', ''),
                     'msg': status.get('output', '状态检查失败')})
        return item

    branch = run_git_command(repo, ['rev-parse', '--abbrev-ref', 'HEAD'], timeout=30)
    commit = run_git_command(repo, ['rev-parse', '--short', 'HEAD'], timeout=30)
    upstream = run_git_command(repo, ['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'], timeout=30)
    lines = [line for line in status.get('stdout', '').splitlines() if line.strip()]

    remote_commits = []
    local_commits = []
    recent = run_git_command(repo, ['log', '-n', '80', '--pretty=format:%h%x09%an%x09%ar%x09%s'], timeout=30)
    recent_commits = parse_git_commit_lines(recent.get('stdout', '')) if recent.get('ok') else []
    if upstream.get('ok'):
        remote = run_git_command(repo, ['log', '--pretty=format:%h%x09%an%x09%ar%x09%s', 'HEAD..@{u}'], timeout=30)
        local = run_git_command(repo, ['log', '--pretty=format:%h%x09%an%x09%ar%x09%s', '@{u}..HEAD'], timeout=30)
        if remote.get('ok'):
            remote_commits = parse_git_commit_lines(remote.get('stdout', ''))
        if local.get('ok'):
            local_commits = parse_git_commit_lines(local.get('stdout', ''))
    remote_commits = enrich_git_commits(repo, remote_commits)
    local_commits = enrich_git_commits(repo, local_commits)
    recent_commits = enrich_git_commits(repo, recent_commits)

    item.update({
        'ok': True,
        'branch': branch.get('stdout', '').strip() if branch.get('ok') else '',
        'commit': commit.get('stdout', '').strip() if commit.get('ok') else '',
        'upstream': upstream.get('stdout', '').strip() if upstream.get('ok') else '',
        'status_line': lines[0] if lines else '',
        'changes': lines[1:],
        'dirty': len(lines) > 1,
        'remote_commits': remote_commits,
        'remote_count': len(remote_commits),
        'local_commits': local_commits,
        'local_count': len(local_commits),
        'recent_commits': recent_commits,
        'recent_count': len(recent_commits),
        'fetch_ok': fetch.get('ok'),
        'fetch_msg': '' if fetch.get('ok') else fetch.get('output', ''),
        'msg': '',
    })
    return item


class GMHandler(SimpleHTTPRequestHandler):

    def translate_path(self, path):
        parsed = urlparse(path)
        clean = parsed.path
        if clean.startswith('/api/'):
            return ''
        rel = clean.lstrip('/') or 'index.html'
        return os.path.join(TOOL_DIR, rel)

    def _current_user(self):
        cookies = self.headers.get('Cookie', '')
        token = ''
        for part in cookies.split(';'):
            part = part.strip()
            if part.startswith('gm_token='):
                token = part[len('gm_token='):]
                break
        return get_session(token), token

    def _require_login(self):
        sess, _ = self._current_user()
        if not sess:
            self._send_json({'ok': False, 'msg': '未登录或登录已失效', 'code': 'unauthorized'}, status=401)
            return None
        return sess

    def _require_admin(self):
        sess = self._require_login()
        if sess is None:
            return None
        if sess.get('role') != 'admin':
            self._send_json({'ok': False, 'msg': '无权限，仅管理员可操作', 'code': 'forbidden'}, status=403)
            return None
        return sess

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == '/api/auth/me':
            self._auth_me()
            return
        if path.startswith('/api/'):
            if self._require_login() is None:
                return
            if path == '/api/users':
                if self._require_admin() is None:
                    return
                self._list_users()
            elif path == '/api/commands':
                self._list_commands(parse_qs(parsed.query))
            elif path.startswith('/api/commands/'):
                self._get_command(path.rsplit('/', 1)[-1])
            elif path == '/api/scripts':
                self._list_scripts(parse_qs(parsed.query))
            elif path.startswith('/api/scripts/'):
                self._get_script(path.rsplit('/', 1)[-1])
            elif path == '/api/formulas':
                self._list_formulas(parse_qs(parsed.query))
            elif path.startswith('/api/formulas/'):
                self._get_formula(path.rsplit('/', 1)[-1])
            elif path == '/api/items':
                self._list_items(parse_qs(parsed.query))
            elif path == '/api/items/refresh':
                if self._require_admin() is None:
                    return
                self._refresh_items()
            elif path == '/api/git/repos':
                if self._require_admin() is None:
                    return
                self._list_git_repos()
            elif path == '/api/git/detail':
                if self._require_admin() is None:
                    return
                self._git_detail(parse_qs(parsed.query))
            elif path == '/api/categories':
                self._list_categories()
            else:
                self.send_error(404)
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == '/api/auth/login':
            self._login()
            return
        if path == '/api/auth/logout':
            self._logout()
            return
        if path == '/api/users':
            if self._require_admin() is None:
                return
            self._create_user()
            return
        if self._require_admin() is None:
            return
        if path == '/api/commands':
            self._create_command()
        elif path == '/api/scripts':
            self._create_script()
        elif path == '/api/formulas':
            self._create_formula()
        elif path == '/api/categories':
            self._create_category()
        elif path == '/api/git/pull':
            self._git_pull()
        else:
            self.send_error(404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == '/api/auth/password':
            if self._require_login() is None:
                return
            self._change_password()
            return
        if path.startswith('/api/users/'):
            if self._require_admin() is None:
                return
            self._update_user(path.rsplit('/', 1)[-1])
            return
        if self._require_admin() is None:
            return
        if path == '/api/categories':
            self._rename_category()
        elif path.startswith('/api/commands/'):
            self._update_command(path.rsplit('/', 1)[-1])
        elif path.startswith('/api/scripts/'):
            self._update_script(path.rsplit('/', 1)[-1])
        elif path.startswith('/api/formulas/'):
            self._update_formula(path.rsplit('/', 1)[-1])
        else:
            self.send_error(404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith('/api/users/'):
            if self._require_admin() is None:
                return
            self._delete_user(path.rsplit('/', 1)[-1])
            return
        if self._require_admin() is None:
            return
        if path == '/api/categories':
            self._delete_category(parse_qs(parsed.query))
        elif path.startswith('/api/commands/'):
            self._delete_command(path.rsplit('/', 1)[-1])
        elif path.startswith('/api/scripts/'):
            self._delete_script(path.rsplit('/', 1)[-1])
        elif path.startswith('/api/formulas/'):
            self._delete_formula(path.rsplit('/', 1)[-1])
        else:
            self.send_error(404)

    # ---------- 认证 ----------
    def _login(self):
        data = self._read_json()
        if data is None:
            return
        username = str(data.get('username', '')).strip()
        password = str(data.get('password', ''))
        with _lock:
            users = load_users()
        target = next((u for u in users if u.get('username') == username), None)
        if not target or not verify_password(password, target.get('salt', ''), target.get('password', '')):
            self._send_json({'ok': False, 'msg': '用户名或密码错误'}, status=401)
            return
        token = create_session(target)
        body = json.dumps({'ok': True, 'user': public_user(target)}, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Set-Cookie', f'gm_token={token}; Path=/; HttpOnly; SameSite=Lax')
        self.end_headers()
        self.wfile.write(body)
        print(f'[LOGIN] {username}')

    def _logout(self):
        _, token = self._current_user()
        drop_session(token)
        body = json.dumps({'ok': True}, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Set-Cookie', 'gm_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax')
        self.end_headers()
        self.wfile.write(body)

    def _auth_me(self):
        sess, _ = self._current_user()
        if not sess:
            self._send_json({'ok': True, 'logged_in': False})
            return
        self._send_json({'ok': True, 'logged_in': True, 'user': {
            'id': sess['id'], 'username': sess['username'],
            'role': sess['role'], 'role_label': ROLE_LABELS.get(sess['role'], sess['role']),
        }})

    def _change_password(self):
        data = self._read_json()
        if data is None:
            return
        sess, _ = self._current_user()
        old = str(data.get('old_password', ''))
        new = str(data.get('new_password', ''))
        if not new.strip():
            self._send_json({'ok': False, 'msg': '新密码不能为空'}, status=400)
            return
        with _lock:
            users = load_users()
            target = next((u for u in users if u.get('id') == sess['id']), None)
            if not target:
                self._send_json({'ok': False, 'msg': '用户不存在'}, status=404)
                return
            if not verify_password(old, target.get('salt', ''), target.get('password', '')):
                self._send_json({'ok': False, 'msg': '原密码错误'}, status=400)
                return
            salt, digest = hash_password(new)
            target['salt'] = salt
            target['password'] = digest
            save_users(users)
        print(f'[PASSWD] {sess["username"]}')
        self._send_json({'ok': True})

    # ---------- 用户管理 ----------
    def _list_users(self):
        with _lock:
            users = load_users()
        self._send_json({'ok': True, 'items': [public_user(u) for u in users],
                         'roles': [{'value': r, 'label': ROLE_LABELS[r]} for r in ROLES]})

    def _create_user(self):
        data = self._read_json()
        if data is None:
            return
        username = str(data.get('username', '')).strip()
        password = str(data.get('password', ''))
        role = str(data.get('role', 'user')).strip()
        if not username or not password:
            self._send_json({'ok': False, 'msg': '用户名和密码不能为空'}, status=400)
            return
        if role not in ROLES:
            role = 'user'
        with _lock:
            users = load_users()
            if any(u.get('username') == username for u in users):
                self._send_json({'ok': False, 'msg': '用户名已存在'}, status=400)
                return
            salt, digest = hash_password(password)
            user = {
                'id': uuid.uuid4().hex[:12],
                'username': username,
                'role': role,
                'salt': salt,
                'password': digest,
                'create_time': now_str(),
            }
            users.append(user)
            save_users(users)
        print(f'[USER+] {username} ({role})')
        self._send_json({'ok': True, 'item': public_user(user)})

    def _update_user(self, uid):
        data = self._read_json()
        if data is None:
            return
        sess, _ = self._current_user()
        with _lock:
            users = load_users()
            target = next((u for u in users if u.get('id') == uid), None)
            if not target:
                self._send_json({'ok': False, 'msg': '用户不存在'}, status=404)
                return
            new_role = data.get('role')
            if new_role is not None:
                new_role = str(new_role).strip()
                if new_role not in ROLES:
                    self._send_json({'ok': False, 'msg': '无效的角色'}, status=400)
                    return
                if target['id'] == sess['id'] and new_role != 'admin':
                    admins = [u for u in users if u.get('role') == 'admin']
                    if len(admins) <= 1:
                        self._send_json({'ok': False, 'msg': '不能降级唯一的管理员'}, status=400)
                        return
                target['role'] = new_role
            new_pwd = data.get('password')
            if new_pwd:
                salt, digest = hash_password(str(new_pwd))
                target['salt'] = salt
                target['password'] = digest
            save_users(users)
        print(f'[USER~] {target["username"]}')
        self._send_json({'ok': True, 'item': public_user(target)})

    def _delete_user(self, uid):
        sess, _ = self._current_user()
        with _lock:
            users = load_users()
            target = next((u for u in users if u.get('id') == uid), None)
            if not target:
                self._send_json({'ok': False, 'msg': '用户不存在'}, status=404)
                return
            if target['id'] == sess['id']:
                self._send_json({'ok': False, 'msg': '不能删除当前登录的账号'}, status=400)
                return
            if target.get('role') == 'admin':
                admins = [u for u in users if u.get('role') == 'admin']
                if len(admins) <= 1:
                    self._send_json({'ok': False, 'msg': '不能删除唯一的管理员'}, status=400)
                    return
            users = [u for u in users if u.get('id') != uid]
            save_users(users)
        print(f'[USER-] {target["username"]}')
        self._send_json({'ok': True})

    # ---------- 命令 ----------
    def _list_commands(self, params):
        keyword = params.get('q', [''])[0]
        category = params.get('category', [''])[0]
        with _lock:
            items = load_data()
        result = [it for it in items
                  if matches(it, keyword) and (not category or it.get('category') == category)]
        self._send_json({'ok': True, 'total': len(result), 'items': result})

    def _get_command(self, cid):
        with _lock:
            items = load_data()
        for it in items:
            if it.get('id') == cid:
                self._send_json({'ok': True, 'item': it})
                return
        self._send_json({'ok': False, 'msg': '命令不存在'}, status=404)

    def _create_command(self):
        data = self._read_json()
        if data is None:
            return
        if not str(data.get('name', '')).strip() or not str(data.get('command', '')).strip():
            self._send_json({'ok': False, 'msg': '命令名和命令内容不能为空'}, status=400)
            return
        item = normalize(data)
        with _lock:
            items = load_data()
            items.append(item)
            save_data(items)
        print(f'[CREATE] {item["id"]} {item["name"]}')
        self._send_json({'ok': True, 'item': item})

    def _update_command(self, cid):
        data = self._read_json()
        if data is None:
            return
        with _lock:
            items = load_data()
            for idx, it in enumerate(items):
                if it.get('id') == cid:
                    merged = dict(it)
                    for field in COMMAND_FIELDS:
                        if field in data:
                            merged[field] = data[field]
                    merged = normalize(merged)
                    merged['id'] = cid
                    merged['create_time'] = it.get('create_time') or now_str()
                    merged['update_time'] = now_str()
                    items[idx] = merged
                    save_data(items)
                    print(f'[UPDATE] {cid} {merged["name"]}')
                    self._send_json({'ok': True, 'item': merged})
                    return
        self._send_json({'ok': False, 'msg': '命令不存在'}, status=404)

    def _delete_command(self, cid):
        with _lock:
            items = load_data()
            new_items = [it for it in items if it.get('id') != cid]
            if len(new_items) == len(items):
                self._send_json({'ok': False, 'msg': '命令不存在'}, status=404)
                return
            save_data(new_items)
        print(f'[DELETE] {cid}')
        self._send_json({'ok': True})

    # ---------- 脚本 ----------
    def _list_scripts(self, params):
        keyword = params.get('q', [''])[0]
        category = params.get('category', [''])[0]
        with _lock:
            items = load_scripts()
        result = [it for it in items
                  if matches_script(it, keyword) and (not category or it.get('category') == category)]
        self._send_json({'ok': True, 'total': len(result), 'items': result})

    def _get_script(self, sid):
        with _lock:
            items = load_scripts()
        for it in items:
            if it.get('id') == sid:
                self._send_json({'ok': True, 'item': it})
                return
        self._send_json({'ok': False, 'msg': '脚本不存在'}, status=404)

    def _create_script(self):
        data = self._read_json()
        if data is None:
            return
        if not str(data.get('name', '')).strip() or not str(data.get('content', '')).strip():
            self._send_json({'ok': False, 'msg': '脚本名和脚本内容不能为空'}, status=400)
            return
        item = normalize_script(data)
        with _lock:
            items = load_scripts()
            items.append(item)
            save_scripts(items)
        print(f'[SCRIPT+] {item["id"]} {item["name"]}')
        self._send_json({'ok': True, 'item': item})

    def _update_script(self, sid):
        data = self._read_json()
        if data is None:
            return
        with _lock:
            items = load_scripts()
            for idx, it in enumerate(items):
                if it.get('id') == sid:
                    merged = dict(it)
                    for field in SCRIPT_FIELDS:
                        if field in data:
                            merged[field] = data[field]
                    merged = normalize_script(merged)
                    merged['id'] = sid
                    merged['create_time'] = it.get('create_time') or now_str()
                    merged['update_time'] = now_str()
                    items[idx] = merged
                    save_scripts(items)
                    print(f'[SCRIPT~] {sid} {merged["name"]}')
                    self._send_json({'ok': True, 'item': merged})
                    return
        self._send_json({'ok': False, 'msg': '脚本不存在'}, status=404)

    def _delete_script(self, sid):
        with _lock:
            items = load_scripts()
            new_items = [it for it in items if it.get('id') != sid]
            if len(new_items) == len(items):
                self._send_json({'ok': False, 'msg': '脚本不存在'}, status=404)
                return
            save_scripts(new_items)
        print(f'[SCRIPT-] {sid}')
        self._send_json({'ok': True})

    # ---------- item 道具表 ----------
    def _list_items(self, params):
        with _lock:
            data = load_items()
        keyword = params.get('q', [''])[0].strip().lower()
        items = data.get('items', [])
        if keyword:
            items = [it for it in items
                     if any(keyword in str(v).lower() for v in it.values())]
        self._send_json({'ok': True, 'fields': data.get('fields', []),
                         'total': len(items), 'items': items,
                         'updated_at': data.get('updated_at', ''),
                         'source': data.get('source', '')})

    def _refresh_items(self):
        try:
            with _lock:
                data = refresh_items()
        except (FileNotFoundError, ValueError) as e:
            self._send_json({'ok': False, 'msg': str(e)}, status=400)
            return
        print(f'[ITEM~] refreshed {len(data.get("items", []))} items')
        self._send_json({'ok': True, 'fields': data.get('fields', []),
                         'total': len(data.get('items', [])),
                         'updated_at': data.get('updated_at', ''),
                         'source': data.get('source', '')})

    # ---------- 计算公式 ----------
    def _list_formulas(self, params):
        keyword = params.get('q', [''])[0]
        category = params.get('category', [''])[0]
        with _lock:
            items = load_formulas()
        result = [it for it in items
                  if matches_formula(it, keyword) and (not category or it.get('category') == category)]
        self._send_json({'ok': True, 'total': len(result), 'items': result})

    def _get_formula(self, fid):
        with _lock:
            items = load_formulas()
        for it in items:
            if it.get('id') == fid:
                self._send_json({'ok': True, 'item': it})
                return
        self._send_json({'ok': False, 'msg': '公式不存在'}, status=404)

    def _create_formula(self):
        data = self._read_json()
        if data is None:
            return
        if not str(data.get('name', '')).strip() or not str(data.get('expression', '')).strip():
            self._send_json({'ok': False, 'msg': '公式名和表达式不能为空'}, status=400)
            return
        item = normalize_formula(data)
        with _lock:
            items = load_formulas()
            items.append(item)
            save_formulas(items)
        print(f'[FORMULA+] {item["id"]} {item["name"]}')
        self._send_json({'ok': True, 'item': item})

    def _update_formula(self, fid):
        data = self._read_json()
        if data is None:
            return
        with _lock:
            items = load_formulas()
            for idx, it in enumerate(items):
                if it.get('id') == fid:
                    merged = dict(it)
                    for field in FORMULA_FIELDS:
                        if field in data:
                            merged[field] = data[field]
                    merged = normalize_formula(merged)
                    merged['id'] = fid
                    merged['create_time'] = it.get('create_time') or now_str()
                    merged['update_time'] = now_str()
                    items[idx] = merged
                    save_formulas(items)
                    print(f'[FORMULA~] {fid} {merged["name"]}')
                    self._send_json({'ok': True, 'item': merged})
                    return
        self._send_json({'ok': False, 'msg': '公式不存在'}, status=404)

    def _delete_formula(self, fid):
        with _lock:
            items = load_formulas()
            new_items = [it for it in items if it.get('id') != fid]
            if len(new_items) == len(items):
                self._send_json({'ok': False, 'msg': '公式不存在'}, status=404)
                return
            save_formulas(new_items)
        print(f'[FORMULA-] {fid}')
        self._send_json({'ok': True})

    # ---------- 分类 ----------
    def _list_categories(self):
        with _lock:
            cats = load_categories()
        self._send_json({'ok': True, 'categories': cats})

    def _create_category(self):
        data = self._read_json()
        if data is None:
            return
        name = str(data.get('name', '')).strip()
        if not name:
            self._send_json({'ok': False, 'msg': '分类名不能为空'}, status=400)
            return
        with _lock:
            cats = load_categories()
            if name in cats:
                self._send_json({'ok': False, 'msg': '分类已存在'}, status=400)
                return
            cats.append(name)
            save_categories(cats)
        print(f'[CATEGORY+] {name}')
        self._send_json({'ok': True, 'categories': cats})

    def _rename_category(self):
        data = self._read_json()
        if data is None:
            return
        old = str(data.get('old', '')).strip()
        new = str(data.get('new', '')).strip()
        if not old or not new:
            self._send_json({'ok': False, 'msg': '分类名不能为空'}, status=400)
            return
        with _lock:
            cats = load_categories()
            if old not in cats:
                self._send_json({'ok': False, 'msg': '原分类不存在'}, status=404)
                return
            if new != old and new in cats:
                self._send_json({'ok': False, 'msg': '新分类已存在'}, status=400)
                return
            cats = [new if c == old else c for c in cats]
            save_categories(cats)
            items = load_data()
            changed = 0
            for it in items:
                if it.get('category') == old:
                    it['category'] = new
                    it['update_time'] = now_str()
                    changed += 1
            if changed:
                save_data(items)
        print(f'[CATEGORY~] {old} -> {new} (更新 {changed} 条命令)')
        self._send_json({'ok': True, 'categories': cats, 'changed': changed})

    def _delete_category(self, params):
        name = params.get('name', [''])[0].strip()
        if not name:
            self._send_json({'ok': False, 'msg': '分类名不能为空'}, status=400)
            return
        with _lock:
            cats = load_categories()
            if name not in cats:
                self._send_json({'ok': False, 'msg': '分类不存在'}, status=404)
                return
            cats = [c for c in cats if c != name]
            save_categories(cats)
        print(f'[CATEGORY-] {name}')
        self._send_json({'ok': True, 'categories': cats})

    # ---------- 工具方法 ----------

    # ---------- Git 拉取 ----------
    def _list_git_repos(self):
        self._send_json({'ok': True,
                         'items': [git_repo_status(rid) for rid in GIT_REPOS]})

    def _git_detail(self, params):
        repo_id = params.get('repo', [''])[0].strip()
        kind = params.get('kind', ['commit'])[0].strip()
        value = params.get('value', [''])[0]
        if kind == 'change':
            data = git_change_detail(repo_id, value)
        else:
            data = git_commit_detail(repo_id, value)
        status = 200 if data.get('ok') else 400
        self._send_json(data, status=status)

    def _git_pull(self):
        data = self._read_json()
        if data is None:
            return
        repo_id = str(data.get('repo', '')).strip()
        if repo_id == 'all':
            repo_ids = list(GIT_REPOS.keys())
        elif repo_id in GIT_REPOS:
            repo_ids = [repo_id]
        else:
            self._send_json({'ok': False, 'msg': '未知仓库'}, status=400)
            return

        results = []
        for rid in repo_ids:
            repo = GIT_REPOS[rid]
            before = git_repo_status(rid)
            if not before.get('ok'):
                results.append({'id': rid, 'label': repo['label'], 'path': repo['path'],
                                'ok': False, 'output': before.get('msg', '状态检查失败'),
                                'status': before})
                continue
            lock_files = git_office_lock_files(repo)
            if lock_files:
                results.append({'id': rid, 'label': repo['label'], 'path': repo['path'],
                                'ok': False, 'code': 'office_locked',
                                'output': git_office_lock_message(lock_files),
                                'lock_files': lock_files,
                                'status': before})
                print(f'[GIT] pull {rid}: office files locked')
                continue
            stashed = git_stash_before_pull(repo, rid)
            if not stashed.get('ok'):
                after = git_repo_status(rid)
                results.append({'id': rid, 'label': repo['label'], 'path': repo['path'],
                                'ok': False, 'code': stashed.get('code'),
                                'output': '暂存失败，未执行拉取\n' + (stashed.get('output') or ''),
                                'stash': stashed,
                                'status': after})
                print(f'[GIT] pull {rid}: stash failed')
                continue
            pulled = run_git_command(repo, ['pull', '--ff-only'], timeout=GIT_TIMEOUT)
            retry_stash = None
            retry_output = ''
            if not pulled.get('ok'):
                blocking_paths = git_parse_overwrite_paths(pulled.get('output', ''))
                if blocking_paths:
                    retry_stash = git_stash_paths(repo, rid, blocking_paths, include_untracked=True, reason='blocked')
                    retry_output = '阻塞文件暂存：' + (
                        retry_stash.get('output') or retry_stash.get('message', '已暂存阻塞文件')
                    )
                    if retry_stash.get('ok'):
                        pulled = run_git_command(repo, ['pull', '--ff-only'], timeout=GIT_TIMEOUT)
            after = git_repo_status(rid)
            output_parts = []
            stash_output = stashed.get('output') or ''
            if stashed.get('skipped'):
                output_parts.append('暂存：没有需要暂存的已跟踪本地改动')
            else:
                output_parts.append('暂存：' + (stash_output or stashed.get('message', '已暂存本地改动')))
            if retry_output:
                output_parts.append(retry_output)
            pull_output = pulled.get('output') or ('Already up to date.' if pulled.get('ok') else '')
            output_parts.append('拉取：' + pull_output)
            hint = git_pull_failure_hint(pull_output)
            if hint:
                output_parts.append('提示：' + hint)
            results.append({'id': rid, 'label': repo['label'], 'path': repo['path'],
                            'ok': pulled.get('ok'), 'code': pulled.get('code'),
                            'output': '\n'.join(output_parts),
                            'stash': stashed,
                            'retry_stash': retry_stash,
                            'status': after})
            print(f'[GIT] pull {rid}: {"ok" if pulled.get("ok") else "failed"}')
        self._send_json({'ok': all(it.get('ok') for it in results), 'items': results})

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length) if length else b''
        try:
            return json.loads(raw.decode('utf-8')) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json({'ok': False, 'msg': '请求体不是合法 JSON'}, status=400)
            return None

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if 'GET' not in str(args[0]) or args[1] != '200':
            super().log_message(fmt, *args)


if __name__ == '__main__':
    port = 9092
    open_browser = os.environ.get('GM_OPEN_BROWSER', '1').lower() not in ('0', 'false', 'no')
    for arg in sys.argv[1:]:
        if arg in ('--no-browser', '--headless'):
            open_browser = False
        else:
            port = int(arg)

    if not os.path.exists(DATA_FILE):
        save_data([])
    if not os.path.exists(SCRIPT_FILE):
        save_scripts([])
    if not os.path.exists(FORMULA_FILE):
        save_formulas([])
    if not os.path.exists(CATEGORY_FILE):
        save_categories(list(DEFAULT_CATEGORIES))
    if not os.path.exists(ITEM_FILE):
        try:
            d = refresh_items()
            print(f'  道具表: 已导入 {len(d.get("items", []))} 条')
        except Exception as e:
            save_items({'fields': [], 'items': [], 'updated_at': '', 'source': ITEM_XLSX})
            print(f'  道具表: 初始化失败({e})，可在工具内点“自动更新”重试')
    ensure_default_admin()

    print('==============================')
    print('  GM 命令管理工具 v1.0.0')
    print('==============================')
    print(f'  目录: {TOOL_DIR}')
    print(f'  数据: {DATA_FILE}')
    print(f'  本机访问: http://localhost:{port}')
    lan_ip = get_lan_ip()
    if lan_ip:
        print(f'  局域网访问(发给同事): http://{lan_ip}:{port}')
    print('  Ctrl+C 停止')
    print()

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(f'http://localhost:{port}')).start()

    httpd = ThreadingHTTPServer(('', port), GMHandler)
    httpd.daemon_threads = True
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n服务器已停止')
