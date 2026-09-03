import copy
import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse


KONGMING_WORKFLOW_TYPE = 'ks_alliance_prepare'
KONGMING_REWARD_WORKFLOW_TYPE = 'ks_account_reward'
KONGMING_ACCOUNT_COMMAND_WORKFLOW_TYPE = 'ks_account_command'
KONGMING_COMMAND_ID = 'imp_setkingappointbegin'
KONGMING_SCRIPT_ID = '9358bdc65a4a'
KONGMING_REWARD_COMMAND_ID = 'imp_money'
KONGMING_MAX_SERVERS = 20
KONGMING_MAX_REWARD_TARGETS = 20
KONGMING_REWARD_CURRENCIES = {
    '元宝': {'id': '43', 'name': '元宝'},
    '钻石': {'id': '43', 'name': '元宝'},
    'diamond': {'id': '43', 'name': '元宝'},
}

_workflow_file_lock = threading.RLock()


def _now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _safe_component(value):
    value = ''.join(ch for ch in str(value or '') if ch.isalnum() or ch in ('-', '_'))
    return value[:80]


def _owner_dir(base_dir, owner_id):
    owner = _safe_component(owner_id)
    if not owner:
        raise ValueError('缺少任务用户')
    return os.path.join(base_dir, owner)


def _workflow_path(base_dir, owner_id, workflow_id):
    workflow = _safe_component(workflow_id)
    if not workflow:
        raise ValueError('缺少孔明任务编号')
    return os.path.join(_owner_dir(base_dir, owner_id), workflow + '.json')


def _unique_servers(values):
    result = []
    seen = set()
    for value in values:
        text = str(value or '').strip()
        if not text.isdigit():
            continue
        number = int(text)
        if number <= 0 or number > 20000:
            continue
        normalized = str(number)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _server_numbers(text):
    return _unique_servers(re.findall(r'(?<!\d)(\d{1,5})(?!\d)', str(text or '')))


def extract_ks_url(text):
    candidates = re.findall(r'https?://[^\s\]\[<>"\']+', str(text or ''), flags=re.IGNORECASE)
    for raw_url in candidates:
        url = raw_url.rstrip('。；;，,）)')
        parsed = urlparse(url)
        if parsed.hostname and parsed.hostname.lower() == 'zxty.tuyoo.com' and '/keystone/applications' in parsed.path:
            return url
    return ''


def extract_urls(text):
    urls = []
    seen = set()
    for raw_url in re.findall(r'https?://[^\s\]\[<>"\']+', str(text or ''), flags=re.IGNORECASE):
        url = raw_url.rstrip('。；;，,）)')
        if url and url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def parse_ks_application_url(text):
    url = extract_ks_url(text)
    if not url:
        raise ValueError('未识别到 KS 应用链接，请粘贴 /keystone/applications 页面地址')
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    app_id = str((query.get('id') or [''])[0]).strip()
    project_id = str((query.get('projectId') or query.get('project_id') or [''])[0]).strip()
    cluster_name = unquote(str((query.get('cluster_name') or [''])[0])).strip()
    if not app_id:
        raise ValueError('KS 应用链接缺少 id 参数')
    return {
        'url': url,
        'app_id': app_id,
        'project_id': project_id,
        'cluster_name': cluster_name,
    }


def parse_workflow_servers(text):
    source = str(text or '')
    account_servers = []
    account_patterns = (
        r'原服\s*[（(]([^）)]{1,500})[）)]',
        r'各个原服\s*[:：]?\s*([^。；;\n]{1,500})',
    )
    for pattern in account_patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            account_servers = _server_numbers(match.group(1))
            if account_servers:
                break

    script_servers = _unique_servers(
        re.findall(r'(?i)Server[\s_\-]*(\d{1,5})', source)
    )
    if not account_servers and script_servers:
        account_servers = list(script_servers)
    if not script_servers and account_servers and '备战活动脚本' in source:
        script_servers = list(account_servers)

    if not account_servers:
        raise ValueError('未识别到需要创建账号的原服编号')
    if not script_servers:
        raise ValueError('未识别到需要执行备战活动脚本的 Server_服务器编号')
    if len(account_servers) > KONGMING_MAX_SERVERS or len(script_servers) > KONGMING_MAX_SERVERS:
        raise ValueError(f'单次任务最多允许 {KONGMING_MAX_SERVERS} 个服务器')
    outside = [server_id for server_id in script_servers if server_id not in account_servers]
    if outside:
        raise ValueError('脚本目标不在创建账号的原服范围内：' + '、'.join(outside))
    return account_servers, script_servers


def is_kongming_alliance_workflow_request(text):
    source = str(text or '')
    required_markers = (
        '/keystone/applications',
        '盟主号',
        '成为天子',
        '备战活动脚本',
    )
    return all(marker in source for marker in required_markers)


def is_kongming_workflow_request(text):
    return (
        is_kongming_alliance_workflow_request(text)
        or is_kongming_reward_workflow_request(text)
        or is_kongming_account_command_workflow_request(text)
    )


def _normalize_url_for_match(value):
    try:
        parsed = urlparse(str(value or '').strip())
    except ValueError:
        return ''
    if not parsed.hostname:
        return ''
    path = (parsed.path or '').rstrip('/')
    return parsed.hostname.lower() + path


def _environment_match_values(environment):
    values = {
        str(environment.get('key') or '').strip(),
        str(environment.get('raw_id') or '').strip(),
        str(environment.get('app_id') or '').strip(),
        str(environment.get('name') or '').strip(),
        str(environment.get('app_name') or '').strip(),
        _normalize_url_for_match(environment.get('login_url')),
        _normalize_url_for_match(environment.get('environment_url')),
    }
    for link in environment.get('links') or []:
        values.add(_normalize_url_for_match(link))
    return {item for item in values if item}


def _find_environment_by_text(catalog, text):
    environments = catalog.get('environments') if isinstance(catalog, dict) else []
    source = str(text or '')
    urls = [_normalize_url_for_match(url) for url in extract_urls(source)]
    explicit_names = set(re.findall(r'test-[A-Za-z0-9][A-Za-z0-9_-]{2,80}', source, flags=re.IGNORECASE))
    ks_target = None
    if extract_ks_url(source):
        ks_target = parse_ks_application_url(source)
    for environment in environments or []:
        if not isinstance(environment, dict):
            continue
        values = _environment_match_values(environment)
        if ks_target and ks_target['app_id'] in values:
            return environment
        if any(url and url in values for url in urls):
            return environment
        if any(name in values for name in explicit_names):
            return environment
        for name in explicit_names:
            if any(name and value.startswith(name) for value in values):
                return environment
    return None


def find_kongming_environment(catalog, text):
    return _find_environment_by_text(catalog, text)


def _explicit_reward_accounts(text):
    accounts = []
    seen = set()
    for account_name in re.findall(r'\b\d+\.A\.account\.\d+\b', str(text or ''), flags=re.IGNORECASE):
        normalized = account_name.strip()
        identity = normalized.lower()
        if normalized and identity not in seen:
            accounts.append(normalized)
            seen.add(identity)
    return accounts


def _explicit_account_command_identifiers(text):
    """Extract long numeric identifiers only when they are used as account targets."""
    source = str(text or '')
    source_without_urls = re.sub(r'https?://[^\s\]\[<>"\']+', ' ', source, flags=re.IGNORECASE)
    identifiers = []
    seen = set()
    for match in re.finditer(r'(?<!\d)(\d{10,20})(?!\d)', source_without_urls):
        value = match.group(1)
        context = source_without_urls[max(0, match.start() - 48):min(len(source_without_urls), match.end() + 48)]
        trailing = source_without_urls[match.end():min(len(source_without_urls), match.end() + 16)]
        if re.match(r'\s*(?:元宝|金币|银币|数量|次|个|级|点)', trailing):
            continue
        if '账号' not in context and not re.search(r'\b(?:account|role|player|user)\s*(?:id)?\b', context, re.I):
            continue
        identity = value.lower()
        if identity not in seen:
            identifiers.append(value)
            seen.add(identity)
    return identifiers


def parse_reward_accounts(text):
    accounts = _explicit_reward_accounts(text)
    if not accounts:
        raise ValueError('未识别到账号名，请包含类似 101.A.account.721495 的 KS 账号')
    if len(accounts) > KONGMING_MAX_REWARD_TARGETS:
        raise ValueError(f'单次资源发放最多允许 {KONGMING_MAX_REWARD_TARGETS} 个账号')
    return accounts


def _parse_chinese_account_count(value):
    source = str(value or '').strip()
    if source.isdigit():
        return int(source)
    digits = {
        '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
        '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
    }
    if source == '十':
        return 10
    if '十' in source:
        left, right = source.split('十', 1)
        tens = digits.get(left, 1 if not left else 0)
        ones = digits.get(right, 0 if not right else -1)
        if tens > 0 and ones >= 0:
            return tens * 10 + ones
    return digits.get(source, 0)


def parse_reward_account_scope(text):
    source = str(text or '')
    account_names = _explicit_reward_accounts(source)
    count_match = re.search(
        r'(?<![\dA-Za-z])([0-9]{1,3}|[一二两三四五六七八九十]{1,3})\s*个\s*(?:KS\s*)?账号',
        source,
        flags=re.IGNORECASE,
    )
    expected_count = _parse_chinese_account_count(count_match.group(1)) if count_match else None
    if expected_count is not None:
        if expected_count <= 0:
            raise ValueError('账号数量必须大于 0')
        if expected_count > KONGMING_MAX_REWARD_TARGETS:
            raise ValueError(f'单次资源发放最多允许 {KONGMING_MAX_REWARD_TARGETS} 个账号')
    if account_names:
        if len(account_names) > KONGMING_MAX_REWARD_TARGETS:
            raise ValueError(f'单次资源发放最多允许 {KONGMING_MAX_REWARD_TARGETS} 个账号')
        if expected_count is not None and expected_count != len(account_names):
            raise ValueError(
                f'请求中写明 {expected_count} 个账号，但只识别到 {len(account_names)} 个明确账号名'
            )
        return {
            'mode': 'explicit',
            'account_names': account_names,
            'expected_count': expected_count,
        }
    all_markers = ('全部账号', '所有账号', '每个账号', '全体账号')
    if expected_count is not None or any(marker in source for marker in all_markers):
        return {
            'mode': 'all',
            'account_names': [],
            'expected_count': expected_count,
        }
    raise ValueError('未识别到发放账号范围，请写明账号名、账号数量或“全部账号”')


def parse_account_command_scope(text):
    """Parse explicit account names/IDs for non-resource GM commands."""
    source = str(text or '')
    account_names = _explicit_reward_accounts(source)
    account_identifiers = _explicit_account_command_identifiers(source)
    count_match = re.search(
        r'(?<![\dA-Za-z])([0-9]{1,3}|[一二两三四五六七八九十]{1,3})\s*个\s*(?:KS\s*)?账号',
        source,
        flags=re.IGNORECASE,
    )
    expected_count = _parse_chinese_account_count(count_match.group(1)) if count_match else None
    if expected_count is not None:
        if expected_count <= 0:
            raise ValueError('账号数量必须大于 0')
        if expected_count > KONGMING_MAX_REWARD_TARGETS:
            raise ValueError(f'单次账号操作最多允许 {KONGMING_MAX_REWARD_TARGETS} 个账号')

    explicit_targets = []
    seen = set()
    for value in [*account_names, *account_identifiers]:
        identity = value.lower()
        if identity not in seen:
            explicit_targets.append(value)
            seen.add(identity)
    if explicit_targets:
        if len(explicit_targets) > KONGMING_MAX_REWARD_TARGETS:
            raise ValueError(f'单次账号操作最多允许 {KONGMING_MAX_REWARD_TARGETS} 个账号')
        if expected_count is not None and expected_count != len(explicit_targets):
            raise ValueError(
                f'请求中写明 {expected_count} 个账号，但只识别到 {len(explicit_targets)} 个明确账号标识'
            )
        return {
            'mode': 'explicit',
            'account_names': account_names,
            'account_identifiers': account_identifiers,
            'expected_count': expected_count,
        }
    all_markers = ('全部账号', '所有账号', '每个账号', '全体账号')
    if expected_count is not None or any(marker in source for marker in all_markers):
        return {
            'mode': 'all',
            'account_names': [],
            'account_identifiers': [],
            'expected_count': expected_count,
        }
    raise ValueError('未识别到账号范围，请写明账号名、账号 ID、账号数量或“全部账号”')


def _parse_decimal_number(raw_number):
    raw = str(raw_number or '').strip().replace(',', '').replace('，', '')
    if not raw:
        raise ValueError('缺少数量')
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError('数量格式无法识别') from exc
    if value <= 0:
        raise ValueError('数量必须大于 0')
    if value > 10_000_000_000:
        raise ValueError('单次发放数量不能超过 100 亿')
    return value


def parse_reward_amount(text, currency_name='元宝'):
    source = str(text or '')
    currency_names = [currency_name]
    currency_names.extend(
        alias for alias, currency in KONGMING_REWARD_CURRENCIES.items()
        if currency.get('name') == currency_name
    )
    patterns = []
    for name in dict.fromkeys(item for item in currency_names if item):
        currency_pattern = re.escape(name)
        patterns.extend((
            rf'([0-9]+(?:[.,][0-9]+)?)\s*(亿|万|千|k|K|w|W)?\s*{currency_pattern}',
            rf'{currency_pattern}\s*([0-9]+(?:[.,][0-9]+)?)\s*(亿|万|千|k|K|w|W)?',
        ))
    for pattern in patterns:
        match = re.search(pattern, source)
        if not match:
            continue
        number = _parse_decimal_number(match.group(1))
        unit = str(match.group(2) or '').lower()
        multiplier = {
            '亿': 100_000_000,
            '万': 10_000,
            '千': 1_000,
            'k': 1_000,
            'w': 10_000,
        }.get(unit, 1)
        amount = int(number * multiplier)
        if amount <= 0:
            raise ValueError('数量必须大于 0')
        if amount > 10_000_000_000:
            raise ValueError('单次发放数量不能超过 100 亿')
        return amount
    raise ValueError(f'未识别到{currency_name}数量，请写成 1亿{currency_name} 或 {currency_name}100000000')


def parse_reward_currency(text):
    source = str(text or '').lower()
    for alias, currency in KONGMING_REWARD_CURRENCIES.items():
        if alias.lower() in source:
            return dict(currency)
    raise ValueError('当前仅支持识别元宝发放，请在需求中写明“元宝”')


def is_kongming_reward_workflow_request(text):
    source = str(text or '')
    has_environment = bool(
        extract_urls(source)
        or re.search(r'\btest-[A-Za-z0-9][A-Za-z0-9_-]{2,80}\b', source, flags=re.IGNORECASE)
        or re.search(r'(?:KS\s*)?环境\s*[:：]\s*[A-Za-z0-9][A-Za-z0-9_-]{2,80}', source, flags=re.IGNORECASE)
    )
    if not has_environment:
        return False
    if not any(alias in source.lower() for alias in KONGMING_REWARD_CURRENCIES):
        return False
    action_markers = ('发', '加', '添加', '补', '发放', '给')
    if not any(marker in source for marker in action_markers):
        return False
    try:
        parse_reward_account_scope(source)
    except ValueError:
        return False
    return True


def is_kongming_account_command_workflow_request(text):
    source = str(text or '')
    if not bool(
        extract_urls(source)
        or re.search(r'\btest-[A-Za-z0-9][A-Za-z0-9_-]{2,80}\b', source, flags=re.IGNORECASE)
        or re.search(r'(?:KS\s*)?环境\s*[:：]\s*[A-Za-z0-9][A-Za-z0-9_-]{2,80}', source, flags=re.IGNORECASE)
    ):
        return False
    try:
        parse_account_command_scope(source)
    except ValueError:
        return False
    action_markers = (
        '设置', '设为', '改成', '修改', '调整', '升到', '降低', '增加',
        '删除', '开启', '关闭', '解锁', '完成', '重置', '执行',
    )
    # A previous workflow may append a validated scope to a follow-up question.
    # Classify the user's intent before that synthetic context, otherwise the
    # word "执行" in the scope label can turn a read-only query into a workflow.
    intent_source = _command_intent_text(source)
    return '#' in intent_source or any(marker in intent_source for marker in action_markers)


def _normalized_command_text(value):
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '', str(value or '').lower())


def _canonical_command_question(value):
    source = str(value or '')
    replacements = (
        ('提升到', '设置为'),
        ('提高到', '设置为'),
        ('升级到', '设置为'),
        ('升到', '设置为'),
        ('调整到', '设置为'),
        ('调到', '设置为'),
        ('修改为', '设置为'),
        ('改成', '设置为'),
        ('设为', '设置为'),
        ('级别', '等级'),
    )
    for before, after in replacements:
        source = source.replace(before, after)
    return source


def _command_intent_text(value):
    source = str(value or '').split('【从最近任务卡继承的已校验执行范围】', 1)[0]
    source = re.sub(r'https?://[^\s\]\[<>"\']+', ' ', source, flags=re.IGNORECASE)
    source = re.sub(r'\b\d+\.A\.account\.\d+\b', ' ', source, flags=re.IGNORECASE)
    return source.strip()


def _command_bigrams(value):
    normalized = _normalized_command_text(value)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[index:index + 2] for index in range(len(normalized) - 1)}


def _command_match_score(question, command):
    source = _canonical_command_question(question)
    normalized_source = _normalized_command_text(source)
    template = str(command.get('command') or '').strip()
    name = str(command.get('name') or '').strip()
    description = str(command.get('description') or '').strip()
    category = str(command.get('category') or '').strip()
    if not template.startswith('#'):
        return 0

    score = 0
    if template.lower() in source.lower():
        score += 240
    normalized_name = _normalized_command_text(name)
    if normalized_name and normalized_name in normalized_source:
        score += 140
    normalized_description = _normalized_command_text(description)
    if len(normalized_description) >= 3 and normalized_description in normalized_source:
        score += 120
    normalized_category = _normalized_command_text(category)
    if normalized_category and normalized_category in normalized_source:
        score += 25

    source_bigrams = _command_bigrams(source)
    description_bigrams = _command_bigrams(description)
    if source_bigrams and description_bigrams:
        overlap = len(source_bigrams & description_bigrams) / len(description_bigrams)
        score += int(overlap * 70)

    action_words = ('设置', '领取', '增加', '删除', '开启', '关闭', '重置', '完成', '解锁')
    for word in action_words:
        if word in source and word in description:
            score += 45
    return score


def _select_kongming_command(question, commands):
    scored = []
    for command in commands or []:
        if not isinstance(command, dict):
            continue
        score = _command_match_score(question, command)
        if score:
            scored.append((score, command))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < 80:
        raise ValueError('没有从 GM 命令库中匹配到可信命令，请补充功能名称或直接写出命令示例')
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 15:
        names = '、'.join(str(item[1].get('name') or item[1].get('command')) for item in scored[:3])
        raise ValueError(f'匹配到多个相近 GM 命令（{names}），请补充要执行的具体操作')
    return scored[0][1]


def _command_example_arguments(command):
    template = str(command.get('command') or '').strip()
    example = str(command.get('example') or '').strip()
    if not example or not template or not example.lower().startswith(template.lower()):
        return []
    return example[len(template):].strip().split()


def _validate_command_arguments(command, arguments):
    cleaned = []
    for argument in arguments:
        value = str(argument or '').strip()
        if not value or len(value) > 100 or any(ch in value for ch in ('\r', '\n', '#', ';')):
            raise ValueError('GM 命令参数包含不允许的内容')
        cleaned.append(value)
    example_arguments = _command_example_arguments(command)
    if example_arguments and len(cleaned) != len(example_arguments):
        raise ValueError(
            f'命令参数数量不正确，请参考：{command.get("example") or command.get("command")}'
        )
    params = str(command.get('params') or '')
    range_match = re.search(r'(\d+)\s*[-~至到]\s*(\d+)', params)
    if range_match and len(cleaned) == 1 and cleaned[0].isdigit():
        minimum, maximum = int(range_match.group(1)), int(range_match.group(2))
        value = int(cleaned[0])
        if value < minimum or value > maximum:
            raise ValueError(f'命令参数必须在 {minimum} 到 {maximum} 之间')
    return cleaned


def _extract_kongming_command_arguments(question, command):
    source = str(question or '')
    template = str(command.get('command') or '').strip()
    explicit = re.search(
        rf'(?i)(?<!\S){re.escape(template)}(?:\s+([^\r\n，。；;]+))?',
        source,
    )
    if explicit:
        return _validate_command_arguments(command, str(explicit.group(1) or '').split())

    example_arguments = _command_example_arguments(command)
    if not example_arguments:
        return []
    if len(example_arguments) != 1:
        raise ValueError(f'该操作包含多个参数，请按命令示例填写：{command.get("example") or template}')

    patterns = (
        r'(?:设置为|设为|改成|修改为|调整到|升到|降低到)\s*(\d+)',
        r'(\d+)\s*级',
        r'(?:等级|数量|次数|阶段|星级)\s*(?:为|到|=|：|:)?\s*(\d+)',
    )
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            return _validate_command_arguments(command, [match.group(1)])
    raise ValueError(f'没有识别到命令参数，请按示例描述：{command.get("example") or template}')


def _find_by_id(items, item_id):
    return next((
        item for item in (items or [])
        if isinstance(item, dict) and str(item.get('id') or '').strip() == item_id
    ), None)


def _find_environment(catalog, app_id):
    environments = catalog.get('environments') if isinstance(catalog, dict) else []
    return next((
        item for item in (environments or [])
        if isinstance(item, dict) and app_id in {
            str(item.get('key') or '').strip(),
            str(item.get('raw_id') or '').strip(),
            str(item.get('app_id') or '').strip(),
        }
    ), None)


def _account_identifier_values(account):
    values = []
    for key in ('account_name', 'account_id', 'role_id', 'player_id', 'user_id'):
        value = str(account.get(key) or '').strip()
        if value:
            values.append(value)
    return values


def _resolve_reward_targets(environment, account_names=None, account_identifiers=None):
    accounts = environment.get('accounts') or []
    resolved = []
    requested_identifiers = []
    seen_requested = set()
    for value in [*(account_names or []), *(account_identifiers or [])]:
        identity = str(value).strip().lower()
        if identity and identity not in seen_requested:
            requested_identifiers.append(value)
            seen_requested.add(identity)
    for account_name in requested_identifiers:
        matches = [
            item for item in accounts
            if isinstance(item, dict)
            and any(
                value.lower() == str(account_name).strip().lower()
                for value in _account_identifier_values(item)
            )
        ]
        if not matches:
            raise ValueError(f'环境 {environment.get("name") or environment.get("key")} 中没有找到账号 {account_name}，请先同步 KS 账号缓存')
        matches.sort(
            key=lambda item: (str(item.get('last_seen') or ''), str(item.get('operation_time') or '')),
            reverse=True,
        )
        account = matches[0]
        missing = [
            key for key in ('role_id', 'server_id')
            if not str(account.get(key) or '').strip()
        ]
        connection_id = str(account.get('connection_id') or account.get('id') or '').strip()
        if connection_id.startswith('cache:'):
            connection_id = ''
        if not str(account.get('cache_id') or '').strip() and not connection_id:
            missing.append('cache_id/connection_id')
        if missing:
            raise ValueError(f'账号 {account_name} 信息不完整，缺少 ' + '、'.join(missing))
        target = {
            'environment_key': str(environment.get('key') or ''),
            'cache_id': str(account.get('cache_id') or '').strip(),
            'account_name': str(account.get('account_name') or '').strip(),
            'account_label': str(account.get('role_name') or account.get('account_label') or account.get('account_name') or '').strip(),
            'account_id': str(account.get('account_id') or '').strip(),
            'player_id': str(account.get('player_id') or '').strip(),
            'role_id': str(account.get('role_id') or '').strip(),
            'server_id': str(account.get('server_id') or '').strip(),
            'operation_time': str(account.get('operation_time') or account.get('last_seen') or '').strip(),
            'connection_id': connection_id,
            'client_id': str(account.get('client_id') or '').strip(),
            'port': str(account.get('port') or '').strip(),
            'environment_url': str(account.get('environment_url') or environment.get('login_url') or '').strip(),
            'online': bool(account.get('online') or account.get('connected')),
        }
        for key in ('proxy_client_id', 'proxy_connected_at'):
            if account.get(key):
                target[key] = str(account.get(key) or '').strip()
        resolved.append(target)
    return resolved


def _bulk_reward_account_names(environment, expected_count=None):
    accounts = [
        item for item in (environment.get('accounts') or [])
        if isinstance(item, dict) and str(item.get('account_name') or '').strip()
    ]
    accounts.sort(
        key=lambda item: (str(item.get('last_seen') or ''), str(item.get('operation_time') or '')),
        reverse=True,
    )
    account_names = []
    seen = set()
    for account in accounts:
        account_name = str(account.get('account_name') or '').strip()
        identity = account_name.lower()
        if identity in seen:
            continue
        seen.add(identity)
        account_names.append(account_name)
    actual_count = len(account_names)
    environment_name = environment.get('name') or environment.get('key') or '目标环境'
    if expected_count is not None and actual_count != expected_count:
        raise ValueError(
            f'环境 {environment_name} 同步后识别到 {actual_count} 个唯一账号，'
            f'与请求中的 {expected_count} 个账号不一致，已停止生成任务'
        )
    if not account_names:
        raise ValueError(f'环境 {environment_name} 同步后没有识别到可用账号')
    if actual_count > KONGMING_MAX_REWARD_TARGETS:
        raise ValueError(f'单次资源发放最多允许 {KONGMING_MAX_REWARD_TARGETS} 个账号')
    return account_names


def build_kongming_reward_workflow(owner_id, text, catalog, commands):
    if not is_kongming_reward_workflow_request(text):
        raise ValueError('当前文字不是受支持的 KS 账号资源发放任务')
    environment = _find_environment_by_text(catalog, text)
    if not environment:
        raise ValueError('KS 目录中没有找到该环境，请先在命令管理中更新 Token 并同步环境，或粘贴该环境的登录地址')
    currency = parse_reward_currency(text)
    amount = parse_reward_amount(text, currency.get('name') or '元宝')
    account_scope = parse_reward_account_scope(text)
    account_names = account_scope['account_names']
    if account_scope['mode'] == 'all':
        account_names = _bulk_reward_account_names(environment, account_scope.get('expected_count'))
    targets = _resolve_reward_targets(environment, account_names)
    command = _find_by_id(commands, KONGMING_REWARD_COMMAND_ID)
    if not command or not str(command.get('command') or '').strip():
        raise ValueError('命令库中缺少“添加货币”命令')

    executable_command = f'{str(command.get("command") or "").strip()} {currency["id"]} {amount}'
    now = _now_text()
    workflow = {
        'id': uuid.uuid4().hex,
        'owner_id': str(owner_id or ''),
        'type': KONGMING_REWARD_WORKFLOW_TYPE,
        'title': f'{environment.get("name") or environment.get("key")} · {len(targets)}个账号发放{currency["name"]}',
        'state': 'pending_confirmation',
        'source_text': str(text or '').strip(),
        'created_at': now,
        'updated_at': now,
        'confirmed_at': '',
        'completed_at': '',
        'environment': {
            'key': str(environment.get('key') or ''),
            'app_id': str(environment.get('app_id') or environment.get('raw_id') or environment.get('key') or ''),
            'app_name': str(environment.get('app_name') or environment.get('name') or ''),
            'name': str(environment.get('name') or environment.get('app_name') or environment.get('key') or ''),
            'project_id': str(environment.get('project_id') or ''),
            'cluster_name': str(environment.get('cluster') or ''),
            'status': str(environment.get('status') or ''),
            'login_url': str(environment.get('login_url') or environment.get('environment_url') or ''),
            'source_url': next(iter(extract_urls(text)), ''),
        },
        'targets': targets,
        'command': {
            'id': KONGMING_REWARD_COMMAND_ID,
            'name': str(command.get('name') or '添加货币'),
            'command': executable_command,
            'template': str(command.get('command') or '').strip(),
        },
        'reward': {
            'currency_id': currency['id'],
            'currency_name': currency['name'],
            'amount': amount,
            'amount_text': f'{amount:,}',
        },
        'steps': [
            {'id': 'resolve_reward_targets', 'title': f'核对 {len(targets)} 个目标账号', 'status': 'pending', 'attempts': 0},
            {'id': 'execute_reward_command', 'title': f'并行发放 {amount:,} {currency["name"]}', 'status': 'pending', 'attempts': 0},
        ],
        'runtime': {
            'targets': targets,
            'command_completed_cache_ids': [],
        },
        'events': [],
        'error': '',
    }
    return workflow


def build_kongming_account_command_workflow(owner_id, text, catalog, commands):
    if not is_kongming_account_command_workflow_request(text):
        raise ValueError('当前文字不是可识别的 KS 账号 GM 操作')
    environment = _find_environment_by_text(catalog, text)
    if not environment:
        raise ValueError('KS 目录中没有找到该环境，请先同步环境与账号，或提供该环境的登录地址')
    account_scope = parse_account_command_scope(text)
    account_names = account_scope['account_names']
    if account_scope['mode'] == 'all':
        account_names = _bulk_reward_account_names(environment, account_scope.get('expected_count'))
        targets = _resolve_reward_targets(environment, account_names=account_names)
    else:
        targets = _resolve_reward_targets(
            environment,
            account_names=account_names,
            account_identifiers=account_scope.get('account_identifiers'),
        )
    intent_text = _command_intent_text(text)
    command = _select_kongming_command(intent_text, commands)
    arguments = _extract_kongming_command_arguments(intent_text, command)
    template = str(command.get('command') or '').strip()
    executable_command = ' '.join([template, *arguments]).strip()
    operation_name = str(command.get('description') or command.get('name') or template).strip()
    now = _now_text()
    workflow = {
        'id': uuid.uuid4().hex,
        'owner_id': str(owner_id or ''),
        'type': KONGMING_ACCOUNT_COMMAND_WORKFLOW_TYPE,
        'title': f'{environment.get("name") or environment.get("key")} · {len(targets)}个账号{operation_name}',
        'state': 'pending_confirmation',
        'source_text': str(text or '').strip(),
        'created_at': now,
        'updated_at': now,
        'confirmed_at': '',
        'completed_at': '',
        'environment': {
            'key': str(environment.get('key') or ''),
            'app_id': str(environment.get('app_id') or environment.get('raw_id') or environment.get('key') or ''),
            'app_name': str(environment.get('app_name') or environment.get('name') or ''),
            'name': str(environment.get('name') or environment.get('app_name') or environment.get('key') or ''),
            'project_id': str(environment.get('project_id') or ''),
            'cluster_name': str(environment.get('cluster') or ''),
            'status': str(environment.get('status') or ''),
            'login_url': str(environment.get('login_url') or environment.get('environment_url') or ''),
            'source_url': next(iter(extract_urls(text)), ''),
        },
        'targets': targets,
        'command': {
            'id': str(command.get('id') or ''),
            'name': str(command.get('name') or operation_name),
            'description': str(command.get('description') or ''),
            'command': executable_command,
            'template': template,
            'arguments': arguments,
            'example': str(command.get('example') or ''),
        },
        'operation': {
            'name': operation_name,
            'command_id': str(command.get('id') or ''),
            'arguments': arguments,
        },
        'steps': [
            {'id': 'resolve_account_targets', 'title': f'核对 {len(targets)} 个目标账号与投递通道', 'status': 'pending', 'attempts': 0},
            {'id': 'execute_account_command', 'title': f'并行执行：{operation_name}', 'status': 'pending', 'attempts': 0},
        ],
        'runtime': {
            'targets': targets,
            'client_targets': [],
            'ks_targets': [],
            'command_completed_cache_ids': [],
        },
        'events': [],
        'error': '',
    }
    return workflow


def build_kongming_workflow(owner_id, text, catalog, commands, scripts):
    if is_kongming_reward_workflow_request(text):
        return build_kongming_reward_workflow(owner_id, text, catalog, commands)
    if is_kongming_account_command_workflow_request(text):
        return build_kongming_account_command_workflow(owner_id, text, catalog, commands)
    if not is_kongming_alliance_workflow_request(text):
        raise ValueError('当前文字没有匹配到可执行的孔明任务')
    target = parse_ks_application_url(text)
    account_servers, script_servers = parse_workflow_servers(text)
    environment = _find_environment(catalog, target['app_id'])
    if not environment:
        raise ValueError('KS 目录中没有找到该环境，请先在命令管理中更新 Token 并同步环境')

    environment_project_id = str(environment.get('project_id') or '').strip()
    environment_cluster = str(environment.get('cluster') or '').strip()
    if target['project_id'] and environment_project_id and target['project_id'] != environment_project_id:
        raise ValueError('KS 链接的 projectId 与已同步环境不一致，请重新同步后再试')
    if target['cluster_name'] and environment_cluster and target['cluster_name'] != environment_cluster:
        raise ValueError('KS 链接的集群与已同步环境不一致，请重新同步后再试')

    command = _find_by_id(commands, KONGMING_COMMAND_ID)
    script = _find_by_id(scripts, KONGMING_SCRIPT_ID)
    if not command or not str(command.get('command') or '').strip():
        raise ValueError('命令库中缺少“成为王盟(S1)/天子”命令')
    if not script or not str(script.get('content') or '').strip():
        raise ValueError('脚本库中缺少“备战活动脚本”')

    now = _now_text()
    script_content = str(script.get('content') or '')
    workflow = {
        'id': uuid.uuid4().hex,
        'owner_id': str(owner_id or ''),
        'type': KONGMING_WORKFLOW_TYPE,
        'title': f'{environment.get("name") or target["app_id"]} · {len(account_servers)}服盟主备战',
        'state': 'pending_confirmation',
        'source_text': str(text or '').strip(),
        'created_at': now,
        'updated_at': now,
        'confirmed_at': '',
        'completed_at': '',
        'environment': {
            'key': str(environment.get('key') or target['app_id']),
            'app_id': target['app_id'],
            'app_name': str(environment.get('app_name') or environment.get('name') or ''),
            'name': str(environment.get('name') or target['app_id']),
            'project_id': environment_project_id or target['project_id'],
            'cluster_name': environment_cluster or target['cluster_name'],
            'status': str(environment.get('status') or ''),
            'login_url': str(environment.get('login_url') or ''),
            'source_url': target['url'],
        },
        'account_servers': account_servers,
        'script_servers': script_servers,
        'command': {
            'id': KONGMING_COMMAND_ID,
            'name': str(command.get('name') or '成为王盟(S1)/天子'),
            'command': str(command.get('command') or '').strip(),
            'template': str(command.get('command') or '').strip(),
        },
        'script': {
            'id': KONGMING_SCRIPT_ID,
            'name': str(script.get('name') or '备战活动脚本'),
            'content': script_content,
            'sha256': hashlib.sha256(script_content.encode('utf-8')).hexdigest(),
        },
        'steps': [
            {'id': 'resolve_environment', 'title': '解析 KS 环境与赛季服', 'status': 'pending', 'attempts': 0},
            {'id': 'create_accounts', 'title': f'在 {len(account_servers)} 个原服创建盟主号', 'status': 'pending', 'attempts': 0},
            {'id': 'sync_accounts', 'title': '同步并核对本次新增账号', 'status': 'pending', 'attempts': 0},
            {'id': 'execute_command', 'title': '对新增账号执行成为天子', 'status': 'pending', 'attempts': 0},
            {'id': 'auto_login', 'title': '自动登录 GM 控制台并核对服务器', 'status': 'pending', 'attempts': 0},
            {'id': 'execute_script', 'title': '在指定原服执行备战活动脚本', 'status': 'pending', 'attempts': 0},
        ],
        'runtime': {
            'account_baseline': {},
            'created_accounts': [],
            'season_server_id': '',
            'gm_servers': [],
        },
        'events': [],
        'error': '',
    }
    return workflow


def save_kongming_workflow(base_dir, workflow):
    workflow = copy.deepcopy(workflow)
    owner_id = workflow.get('owner_id')
    workflow_id = workflow.get('id')
    path = _workflow_path(base_dir, owner_id, workflow_id)
    workflow['updated_at'] = _now_text()
    workflow['events'] = list(workflow.get('events') or [])[-100:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = path + '.tmp'
    with _workflow_file_lock:
        with open(temporary_path, 'w', encoding='utf-8') as target:
            json.dump(workflow, target, ensure_ascii=False, indent=2)
        os.replace(temporary_path, path)
    return workflow


def load_kongming_workflow(base_dir, owner_id, workflow_id):
    try:
        path = _workflow_path(base_dir, owner_id, workflow_id)
        with _workflow_file_lock:
            with open(path, 'r', encoding='utf-8') as source:
                workflow = json.load(source)
    except (ValueError, FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(workflow, dict) or workflow.get('owner_id') != str(owner_id or ''):
        return None
    return workflow


def append_workflow_event(workflow, message, level='info'):
    workflow.setdefault('events', []).append({
        'time': _now_text(),
        'level': str(level or 'info'),
        'message': str(message or '').strip()[:500],
    })


def update_kongming_workflow_command(base_dir, owner_id, workflow_id, command_text, operator=''):
    command_text = str(command_text or '').strip()
    if not command_text:
        raise ValueError('GM 命令不能为空')
    if len(command_text) > 2000:
        raise ValueError('GM 命令不能超过 2000 个字符')
    if '\r' in command_text or '\n' in command_text:
        raise ValueError('GM 命令只能填写一行')
    if not command_text.startswith('#'):
        raise ValueError('GM 命令必须以 # 开头')

    with _workflow_file_lock:
        workflow = load_kongming_workflow(base_dir, owner_id, workflow_id)
        if not workflow:
            raise ValueError('孔明任务不存在或无权访问')
        if workflow.get('state') != 'pending_confirmation':
            raise ValueError('只有等待确认的任务可以修改 GM 命令')
        if workflow.get('type') != KONGMING_REWARD_WORKFLOW_TYPE:
            raise ValueError('当前任务的 GM 命令不支持手动修改')

        command = workflow.get('command') or {}
        template = str(command.get('template') or '').strip()
        if not template:
            current_parts = str(command.get('command') or '').strip().split()
            template = current_parts[0] if current_parts else ''
        parts = command_text.split()
        if len(parts) != 3 or parts[0] != template:
            raise ValueError(f'资源发放命令格式应为：{template or "#money"} 货币类型 数量')
        if not parts[1].isdigit() or not parts[2].isdigit():
            raise ValueError('货币类型和数量必须填写正整数')
        currency_id = str(int(parts[1]))
        amount = int(parts[2])
        if int(currency_id) <= 0:
            raise ValueError('货币类型必须大于 0')
        if amount <= 0:
            raise ValueError('发放数量必须大于 0')
        if amount > 10_000_000_000:
            raise ValueError('单次发放数量不能超过 100 亿')

        old_command = str(command.get('command') or '')
        reward = workflow.setdefault('reward', {})
        old_currency_id = str(reward.get('currency_id') or '')
        old_currency_name = str(reward.get('currency_name') or '资源')
        currency_name = old_currency_name if currency_id == old_currency_id else f'货币 {currency_id}'
        command.update({
            'command': f'{template} {currency_id} {amount}',
            'template': template,
        })
        workflow['command'] = command
        reward.update({
            'currency_id': currency_id,
            'currency_name': currency_name,
            'amount': amount,
            'amount_text': f'{amount:,}',
        })
        environment = workflow.get('environment') or {}
        targets = workflow.get('targets') or []
        workflow['title'] = (
            f'{environment.get("name") or environment.get("key")} · '
            f'{len(targets)}个账号发放{currency_name}'
        )
        reward_step = next((
            step for step in (workflow.get('steps') or [])
            if step.get('id') == 'execute_reward_command'
        ), None)
        if reward_step:
            reward_step['title'] = f'并行发放 {amount:,} {currency_name}'
        workflow.setdefault('runtime', {})['command_completed_cache_ids'] = []
        workflow.setdefault('edits', []).append({
            'field': 'command',
            'before': old_command,
            'after': command['command'],
            'operator': str(operator or ''),
            'time': _now_text(),
        })
        append_workflow_event(workflow, f'{operator or "管理员"}修改 GM 命令参数')
        return save_kongming_workflow(base_dir, workflow)


def public_kongming_workflow(workflow):
    if not isinstance(workflow, dict):
        return None
    script = workflow.get('script') or {}
    runtime = workflow.get('runtime') or {}
    return {
        'id': workflow.get('id', ''),
        'type': workflow.get('type', ''),
        'title': workflow.get('title', ''),
        'state': workflow.get('state', ''),
        'created_at': workflow.get('created_at', ''),
        'updated_at': workflow.get('updated_at', ''),
        'confirmed_at': workflow.get('confirmed_at', ''),
        'completed_at': workflow.get('completed_at', ''),
        'environment': copy.deepcopy(workflow.get('environment') or {}),
        'account_servers': list(workflow.get('account_servers') or []),
        'script_servers': list(workflow.get('script_servers') or []),
        'targets': copy.deepcopy(workflow.get('targets') or runtime.get('targets') or []),
        'command': copy.deepcopy(workflow.get('command') or {}),
        'reward': copy.deepcopy(workflow.get('reward') or {}),
        'operation': copy.deepcopy(workflow.get('operation') or {}),
        'script': {
            'id': script.get('id', ''),
            'name': script.get('name', ''),
            'sha256': script.get('sha256', ''),
        },
        'steps': copy.deepcopy(workflow.get('steps') or []),
        'season_server_id': runtime.get('season_server_id', ''),
        'created_accounts': copy.deepcopy(runtime.get('created_accounts') or []),
        'events': copy.deepcopy((workflow.get('events') or [])[-20:]),
        'error': workflow.get('error', ''),
    }


def workflow_preview_markdown(workflow):
    environment = workflow.get('environment') or {}
    if workflow.get('type') == KONGMING_ACCOUNT_COMMAND_WORKFLOW_TYPE:
        targets = workflow.get('targets') or []
        operation = workflow.get('operation') or {}
        target_text = '、'.join(
            f'{item.get("server_id")}服/{item.get("account_name")}'
            for item in targets
        )
        return (
            '已根据提问生成可执行的 **KS 账号 GM 任务**。环境、账号和命令均已通过本地目录校验，确认前不会进行任何外部操作。\n\n'
            f'- KS 环境：**{environment.get("name") or environment.get("app_id")}**\n'
            f'- 目标账号：**{target_text}**\n'
            f'- 执行操作：**{operation.get("name") or (workflow.get("command") or {}).get("name")}**\n'
            f'- GM 命令：`{(workflow.get("command") or {}).get("command")}`\n\n'
            '请在下方任务卡核对范围并点击“确认并执行”。在线账号优先走 Cocos，未登录账号自动走 KS 投递。'
        )
    if workflow.get('type') == KONGMING_REWARD_WORKFLOW_TYPE:
        reward = workflow.get('reward') or {}
        targets = workflow.get('targets') or []
        target_text = '、'.join(
            f'{item.get("server_id")}服/{item.get("account_name")}'
            for item in targets
        )
        return (
            '已识别为可执行的 **KS 账号资源发放任务**。我已锁定环境、账号和命令，确认前不会进行任何外部操作。\n\n'
            f'- KS 环境：**{environment.get("name") or environment.get("app_id")}**\n'
            f'- 目标账号：**{target_text}**\n'
            f'- 发放资源：**{reward.get("amount_text") or reward.get("amount")} {reward.get("currency_name") or "元宝"}**\n'
            f'- GM 命令：`{(workflow.get("command") or {}).get("command")}`\n\n'
            '请在下方任务卡中核对账号和数量，然后点击“确认并执行”。在线账号优先走 Cocos，未登录账号自动走 KS 投递。'
        )
    account_servers = '、'.join(workflow.get('account_servers') or [])
    script_servers = '、'.join('Server_' + item for item in (workflow.get('script_servers') or []))
    return (
        '已识别为可执行的 **KS 盟主备战任务**。我已锁定执行范围，确认前不会进行任何外部操作。\n\n'
        f'- KS 环境：**{environment.get("name") or environment.get("app_id")}**\n'
        f'- 创建账号：原服 **{account_servers}**，每服 1 个联盟、1 个盟主号\n'
        f'- GM 命令：**{(workflow.get("command") or {}).get("name")}**\n'
        f'- 脚本目标：**{script_servers}**\n'
        f'- 执行脚本：**{(workflow.get("script") or {}).get("name")}**\n\n'
        '请在下方任务卡中核对范围，然后点击“确认并执行”。任务失败时会停在当前步骤，不会自动扩大服务器或账号范围。'
    )
