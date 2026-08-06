import json
import os
import re
import shutil
import subprocess
import time
import unicodedata


KONGMING_MAX_SEARCH_TERMS = 8
KONGMING_MAX_TABLE_CANDIDATES = 12
KONGMING_MAX_CLIENT_CANDIDATES = 18
KONGMING_MAX_MATCHED_ROWS = 10
KONGMING_MAX_ROW_FIELDS = 22
KONGMING_MAX_CLIENT_SNIPPETS = 5
KONGMING_MAX_EVIDENCE_CHARS = 70000

_CJK_PATTERN = re.compile(r'[\u3400-\u9fff]{2,}')
_IDENTIFIER_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{2,}|\d{4,}')
_STOP_PHRASES = sorted({
    '帮我查找', '帮我查询', '帮我看看', '帮我', '请帮忙', '请问', '查找', '查询', '查阅', '查',
    '配置表', '客户端', '服务端', '前后端', '关键字段', '关联关系', '关联的', '关联',
    '活动', '玩法', '功能', '入口', '代码', '字段', '表格', '表里', '表中',
    '哪些', '哪个', '什么', '怎么', '如何', '最多', '列出', '相关的', '相关', '张', '最',
    '详细', '具体', '信息', '内容', '一下', '一下子', '这个', '那个', '以及',
    '是否', '可以', '需要', '对应', '里面', '中的', '里的', '和', '与', '的',
}, key=len, reverse=True)
_GENERIC_IDENTIFIERS = {
    'xlsx', 'json', 'excel', 'client', 'server', 'sheet', 'field', 'fields',
    'activity', 'config', 'configuration', 'entry', 'table', 'tables', 'find',
    'search', 'related', 'relation', 'game', 'code', 'detail', 'details',
}
_FIELD_HINTS = (
    'id', 'name', 'title', 'desc', 'type', 'activity', 'switch', 'reward', 'drop',
    'store', 'item', 'time', 'level', 'group', 'server', 'function', 'open', 'close',
)
_CLIENT_GLOBS = ('*.ts', '*.tsx', '*.js', '*.jsx', '*.lua', '*.py', '*.cs')


def extract_kongming_search_terms(text):
    normalized = unicodedata.normalize('NFKC', str(text or ''))
    terms = []

    for value in _IDENTIFIER_PATTERN.findall(normalized):
        clean = value.strip('._-')
        if len(clean) < 2 or clean.lower() in _GENERIC_IDENTIFIERS:
            continue
        if clean not in terms:
            terms.append(clean)

    for chunk in _CJK_PATTERN.findall(normalized):
        parts = [chunk]
        for phrase in _STOP_PHRASES:
            parts = [piece for part in parts for piece in part.split(phrase)]
        for part in parts:
            clean = part.strip()
            if len(clean) >= 2 and clean not in terms:
                terms.append(clean)

    return terms[:KONGMING_MAX_SEARCH_TERMS]


def _run_rg_files(root, terms, globs, limit, exclude_tool=False):
    rg_path = shutil.which('rg')
    if not rg_path or not os.path.isdir(root) or not terms:
        return {}
    args = [rg_path, '-l', '-F', '-i', '--no-messages']
    for pattern in globs:
        args.extend(['-g', pattern])
    args.extend(['-g', '!.git/**', '-g', '!node_modules/**', '-g', '!Library/**'])
    if exclude_tool:
        args.extend(['-g', '!tools/gm-command-tool/**'])
    for term in terms:
        args.extend(['-e', term])
    args.extend(['--', root])
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode not in (0, 1):
        return {}
    matches = {}
    for line in result.stdout.splitlines():
        path = os.path.abspath(line.strip())
        if not path or not os.path.isfile(path):
            continue
        path_lower = path.lower()
        path_terms = {term for term in terms if term.lower() in path_lower}
        matches[path] = path_terms or set(terms)
        if len(matches) >= limit:
            break
    return matches


def _truncate(value, limit=360):
    text = str(value or '').replace('\x00', '').strip()
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _matched_terms(value, terms):
    lowered = str(value or '').lower()
    return [term for term in terms if term.lower() in lowered]


def _row_fields(cells, headers, terms):
    ranked = []
    for column, raw_value in (cells or {}).items():
        value = _truncate(raw_value)
        if not value:
            continue
        label = _truncate(headers.get(column) or column, 80)
        lowered_label = label.lower()
        lowered_value = value.lower()
        score = 0
        if any(term.lower() in lowered_value for term in terms):
            score += 20
        if any(hint in lowered_label for hint in _FIELD_HINTS):
            score += 5
        if lowered_label in ('id', 'name', 'title'):
            score += 5
        ranked.append((score, str(column), label, value))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return {label: value for _score, _column, label, value in ranked[:KONGMING_MAX_ROW_FIELDS]}


def _summarize_json_table(path, matched_by, json_root):
    relative = os.path.relpath(path, json_root).replace('\\', '/')
    candidate = {
        'json_path': relative,
        'xlsx_path': relative[:-5] + '.xlsx' if relative.lower().endswith('.json') else relative,
        'matched_terms': sorted(matched_by),
        'sheets': [],
        'matched_rows': [],
        'score': 0,
    }
    if '/language/' in '/' + relative.lower():
        candidate['score'] = -20
        return candidate
    try:
        with open(path, 'r', encoding='utf-8') as source:
            data = json.load(source)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return candidate

    terms = list(matched_by)
    for sheet in data.get('sheets') or []:
        if not isinstance(sheet, dict):
            continue
        sheet_name = _truncate(sheet.get('name'), 100)
        if sheet_name:
            candidate['sheets'].append(sheet_name)
        rows = sheet.get('rows') if isinstance(sheet.get('rows'), list) else []
        headers = {}
        for row in rows[:12]:
            cells = row.get('cells') if isinstance(row, dict) else None
            if not isinstance(cells, dict):
                continue
            values = [str(value or '').strip().lower() for value in cells.values()]
            if str(cells.get('A') or '').strip().lower() == 'id' or 'id' in values:
                headers = {str(column): str(value or '').strip() for column, value in cells.items()}
                break

        for row_index, row in enumerate(rows, start=1):
            cells = row.get('cells') if isinstance(row, dict) else None
            if not isinstance(cells, dict):
                continue
            joined = '\n'.join(str(value or '') for value in cells.values())
            row_terms = _matched_terms(joined, terms)
            if not row_terms:
                continue
            candidate['matched_rows'].append({
                'sheet': sheet_name,
                'row': row_index,
                'matched_terms': row_terms,
                'fields': _row_fields(cells, headers, row_terms),
            })
            if len(candidate['matched_rows']) >= KONGMING_MAX_MATCHED_ROWS:
                break
        if len(candidate['matched_rows']) >= KONGMING_MAX_MATCHED_ROWS:
            break

    relative_lower = relative.lower()
    stem_lower = os.path.splitext(os.path.basename(relative_lower))[0]
    normalized_stem = re.sub(r'^(sg_)?coa_', '', stem_lower)
    filename_hits = sum(
        1 for term in terms
        if term.lower() in stem_lower or term.lower() in normalized_stem
    )
    sheet_hits = sum(
        1 for term in terms
        if any(term.lower() in sheet.lower() for sheet in candidate['sheets'])
    )
    candidate['score'] = (
        len(candidate['matched_rows']) * 8
        + len(candidate['matched_terms']) * 5
        + (8 if '/common/' in '/' + relative_lower else 0)
        + (3 if os.path.basename(relative_lower).startswith(('coa_', 'sg_coa_')) else 0)
        + filename_hits * 60
        + sheet_hits * 30
    )
    candidate['sheets'] = candidate['sheets'][:30]
    return candidate


def _client_search_terms(question_terms, table_candidates):
    terms = list(question_terms)
    top_score = int(table_candidates[0].get('score') or 0) if table_candidates else 0
    focused_tables = [
        table for table in table_candidates[:3]
        if int(table.get('score') or 0) >= max(1, int(top_score * .75))
    ]
    for table in focused_tables:
        stem = os.path.splitext(os.path.basename(table.get('xlsx_path') or ''))[0]
        for value in (stem, *(table.get('sheets') or [])[:8]):
            if value and len(value) >= 3 and value not in terms:
                terms.append(value)
            if len(terms) >= 20:
                return terms
    return terms


def _read_client_summary(path, matched_by, client_root):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as source:
            content = source.read(2 * 1024 * 1024)
    except OSError:
        content = ''
    content_lower = content.lower()
    actual_terms = {term for term in matched_by if term.lower() in content_lower}
    terms = sorted(actual_terms, key=len, reverse=True)
    snippets = []
    lines = content.splitlines()
    used_lines = set()
    for index, line in enumerate(lines):
        line_lower = line.lower()
        hit_terms = [term for term in terms if term.lower() in line_lower]
        if not hit_terms:
            continue
        start = max(0, index - 1)
        end = min(len(lines), index + 2)
        if any(number in used_lines for number in range(start, end)):
            continue
        snippet = '\n'.join(
            f'{number + 1}: {_truncate(lines[number], 520)}'
            for number in range(start, end)
        )
        snippets.append({'matched_terms': hit_terms, 'text': snippet})
        used_lines.update(range(start, end))
        if len(snippets) >= KONGMING_MAX_CLIENT_SNIPPETS:
            break
    relative = os.path.relpath(path, client_root).replace('\\', '/')
    score = len(actual_terms) * 8 + len(snippets) * 3
    lowered = relative.lower()
    if '/modules/logic/' in '/' + lowered:
        score += 8
    if '/creator/assets/scripts/' in '/' + lowered:
        score += 4
    return {
        'path': relative,
        'matched_terms': sorted(actual_terms),
        'snippets': snippets,
        'score': score,
    }


def _table_path_score(path, matched_by):
    lowered = path.replace('\\', '/').lower()
    stem = os.path.splitext(os.path.basename(lowered))[0]
    normalized_stem = re.sub(r'^(sg_)?coa_', '', stem)
    score = len(matched_by) * 4
    score += sum(
        60 for term in matched_by
        if term.lower() in stem or term.lower() in normalized_stem
    )
    if '/common/' in lowered:
        score += 10
    if '/language/' in lowered:
        score -= 100
    return score


def _client_path_score(path, matched_by):
    lowered = path.replace('\\', '/').lower()
    score = len(matched_by) * 5
    if '/modules/logic/' in lowered:
        score += 20
    if '/creator/assets/scripts/' in lowered:
        score += 8
    if any(term.lower() in lowered for term in matched_by):
        score += 12
    if '/tools/' in lowered or '/test/' in lowered or '/tests/' in lowered:
        score -= 20
    return score


def _fit_evidence(evidence):
    while True:
        serialized = json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))
        if len(serialized) <= KONGMING_MAX_EVIDENCE_CHARS:
            evidence['serialized_chars'] = len(serialized)
            return evidence
        clients = evidence.get('client_candidates') or []
        tables = evidence.get('table_candidates') or []
        if len(clients) > 6:
            clients.pop()
            continue
        if len(tables) > 4:
            tables.pop()
            continue
        for client in clients:
            snippets = client.get('snippets') or []
            if len(snippets) > 2:
                snippets.pop()
                break
        else:
            evidence['truncated'] = True
            evidence['serialized_chars'] = len(serialized)
            return evidence


def build_kongming_evidence(question, client_root, excel_root, json_root, context=''):
    started_at = time.time()
    terms = extract_kongming_search_terms('\n'.join((str(question or ''), str(context or ''))))
    if not terms:
        return {
            'keywords': [],
            'table_candidates': [],
            'client_candidates': [],
            'duration_ms': int((time.time() - started_at) * 1000),
            'message': '未能提取有效检索词，需要孔明进行定向分析。',
        }

    table_paths = _run_rg_files(json_root, terms, ('*.json',), 100)
    prioritized_table_paths = sorted(
        table_paths.items(),
        key=lambda item: (-_table_path_score(item[0], item[1]), item[0]),
    )[:24]
    tables = [
        _summarize_json_table(path, matched_by, json_root)
        for path, matched_by in prioritized_table_paths
    ]
    tables.sort(key=lambda item: (-item.get('score', 0), item.get('json_path', '')))
    tables = [item for item in tables if item.get('score', 0) >= 0][:KONGMING_MAX_TABLE_CANDIDATES]

    client_terms = _client_search_terms(terms, tables)
    client_paths = _run_rg_files(
        client_root,
        client_terms,
        _CLIENT_GLOBS,
        500,
        exclude_tool=True,
    )
    prioritized_client_paths = sorted(
        client_paths.items(),
        key=lambda item: (-_client_path_score(item[0], item[1]), item[0]),
    )[:50]
    clients = [
        _read_client_summary(path, matched_by, client_root)
        for path, matched_by in prioritized_client_paths
    ]
    clients.sort(key=lambda item: (-item.get('score', 0), item.get('path', '')))
    clients = clients[:KONGMING_MAX_CLIENT_CANDIDATES]

    evidence = {
        'version': 1,
        'keywords': terms,
        'table_candidates': tables,
        'client_candidates': clients,
        'duration_ms': int((time.time() - started_at) * 1000),
        'search_roots': {
            'client': os.path.abspath(client_root),
            'excel': os.path.abspath(excel_root),
            'json': os.path.abspath(json_root),
        },
    }
    return _fit_evidence(evidence)
