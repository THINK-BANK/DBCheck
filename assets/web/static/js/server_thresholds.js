// DBCheck - 服务器阈值配置前端逻辑
// 文件: static/js/server_thresholds.js

// 分类分组定义
const THRESHOLD_GROUPS = {
    'cpu':    'CPU 阈值',
    'mem':    '内存阈值',
    'swap':   'Swap 阈值',
    'disk':   '磁盘阈值',
    'inode':  'inode 阈值',
    'docker': 'Docker 阈值',
    'health': '健康评分阈值',
    'zombie': '僵尸进程阈值',
};

// ========== 加载服务器阈值 ==========
function loadServerThresholds() {
    const tbody = document.getElementById('server-thresholds-tbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--text-muted);padding:32px">加载中...</td></tr>';

    fetch('/api/server_thresholds')
        .then(r => r.json())
        .then(resp => {
            if (resp.success) {
                renderServerThresholdsTable(resp.data);
            } else {
                if (tbody) tbody.innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--danger)">加载失败: ${escapeHtml(resp.message || '')}</td></tr>`;
            }
        })
        .catch(err => {
            if (tbody) tbody.innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--danger)">请求失败: ${escapeHtml(err.message)}</td></tr>`;
        });
}

// ========== 按分类渲染表格 ==========
function renderServerThresholdsTable(data) {
    const tbody = document.getElementById('server-thresholds-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (!data || data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--text-muted);padding:32px">暂无阈值配置</td></tr>';
        return;
    }

    // 按分类分组
    const groups = {};
    data.forEach(item => {
        const prefix = item.key.split('_')[0];
        if (!groups[prefix]) groups[prefix] = [];
        groups[prefix].push(item);
    });

    // 按固定顺序渲染分类
    const order = ['cpu', 'mem', 'swap', 'disk', 'inode', 'docker', 'health', 'zombie'];
    order.forEach(key => {
        if (!groups[key]) return;

        // 分类标题行
        const groupLabel = THRESHOLD_GROUPS[key] || key;
        const trGroup = document.createElement('tr');
        trGroup.innerHTML = `<td colspan="3" style="background:var(--surface2);font-weight:600;padding:8px 12px;color:var(--accent2);">${escapeHtml(groupLabel)}</td>`;
        tbody.appendChild(trGroup);

        // 该分类下的所有阈值行
        groups[key].forEach(item => {
            const tr = document.createElement('tr');
            const val = item.value != null ? item.value : '';
            const desc = item.description_zh || item.key;
            tr.innerHTML = `
                <td style="padding:8px 12px;color:var(--text);">${escapeHtml(desc)}</td>
                <td style="padding:8px 12px;">
                    <input type="number" step="any" value="${escapeHtml(String(val))}" data-key="${escapeHtml(item.key)}" style="width:100px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-size:13px;" />
                </td>
                <td style="padding:8px 12px;color:var(--text-muted);font-size:12px;">${escapeHtml(item.description_en || '')}</td>`;
            tbody.appendChild(tr);
        });
    });
}

// ========== 保存服务器阈值 ==========
function saveServerThresholds() {
    const inputs = document.querySelectorAll('#server-thresholds-tbody input[data-key]');
    const items = [];
    inputs.forEach(input => {
        const key = input.getAttribute('data-key');
        const value = parseFloat(input.value);
        if (key && !isNaN(value)) {
            items.push({ key: key, value: value });
        }
    });

    if (items.length === 0) {
        showServerThresholdsToast('没有可保存的阈值', 'error');
        return;
    }

    fetch('/api/server_thresholds', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(items)
    })
    .then(r => r.json())
    .then(resp => {
        if (resp.success) {
            showServerThresholdsToast(i18n('server_thresholds.save_success') || '服务器阈值配置已保存', 'success');
            loadServerThresholds(); // 重新加载
        } else {
            showServerThresholdsToast(i18n('server_thresholds.save_failed') || '保存失败' + ': ' + (resp.message || '未知错误'), 'error');
        }
    })
    .catch(err => {
        showServerThresholdsToast('保存失败: ' + err.message, 'error');
    });
}

// ========== Toast 提示 ==========
function showServerThresholdsToast(msg, type) {
    if (type === 'success' && typeof toastSuccess === 'function') {
        toastSuccess(msg);
        return;
    }
    if (type === 'error' && typeof toastError === 'function') {
        toastError(msg);
        return;
    }
    // fallback
    const div = document.createElement('div');
    div.textContent = msg;
    div.style.cssText = `position:fixed;top:20px;right:20px;padding:12px 20px;border-radius:8px;z-index:9999;font-size:13px;color:#fff;background:${type === 'success' ? 'var(--accent)' : 'var(--danger)'}`;
    document.body.appendChild(div);
    setTimeout(() => div.remove(), 3000);
}

// ========== HTML 转义 ==========
function escapeHtml(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
