/* HOLOS - Intelligent Home Cataloging & Asset Intelligence */

/* ── XSS Protection ─────────────────────────────────────── */
// DOMPurify sanitizer: wraps innerHTML to prevent XSS from AI/user content
const safeHTML = (html) => typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html, { ADD_ATTR: ['data-id', 'data-index', 'data-tempid', 'data-status'] }) : html;

document.addEventListener('DOMContentLoaded', () => {
    // --- Elements ---
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const dropContent = document.getElementById('drop-content');
    const scanningState = document.getElementById('scanning-state');
    const resultsSection = document.getElementById('results-section');
    const cardsContainer = document.getElementById('cards-container');
    const previewImage = document.getElementById('preview-image');
    const resetBtn = document.getElementById('reset-btn');
    const assetSearch = document.getElementById('asset-search');
    const myInventoryBtn = document.getElementById('my-inventory-btn');
    const generateReportBtn = document.getElementById('generate-report-btn');
    const modalOverlay = document.getElementById('modal-overlay');
    const modalBody = document.getElementById('modal-body');
    const closeModalBtn = document.getElementById('close-modal-btn');
    const estateTemplate = document.getElementById('estate-report-template');
    const appShell = document.getElementById('app-shell');

    // --- State ---
    let currentScanItems = []; // Raw results from Gemini
    let appMode = 'scan'; // 'scan' or 'inventory'

    // ═══════════════════════════════════════════════════════
    // Sidebar Navigation
    // ═══════════════════════════════════════════════════════
    function switchTab(tabName) {
        // Update sidebar active state
        document.querySelectorAll('.sidebar-tab').forEach(t => t.classList.remove('active'));
        document.querySelector(`.sidebar-tab[data-tab="${tabName}"]`)?.classList.add('active');

        // Switch content
        document.querySelectorAll('.tab-content').forEach(s => s.classList.remove('active'));
        document.getElementById(`tab-${tabName}`)?.classList.add('active');

        // Load data when switching tabs
        if (tabName === 'dashboard') loadDashboardData();
        if (tabName === 'maintenance') loadMaintenanceTasks();
        if (tabName === 'projects') { if (typeof renderProjects === 'function') renderProjects(); }
        if (tabName === 'finances') { if (typeof renderFinances === 'function') renderFinances(); }
    }

    // Sidebar tab clicks
    document.querySelectorAll('.sidebar-tab').forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    // Module card clicks on dashboard
    document.querySelectorAll('.module-card[data-goto]').forEach(card => {
        card.addEventListener('click', () => switchTab(card.dataset.goto));
    });

    // Dashboard action buttons
    document.getElementById('dash-new-scan-btn')?.addEventListener('click', () => switchTab('inventory'));
    document.getElementById('dash-report-btn')?.addEventListener('click', () => {
        generateReportBtn?.click();
    });

    // Load dashboard summary data
    async function loadDashboardData() {
        const sessionStr = localStorage.getItem('holos_session');
        const sess = sessionStr ? JSON.parse(sessionStr) : null;
        if (!sess?.access_token) return;

        try {
            const r = await fetch('/api/items', {
                headers: { 'Authorization': `Bearer ${sess.access_token}` }
            });
            const d = await r.json();
            if (d.success && d.data) {
                const items = d.data.filter(i => !i.is_archived);
                document.getElementById('dash-total-items').textContent = items.length;

                // Calculate total value
                let totalVal = 0;
                items.forEach(item => {
                    const price = parseFloat(item.estimated_price || item.price || 0);
                    if (!isNaN(price)) totalVal += price;
                });
                document.getElementById('dash-total-value').textContent =
                    '$' + totalVal.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
            }
        } catch (e) {
            console.warn('Dashboard data load failed:', e);
        }

        // Properties count from localStorage
        const props = JSON.parse(localStorage.getItem('holos_properties') || '{}');
        const propCount = Math.max(1, Object.keys(props).length);
        document.getElementById('dash-properties-count').textContent = propCount;
    }

    // ═══════════════════════════════════════════════════════
    // Home Maintenance Module
    // ═══════════════════════════════════════════════════════
    let maintTasks = [];
    let maintFilterSeason = 'all';

    function getAuthHeaders() {
        const sessionStr = localStorage.getItem('holos_session');
        const sess = sessionStr ? JSON.parse(sessionStr) : null;
        const h = { 'Content-Type': 'application/json' };
        if (sess?.access_token) h['Authorization'] = `Bearer ${sess.access_token}`;
        return h;
    }

    async function loadMaintenanceTasks() {
        try {
            const r = await fetch('/api/maintenance', { headers: getAuthHeaders() });
            const d = await r.json();
            if (d.success) {
                maintTasks = d.data || [];
                renderMaintenanceTasks();
            }
        } catch (e) {
            console.warn('Maintenance load failed:', e);
        }
    }

    function renderMaintenanceTasks() {
        const container = document.getElementById('maint-tasks-container');
        const emptyState = document.getElementById('maint-empty');
        const today = new Date().toISOString().slice(0, 10);

        // Filter by season
        const filtered = maintFilterSeason === 'all'
            ? maintTasks
            : maintTasks.filter(t => t.season === maintFilterSeason);

        // Update stats
        const overdue = maintTasks.filter(t => t.due_date && t.due_date < today && !t.completed_at).length;
        const upcoming = maintTasks.filter(t => t.due_date && t.due_date >= today && !t.completed_at).length;
        const completed = maintTasks.filter(t => t.completed_at).length;
        document.getElementById('maint-total').textContent = maintTasks.length;
        document.getElementById('maint-overdue').textContent = overdue;
        document.getElementById('maint-upcoming').textContent = upcoming;
        document.getElementById('maint-completed').textContent = completed;

        // Update dashboard card if visible
        const dashMaint = document.getElementById('dash-maint-count');
        if (dashMaint) dashMaint.textContent = maintTasks.length > 0 ? `${overdue} overdue` : '0';

        if (filtered.length === 0) {
            container.innerHTML = '';
            if (emptyState) {
                container.appendChild(emptyState);
                emptyState.style.display = '';
            }
            return;
        }

        // Sort: overdue first, then by due date
        filtered.sort((a, b) => {
            if (a.completed_at && !b.completed_at) return 1;
            if (!a.completed_at && b.completed_at) return -1;
            return (a.due_date || 'z').localeCompare(b.due_date || 'z');
        });

        container.innerHTML = safeHTML(filtered.map(task => {
            const isOverdue = task.due_date && task.due_date < today && !task.completed_at;
            const isCompleted = !!task.completed_at;
            const dueLabel = task.due_date
                ? new Date(task.due_date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
                : '';

            return `
                <div class="maint-task ${isCompleted ? 'completed' : ''}" data-id="${task.id}">
                    <div class="maint-priority-dot ${task.priority}" title="${task.priority}"></div>
                    <button class="maint-task-check" data-id="${task.id}" title="Toggle complete">
                        ${isCompleted ? '<i class="ri-check-line"></i>' : ''}
                    </button>
                    <div class="maint-task-body">
                        <div class="maint-task-title">${task.title}</div>
                        <div class="maint-task-meta">
                            <span class="maint-task-tag maint-tag-category">${task.category}</span>
                            <span class="maint-task-tag maint-tag-season">${task.season}</span>
                            ${dueLabel ? `<span class="maint-task-tag maint-tag-due ${isOverdue ? 'overdue' : ''}">${isOverdue ? '⚠ ' : ''}${dueLabel}</span>` : ''}
                        </div>
                    </div>
                    <button class="maint-task-delete" data-id="${task.id}" title="Delete">
                        <i class="ri-delete-bin-line"></i>
                    </button>
                </div>
            `;
        }).join(''));

        // Wire up check/delete buttons
        container.querySelectorAll('.maint-task-check').forEach(btn => {
            btn.addEventListener('click', async () => {
                const id = btn.dataset.id;
                const task = maintTasks.find(t => t.id === id);
                if (!task) return;
                const completed = !task.completed_at;
                await fetch(`/api/maintenance/${id}`, {
                    method: 'PATCH',
                    headers: getAuthHeaders(),
                    body: JSON.stringify({ completed })
                });
                await loadMaintenanceTasks();
            });
        });

        container.querySelectorAll('.maint-task-delete').forEach(btn => {
            btn.addEventListener('click', async () => {
                const id = btn.dataset.id;
                await fetch(`/api/maintenance/${id}`, {
                    method: 'DELETE',
                    headers: getAuthHeaders()
                });
                await loadMaintenanceTasks();
            });
        });
    }

    // Season filter tabs
    document.querySelectorAll('.maint-filter').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.maint-filter').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            maintFilterSeason = btn.dataset.season;
            renderMaintenanceTasks();
        });
    });

    // Generate AI Schedule
    document.getElementById('maint-generate-btn')?.addEventListener('click', async () => {
        const container = document.getElementById('maint-tasks-container');
        container.innerHTML = '<div style="text-align:center;padding:3rem"><i class="ri-loader-4-line ri-spin" style="font-size:3rem;color:var(--primary)"></i><p style="margin-top:1rem;color:var(--text-muted)">Gemini is generating your maintenance schedule...</p></div>';

        const props = JSON.parse(localStorage.getItem('holos_properties') || '{}');
        const homeSelect = document.getElementById('home-select');
        const selectedHome = homeSelect?.value || 'My House';
        const prop = props[selectedHome] || {};

        try {
            const r = await fetch('/api/maintenance/generate', {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({
                    property_name: selectedHome,
                    address: prop.address || '',
                    bedrooms: prop.bedrooms || 3,
                    bathrooms: prop.bathrooms || 2,
                    rooms: prop.rooms || []
                })
            });
            const d = await r.json();
            if (d.success) {
                maintTasks = d.data;
                renderMaintenanceTasks();
            } else {
                container.innerHTML = `<div class="maint-empty-state"><i class="ri-error-warning-line"></i><h3>Generation Failed</h3><p>${d.error || 'Please try again.'}</p></div>`;
            }
        } catch (e) {
            container.innerHTML = '<div class="maint-empty-state"><i class="ri-error-warning-line"></i><h3>Connection Error</h3><p>Could not reach the server.</p></div>';
        }
    });

    // Add Task Modal
    const maintAddModal = document.getElementById('maint-add-modal');
    document.getElementById('maint-add-btn')?.addEventListener('click', () => {
        maintAddModal?.classList.remove('hidden');
    });
    document.getElementById('close-maint-modal')?.addEventListener('click', () => {
        maintAddModal?.classList.add('hidden');
    });

    document.getElementById('maint-save-task')?.addEventListener('click', async () => {
        const title = document.getElementById('maint-task-title')?.value?.trim();
        if (!title) return;

        await fetch('/api/maintenance', {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                title,
                description: document.getElementById('maint-task-desc')?.value?.trim() || '',
                category: document.getElementById('maint-task-cat')?.value || 'General',
                season: document.getElementById('maint-task-season')?.value || 'Spring',
                priority: document.getElementById('maint-task-priority')?.value || 'medium',
                due_date: document.getElementById('maint-task-due')?.value || null
            })
        });

        // Clear form and close
        document.getElementById('maint-task-title').value = '';
        document.getElementById('maint-task-desc').value = '';
        maintAddModal?.classList.add('hidden');
        await loadMaintenanceTasks();
    });

    // ═══════════════════════════════════════════════════════
    // Home Projects Module (localStorage-backed)
    // ═══════════════════════════════════════════════════════
    let projects = JSON.parse(localStorage.getItem('holos_projects') || '[]');
    let projFilter = 'all';

    function saveProjects() { localStorage.setItem('holos_projects', JSON.stringify(projects)); }

    function renderProjects() {
        const container = document.getElementById('proj-container');
        if (!container) return;
        const filtered = projFilter === 'all' ? projects : projects.filter(p => p.status === projFilter);

        // Stats
        document.getElementById('proj-total').textContent = projects.length;
        document.getElementById('proj-active').textContent = projects.filter(p => p.status === 'in-progress').length;
        const totalBudget = projects.reduce((s, p) => s + (parseFloat(p.budget) || 0), 0);
        const totalSpent = projects.reduce((s, p) => s + (parseFloat(p.spent) || 0), 0);
        document.getElementById('proj-budget').textContent = '$' + totalBudget.toLocaleString();
        document.getElementById('proj-spent').textContent = '$' + totalSpent.toLocaleString();

        if (filtered.length === 0) {
            container.innerHTML = '<div class="maint-empty-state"><i class="ri-hammer-line"></i><h3>No projects</h3><p>Add a project to get started.</p></div>';
            return;
        }

        container.innerHTML = safeHTML(filtered.map(p => {
            const budget = parseFloat(p.budget) || 0;
            const spent = parseFloat(p.spent) || 0;
            const pct = budget > 0 ? Math.min(100, (spent / budget) * 100) : 0;
            const over = spent > budget && budget > 0;
            const statusLabel = { planning: 'Planning', 'in-progress': 'In Progress', completed: 'Completed', 'on-hold': 'On Hold' }[p.status] || p.status;
            return `
            <div class="proj-card">
                <div class="proj-card-header">
                    <div>
                        <div class="proj-card-title">${p.name}</div>
                        <div class="proj-card-desc">${p.category} ${p.desc ? '· ' + p.desc : ''}</div>
                    </div>
                    <div style="display:flex;gap:0.5rem;align-items:center">
                        <span class="proj-status-badge ${p.status}">${statusLabel}</span>
                        <button class="maint-task-delete" data-pid="${p.id}"><i class="ri-delete-bin-line"></i></button>
                    </div>
                </div>
                ${budget > 0 ? `
                <div>
                    <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:var(--text-muted);margin-bottom:4px">
                        <span>Budget: $${budget.toLocaleString()}</span>
                        <span style="color:${over ? 'var(--danger)' : 'var(--text-muted)'}">Spent: $${spent.toLocaleString()}</span>
                    </div>
                    <div class="proj-budget-bar"><div class="proj-budget-fill ${over ? 'over' : ''}" style="width:${pct}%"></div></div>
                </div>` : ''}
                <div class="proj-meta">
                    ${p.start ? `<span><i class="ri-calendar-line"></i> ${p.start}</span>` : ''}
                    ${p.end ? `<span><i class="ri-calendar-check-line"></i> Target: ${p.end}</span>` : ''}
                </div>
            </div>`;
        }).join(''));

        container.querySelectorAll('[data-pid]').forEach(btn => {
            btn.addEventListener('click', () => {
                projects = projects.filter(p => p.id !== btn.dataset.pid);
                saveProjects(); renderProjects();
            });
        });
    }

    // Project status filters
    document.querySelectorAll('[data-pstatus]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('[data-pstatus]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            projFilter = btn.dataset.pstatus;
            renderProjects();
        });
    });

    // Add project modal
    const projModal = document.getElementById('proj-add-modal');
    document.getElementById('proj-add-btn')?.addEventListener('click', () => projModal?.classList.remove('hidden'));
    document.getElementById('close-proj-modal')?.addEventListener('click', () => projModal?.classList.add('hidden'));
    document.getElementById('proj-save-btn')?.addEventListener('click', () => {
        const name = document.getElementById('proj-name')?.value?.trim();
        if (!name) return;
        projects.push({
            id: Date.now().toString(),
            name,
            desc: document.getElementById('proj-desc')?.value?.trim() || '',
            category: document.getElementById('proj-cat')?.value || 'Other',
            status: document.getElementById('proj-status')?.value || 'planning',
            budget: document.getElementById('proj-budget-input')?.value || 0,
            spent: document.getElementById('proj-spent-input')?.value || 0,
            start: document.getElementById('proj-start')?.value || '',
            end: document.getElementById('proj-end')?.value || '',
        });
        saveProjects();
        projModal?.classList.add('hidden');
        document.getElementById('proj-name').value = '';
        document.getElementById('proj-desc').value = '';
        renderProjects();
    });

    // ═══════════════════════════════════════════════════════
    // Home Finances Module (localStorage-backed)
    // ═══════════════════════════════════════════════════════
    let finData = JSON.parse(localStorage.getItem('holos_finances') || '{"homeValue":0,"mortgage":0,"expenses":[]}');

    function saveFinances() { localStorage.setItem('holos_finances', JSON.stringify(finData)); }

    function renderFinances() {
        const hv = parseFloat(finData.homeValue) || 0;
        const mg = parseFloat(finData.mortgage) || 0;
        const equity = hv - mg;
        document.getElementById('fin-home-value').textContent = hv ? '$' + hv.toLocaleString() : '—';
        document.getElementById('fin-mortgage').textContent = mg ? '$' + mg.toLocaleString() : '—';
        document.getElementById('fin-equity').textContent = hv ? '$' + equity.toLocaleString() : '—';

        if (hv) {
            document.getElementById('fin-value-input').value = hv;
            document.getElementById('fin-mortgage-input').value = mg;
        }

        const container = document.getElementById('fin-expenses-container');
        if (!container) return;
        const expenses = finData.expenses || [];
        if (expenses.length === 0) {
            container.innerHTML = '<div class="maint-empty-state"><i class="ri-receipt-line"></i><h3>No expenses logged</h3><p>Click <strong>"Add Expense"</strong> to track home-related spending.</p></div>';
            return;
        }
        container.innerHTML = safeHTML([...expenses].reverse().map(e => `
            <div class="fin-expense-row">
                <div class="fin-exp-left">
                    <div class="fin-exp-title">${e.desc}</div>
                    <div class="fin-exp-meta">${e.category} · ${e.date || 'No date'}</div>
                </div>
                <div style="display:flex;align-items:center;gap:0.75rem">
                    <span class="fin-exp-amount">-$${parseFloat(e.amount).toLocaleString()}</span>
                    <button class="maint-task-delete" data-eid="${e.id}"><i class="ri-delete-bin-line"></i></button>
                </div>
            </div>
        `).join(''));

        container.querySelectorAll('[data-eid]').forEach(btn => {
            btn.addEventListener('click', () => {
                finData.expenses = finData.expenses.filter(e => e.id !== btn.dataset.eid);
                saveFinances(); renderFinances();
            });
        });
    }

    // Finance setup save
    document.getElementById('fin-save-setup')?.addEventListener('click', () => {
        finData.homeValue = parseFloat(document.getElementById('fin-value-input')?.value) || 0;
        finData.mortgage = parseFloat(document.getElementById('fin-mortgage-input')?.value) || 0;
        saveFinances(); renderFinances();
    });

    // Add expense modal
    const finModal = document.getElementById('fin-add-modal');
    document.getElementById('fin-add-btn')?.addEventListener('click', () => finModal?.classList.remove('hidden'));
    document.getElementById('close-fin-modal')?.addEventListener('click', () => finModal?.classList.add('hidden'));
    document.getElementById('fin-save-expense')?.addEventListener('click', () => {
        const desc = document.getElementById('fin-exp-desc')?.value?.trim();
        const amount = parseFloat(document.getElementById('fin-exp-amount')?.value);
        if (!desc || !amount) return;
        if (!finData.expenses) finData.expenses = [];
        finData.expenses.push({
            id: Date.now().toString(),
            desc,
            category: document.getElementById('fin-exp-cat')?.value || 'Other',
            amount,
            date: document.getElementById('fin-exp-date')?.value || new Date().toISOString().slice(0,10)
        });
        saveFinances();
        finModal?.classList.add('hidden');
        document.getElementById('fin-exp-desc').value = '';
        document.getElementById('fin-exp-amount').value = '';
        renderFinances();
    });

    // ═══════════════════════════════════════════════════════
    // AI Home Assistant
    // ═══════════════════════════════════════════════════════
    const aiChatWindow = document.getElementById('ai-chat-window');
    const aiChatInput = document.getElementById('ai-chat-input');

    function addAIMessage(text, role) {
        const msg = document.createElement('div');
        msg.className = `ai-message ai-message-${role}`;
        const icon = role === 'bot' ? 'ri-robot-2-line' : 'ri-user-3-line';
        msg.innerHTML = `
            <div class="ai-avatar"><i class="${icon}"></i></div>
            <div class="ai-bubble">${text.replace(/\n/g, '<br>')}</div>
        `;
        aiChatWindow?.appendChild(msg);
        if (aiChatWindow) aiChatWindow.scrollTop = aiChatWindow.scrollHeight;
        return msg;
    }

    async function sendAIMessage(prompt) {
        if (!prompt?.trim()) return;
        addAIMessage(prompt, 'user');
        if (aiChatInput) aiChatInput.value = '';

        // Typing indicator
        const typingEl = document.createElement('div');
        typingEl.className = 'ai-message ai-message-bot';
        typingEl.innerHTML = '<div class="ai-avatar"><i class="ri-robot-2-line"></i></div><div class="ai-bubble"><div class="ai-typing"><span></span><span></span><span></span></div></div>';
        aiChatWindow?.appendChild(typingEl);
        if (aiChatWindow) aiChatWindow.scrollTop = aiChatWindow.scrollHeight;

        try {
            const r = await fetch('/api/ai/chat', {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({ message: prompt })
            });
            const d = await r.json();
            typingEl.remove();
            addAIMessage(d.reply || d.error || 'Sorry, I could not get a response.', 'bot');
        } catch {
            typingEl.remove();
            addAIMessage('Could not reach the AI. Please make sure the server is running.', 'bot');
        }
    }

    document.getElementById('ai-send-btn')?.addEventListener('click', () => sendAIMessage(aiChatInput?.value));
    aiChatInput?.addEventListener('keydown', e => { if (e.key === 'Enter') sendAIMessage(aiChatInput.value); });
    document.querySelectorAll('.ai-prompt-chip').forEach(chip => {
        chip.addEventListener('click', () => sendAIMessage(chip.dataset.prompt));
    });
    document.getElementById('ai-clear-btn')?.addEventListener('click', () => {
        if (aiChatWindow) aiChatWindow.innerHTML = '<div class="ai-message ai-message-bot"><div class="ai-avatar"><i class="ri-robot-2-line"></i></div><div class="ai-bubble">Chat cleared. What would you like to know about your home?</div></div>';
    });

    // Helper to get value from combo-selector (select + custom input)
    function getLocationValue(selectId, customInputId) {
        const inp = document.getElementById(customInputId);
        const sel = document.getElementById(selectId);
        if (inp && !inp.classList.contains('hidden') && inp.value.trim()) {
            return inp.value.trim();
        }
        const val = sel?.value;
        return (val && val !== '__custom__') ? val : (sel?.options?.[0]?.value || 'My House');
    }

    // --- Core Logic ---

    dropZone.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', async (e) => {
        if (e.target.files.length > 0) {
            handleFiles(e.target.files);
        }
    });

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });

    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            handleFiles(e.dataTransfer.files);
        }
    });

    resetBtn?.addEventListener('click', () => {
        window.location.reload();
    });

    async function handleFiles(files) {
        dropZone.classList.add('hidden');
        scanningState.classList.remove('hidden');

        // ── Blur Detection: reject blurry images before upload ──
        const BLUR_THRESHOLD = 30; // Laplacian variance below this = blurry
        const validFiles = [];
        const rejectedFiles = [];

        for (let file of files) {
            const score = await getBlurScore(file);
            if (score < BLUR_THRESHOLD) {
                rejectedFiles.push({ file, score: Math.round(score) });
            } else {
                validFiles.push(file);
            }
        }

        if (rejectedFiles.length > 0 && validFiles.length === 0) {
            // All images are blurry — show error and reset
            scanningState.classList.add('hidden');
            dropZone.classList.remove('hidden');
            const names = rejectedFiles.map(r => `"${r.file.name}" (sharpness: ${r.score})`).join(', ');
            alert(`⚠️ Image quality too low\n\nThe following image(s) are too blurry for accurate scanning:\n${names}\n\nPlease retake the photo with better lighting and a steady hand.`);
            return;
        }

        if (rejectedFiles.length > 0) {
            const names = rejectedFiles.map(r => r.file.name).join(', ');
            console.warn(`Skipped blurry images: ${names}`);
        }

        // Use valid files only
        const filesToUpload = validFiles.length > 0 ? validFiles : Array.from(files);

        // Use the first image as the preview for the "scanning" HUD
        const firstFile = filesToUpload[0];
        previewImage.src = URL.createObjectURL(firstFile);

        const formData = new FormData();
        for (let file of filesToUpload) {
            formData.append('image', file);
        }

        // Include location info
        const homeName = getLocationValue('home-select', 'home-custom-input');
        const roomName = getLocationValue('room-select', 'room-custom-input');
        formData.append('home_name', homeName);
        formData.append('room_name', roomName);

        const userNotes = document.getElementById('user-notes')?.value?.trim() || '';
        if (userNotes) {
            formData.append('user_notes', userNotes);
        }

        // Get auth token
        const sessionStr = localStorage.getItem('holos_session');
        const sess = sessionStr ? JSON.parse(sessionStr) : null;
        const headers = {};
        if (sess?.access_token) {
            headers['Authorization'] = `Bearer ${sess.access_token}`;
        }

        try {
            const response = await fetch('/api/scan', {
                method: 'POST',
                headers: headers,
                body: formData
            });

            const data = await response.json();
            if (data.success) {
                const summary = data.summary || {};
                const autoSaved = data.auto_saved || [];
                const needsReview = data.needs_review || [];

                // Mark items with their status for the renderer
                autoSaved.forEach(item => { item._status = 'auto_saved'; });
                needsReview.forEach(item => { item._status = 'needs_review'; });

                // Combine for rendering — auto-saved first, then review items
                currentScanItems = [...autoSaved, ...needsReview];

                // Pre-generate thumbnails locally for speed
                const firstFile = files[0];
                for (let item of currentScanItems) {
                    if (!item.thumbnail_url && firstFile && item.bounding_box) {
                        item.thumbnail_url = await generateThumbnail(firstFile, item.bounding_box);
                    }
                }

                renderResults(currentScanItems, summary);
                resetBtn.classList.remove('hidden');
            } else {
                alert('Scan Failed: ' + (data.error || 'Check server logs'));
                window.location.reload();
            }
        } catch (err) {
            console.error('Scan Error:', err);
            alert('Error reaching the scanning AI.');
            window.location.reload();
        }
    }

    function groupByCategory(items) {
        const tree = {};
        items.forEach(item => {
            const cat = item.category || "General > Uncategorized";
            const parts = cat.split(' > ');
            const mainCat = parts[0];
            const subCat = parts.length > 1 ? parts.slice(1).join(' > ') : "General";

            if (!tree[mainCat]) tree[mainCat] = {};
            if (!tree[mainCat][subCat]) tree[mainCat][subCat] = [];
            tree[mainCat][subCat].push(item);
        });
        return tree;
    }

    /**
     * Compute a blur score for an image file using Laplacian variance.
     * Higher score = sharper image. Score < 30 is typically blurry.
     */
    async function getBlurScore(file) {
        return new Promise((resolve) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');

                // Downsample for speed (max 512px on longest side)
                const maxDim = 512;
                const scale = Math.min(maxDim / img.width, maxDim / img.height, 1);
                canvas.width = Math.round(img.width * scale);
                canvas.height = Math.round(img.height * scale);
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

                const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                const data = imageData.data;
                const w = canvas.width;
                const h = canvas.height;

                // Convert to grayscale array
                const gray = new Float32Array(w * h);
                for (let i = 0; i < w * h; i++) {
                    const idx = i * 4;
                    gray[i] = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
                }

                // Apply Laplacian kernel [0,1,0; 1,-4,1; 0,1,0]
                let sum = 0, sumSq = 0, count = 0;
                for (let y = 1; y < h - 1; y++) {
                    for (let x = 1; x < w - 1; x++) {
                        const lap =
                            gray[(y - 1) * w + x] +
                            gray[(y + 1) * w + x] +
                            gray[y * w + (x - 1)] +
                            gray[y * w + (x + 1)] -
                            4 * gray[y * w + x];
                        sum += lap;
                        sumSq += lap * lap;
                        count++;
                    }
                }

                // Variance of Laplacian = measure of sharpness
                const mean = sum / count;
                const variance = (sumSq / count) - (mean * mean);
                URL.revokeObjectURL(img.src);
                resolve(Math.max(0, variance));
            };
            img.onerror = () => resolve(999); // If we can't load it, let the server decide
            img.src = URL.createObjectURL(file);
        });
    }

    async function generateThumbnail(file, bbox) {
        if (!file || !bbox || bbox.length !== 4) return null;
        return new Promise((resolve) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                const [ymin, xmin, ymax, xmax] = bbox;
                const pad = 0.15;
                const padX = ((xmax - xmin) / 1000) * img.width * pad;
                const padY = ((ymax - ymin) / 1000) * img.height * pad;
                const sx = Math.max(0, (xmin / 1000) * img.width - padX);
                const sy = Math.max(0, (ymin / 1000) * img.height - padY);
                const ex = Math.min(img.width, (xmax / 1000) * img.width + padX);
                const ey = Math.min(img.height, (ymax / 1000) * img.height + padY);
                const sw = ex - sx;
                const sh = ey - sy;
                if (sw <= 0 || sh <= 0) { resolve(null); return; }
                const maxSize = 800;
                const scale = Math.min(maxSize / sw, maxSize / sh, 1);
                canvas.width = Math.round(sw * scale);
                canvas.height = Math.round(sh * scale);
                ctx.drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
                resolve(canvas.toDataURL('image/jpeg', 0.85));
            };
            img.src = URL.createObjectURL(file);
        });
    }

    async function renderResults(items, scanSummary) {
        scanningState.classList.add('hidden');
        resultsSection.classList.remove('hidden');
        cardsContainer.innerHTML = '';
        dropZone.style.backgroundImage = 'none';

        if (items.length === 0) {
            cardsContainer.innerHTML = '<p style="color:var(--text-muted); text-align:center; padding:2rem;">No items identified. Try a different angle.</p>';
            return;
        }

        // ── Scan Intelligence Banner ──
        if (scanSummary && scanSummary.total > 0) {
            const banner = document.createElement('div');
            banner.className = 'scan-intelligence-banner';
            banner.innerHTML = `
                <div class="sib-header">
                    <i class="ri-brain-line"></i>
                    <span>Scan Intelligence</span>
                </div>
                <div class="sib-stats">
                    <div class="sib-stat sib-auto">
                        <span class="sib-count">${scanSummary.auto_saved_count || 0}</span>
                        <span class="sib-label"><i class="ri-checkbox-circle-fill"></i> Auto-Saved</span>
                    </div>
                    <div class="sib-stat sib-review">
                        <span class="sib-count">${scanSummary.needs_review_count || 0}</span>
                        <span class="sib-label"><i class="ri-alert-line"></i> Needs Review</span>
                    </div>
                    <div class="sib-stat sib-total">
                        <span class="sib-count">${scanSummary.total}</span>
                        <span class="sib-label">Total Items</span>
                    </div>
                </div>
                ${scanSummary.auto_saved_count > 0 ? `<p class="sib-note">Items with ≥${scanSummary.threshold}% confidence were auto-saved to your inventory.</p>` : ''}
            `;
            cardsContainer.appendChild(banner);
        }

        // ── Selection Toolbar ──
        const selToolbar = document.createElement('div');
        selToolbar.className = 'selection-toolbar';
        selToolbar.innerHTML = `
            <div class="sel-toolbar-left">
                <button class="sel-btn" id="sel-all-btn"><i class="ri-checkbox-multiple-line"></i> Select All</button>
                <button class="sel-btn" id="desel-all-btn"><i class="ri-checkbox-blank-line"></i> Deselect All</button>
                <button class="sel-btn sel-btn-review" id="sel-review-btn"><i class="ri-alert-line"></i> Select Review Items</button>
            </div>
            <div class="sel-toolbar-right">
                <span id="sel-count-label" class="sel-count-label">0 selected</span>
            </div>
        `;
        cardsContainer.appendChild(selToolbar);

        const categoryTree = groupByCategory(items);
        let delayIndex = 0;

        Object.keys(categoryTree).sort().forEach(mainCat => {
            const mainSection = document.createElement('div');
            mainSection.className = 'tree-section';

            let subCatHtml = '';
            Object.keys(categoryTree[mainCat]).sort().forEach(subCat => {
                const subItems = categoryTree[mainCat][subCat];
                let itemsHtml = subItems.map((item) => {
                    const cond = (item.condition || 'Good').toLowerCase();
                    let badgeClass = 'badge-good';
                    if (cond.includes('excellent')) badgeClass = 'badge-excellent';
                    else if (cond.includes('fair')) badgeClass = 'badge-fair';
                    else if (cond.includes('poor') || cond.includes('damaged')) badgeClass = 'badge-poor';

                    const confidence = item.confidence_score || 0;
                    let confColor = '#10b981'; // green
                    if (confidence < 50) confColor = '#ef4444'; // red
                    else if (confidence < 70) confColor = '#f59e0b'; // yellow

                    const qty = item.quantity || 1;
                    const qtyBadge = qty > 1 ? `<span class="qty-badge">×${qty}</span>` : '';
                    const setPill = item.is_set ? '<span class="set-pill">SET</span>' : '';

                    // Format resale price for the header
                    const displayPrice = item.resale_value_usd || `$${(item.estimated_price_usd || 0).toLocaleString()}`;

                    // Determine the card status
                    const isAutoSaved = item._status === 'auto_saved' || item.auto_saved === true;
                    const hasDbId = item.id && !item.id.toString().startsWith('item-');
                    const cardClass = isAutoSaved ? 'asset-card card-auto-saved' : (item._status === 'needs_review' ? 'asset-card card-needs-review' : 'asset-card');

                    // Status bar HTML
                    let statusBar = '';
                    if (isAutoSaved) {
                        statusBar = `<div class="card-status-bar status-auto-saved">
                            <i class="ri-checkbox-circle-fill"></i> Auto-Saved to Inventory
                        </div>`;
                    } else if (item._status === 'needs_review') {
                        statusBar = `<div class="card-status-bar status-needs-review">
                            <i class="ri-alert-line"></i> Review Required
                            ${item.review_reason ? `<span class="review-reason">${item.review_reason}</span>` : ''}
                        </div>`;
                    }

                    // Action buttons based on status
                    let actionButtons = '';
                    if (isAutoSaved || hasDbId) {
                        actionButtons = `
                            <button class="action-btn btn-secondary-action archive-item-btn" data-id="${item.id}" data-tempid="${item.tempId}">
                                <i class="ri-archive-line"></i> ${item.is_archived ? 'Restore' : 'Archive'}
                            </button>
                            <button class="action-btn btn-primary-action sell-item-btn sell-btn" data-id="${item.id}">
                                <i class="ri-money-dollar-circle-line"></i> Sell
                            </button>
                        `;
                    } else {
                        actionButtons = `
                            <button class="action-btn btn-primary-action save-item-btn" data-index="${items.indexOf(item)}" data-tempid="${item.tempId}">
                                <i class="ri-save-line"></i> Save Asset
                            </button>
                        `;
                    }

                    return `
                    <div class="${cardClass}" data-id="${item.tempId}" data-item-index="${items.indexOf(item)}" data-status="${item._status || 'saved'}">
                        <div class="card-select-overlay">
                            <input type="checkbox" class="item-select-chk" data-tempid="${item.tempId}" data-index="${items.indexOf(item)}">
                        </div>
                        ${statusBar}
                        <div class="asset-thumbnail-container">
                            <img src="${item.thumbnail_url || '/static/HOLOS.jpg'}" class="asset-thumbnail">
                            <span class="condition-badge ${badgeClass}">${item.condition || 'Good'}</span>
                            ${qtyBadge}
                            ${setPill}
                        </div>
                        <div class="asset-content">
                            <div class="card-header">
                                <h4 class="item-name">${item.name || 'Unnamed Object'}</h4>
                                <span class="price-tag">${displayPrice}</span>
                            </div>
                            <div class="card-body">
                                <div class="detail-row">
                                    <span class="detail-label">Brand / Model</span>
                                    <span class="detail-value">${item.make || 'Unknown'} ${item.model || ''}</span>
                                </div>
                                <div class="detail-row">
                                    <span class="detail-label">Dimensions</span>
                                    <span class="detail-value">${item.estimated_dimensions || 'Not specified'}</span>
                                </div>
                                ${item.estimated_age_years ? `
                                <div class="detail-row">
                                    <span class="detail-label">Age</span>
                                    <span class="detail-value">${item.estimated_age_years}</span>
                                </div>` : ''}
                                ${item.condition_notes ? `
                                <div class="detail-row">
                                    <span class="detail-label">Notes</span>
                                    <span class="detail-value" style="font-size:0.8rem;color:var(--text-muted)">${item.condition_notes}</span>
                                </div>` : ''}
                                <div class="pricing-grid">
                                    <div class="pricing-tier">
                                        <span class="tier-label">Resale</span>
                                        <span class="tier-value tier-resale">${item.resale_value_usd || 'N/A'}</span>
                                    </div>
                                    <div class="pricing-tier">
                                        <span class="tier-label">Retail</span>
                                        <span class="tier-value">${item.retail_replacement_usd || 'N/A'}</span>
                                    </div>
                                    <div class="pricing-tier">
                                        <span class="tier-label">Insurance</span>
                                        <span class="tier-value tier-insurance">${item.insurance_replacement_usd || 'N/A'}</span>
                                    </div>
                                </div>
                                ${item.price_basis ? `
                                <div class="price-basis">
                                    <i class="ri-information-line"></i> ${item.price_basis}
                                </div>` : ''}
                                <div class="detail-row" style="margin-top:0.75rem">
                                    <span class="detail-label">Confidence</span>
                                    <span class="detail-value">
                                        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${confColor};margin-right:0.4rem"></span>
                                        ${confidence}%${item.identification_basis ? ' — ' + item.identification_basis : ''}
                                    </span>
                                </div>
                                <div class="detail-row">
                                    <span class="detail-label">Packed</span>
                                    <span class="detail-value">
                                        <input type="checkbox" class="is-packed-toggle" data-id="${item.id}" ${item.is_packed ? 'checked' : ''}>
                                    </span>
                                </div>
                                <div class="asset-actions" id="actions-${item.tempId}">
                                    ${actionButtons}
                                </div>
                            </div>
                        </div>
                    </div>`;
                }).join('');

                subCatHtml += `
                    <div class="tree-subsection">
                        <div class="subcat-title"><i class="ri-folder-reduce-line"></i> ${subCat} <span class="item-count">${subItems.length}</span></div>
                        <div class="subcat-items">${itemsHtml}</div>
                    </div>`;
            });

            mainSection.innerHTML = `
                <div class="tree-header accordion-trigger">
                    <h3><i class="ri-home-4-line"></i> ${mainCat} <span class="header-count">${Object.values(categoryTree[mainCat]).flat().length}</span></h3>
                    <i class="ri-arrow-down-s-line chevron"></i>
                </div>
                <div class="tree-content">${subCatHtml}</div>`;
            cardsContainer.appendChild(mainSection);
        });

        // ── Floating Bulk Action Bar ──
        let bulkBar = document.getElementById('bulk-action-bar');
        if (!bulkBar) {
            bulkBar = document.createElement('div');
            bulkBar.id = 'bulk-action-bar';
            bulkBar.className = 'bulk-action-bar hidden';
            bulkBar.innerHTML = `
                <div class="bulk-bar-info">
                    <i class="ri-checkbox-multiple-fill"></i>
                    <span id="bulk-count">0</span> items selected
                </div>
                <div class="bulk-bar-actions">
                    <button class="bulk-btn bulk-save-btn" id="bulk-save-btn"><i class="ri-save-line"></i> Save Selected</button>
                    <button class="bulk-btn bulk-archive-btn" id="bulk-archive-btn"><i class="ri-archive-line"></i> Archive Selected</button>
                </div>
            `;
            document.body.appendChild(bulkBar);
        }

        // ── Selection Logic ──
        function updateSelectionCount() {
            const checked = document.querySelectorAll('.item-select-chk:checked');
            const count = checked.length;
            const countLabel = document.getElementById('sel-count-label');
            const bulkCount = document.getElementById('bulk-count');
            if (countLabel) countLabel.textContent = `${count} selected`;
            if (bulkCount) bulkCount.textContent = count;
            if (bulkBar) {
                if (count > 0) bulkBar.classList.remove('hidden');
                else bulkBar.classList.add('hidden');
            }
            // Highlight selected cards
            document.querySelectorAll('.asset-card').forEach(card => {
                const chk = card.querySelector('.item-select-chk');
                if (chk?.checked) card.classList.add('card-selected');
                else card.classList.remove('card-selected');
            });
        }

        document.querySelectorAll('.item-select-chk').forEach(chk => {
            chk.addEventListener('change', updateSelectionCount);
        });

        document.getElementById('sel-all-btn')?.addEventListener('click', () => {
            document.querySelectorAll('.item-select-chk').forEach(c => { c.checked = true; });
            updateSelectionCount();
        });

        document.getElementById('desel-all-btn')?.addEventListener('click', () => {
            document.querySelectorAll('.item-select-chk').forEach(c => { c.checked = false; });
            updateSelectionCount();
        });

        document.getElementById('sel-review-btn')?.addEventListener('click', () => {
            document.querySelectorAll('.item-select-chk').forEach(c => { c.checked = false; }); // reset
            document.querySelectorAll('.asset-card[data-status="needs_review"]').forEach(card => {
                const chk = card.querySelector('.item-select-chk');
                if (chk) chk.checked = true;
            });
            updateSelectionCount();
        });

        // Bulk Save
        document.getElementById('bulk-save-btn')?.addEventListener('click', async () => {
            const checked = document.querySelectorAll('.item-select-chk:checked');
            const btn = document.getElementById('bulk-save-btn');
            btn.disabled = true;
            btn.innerHTML = '<i class="ri-loader-4-line ri-spin"></i> Saving...';
            let savedCount = 0;

            for (const chk of checked) {
                const index = parseInt(chk.getAttribute('data-index'));
                const tempId = chk.getAttribute('data-tempid');
                const item = currentScanItems[index];
                // Skip already-saved items
                if (item && (item._status === 'needs_review' || (!item.auto_saved && (!item.id || item.id.toString().startsWith('item-'))))) {
                    const itemData = {
                        ...item,
                        home_name: document.getElementById('home-select')?.value || 'My House',
                        room_name: document.getElementById('room-select')?.value || 'Living Room'
                    };
                    const res = await saveItem(itemData);
                    if (res.success) {
                        savedCount++;
                        const saved = res.data;
                        item.id = saved.id;
                        item._status = 'auto_saved';
                        item.auto_saved = true;

                        // Update the card visually
                        const card = document.querySelector(`.asset-card[data-id="${tempId}"]`);
                        if (card) {
                            card.classList.remove('card-needs-review');
                            card.classList.add('card-auto-saved');
                            // Replace status bar
                            const oldBar = card.querySelector('.card-status-bar');
                            if (oldBar) oldBar.outerHTML = `<div class="card-status-bar status-auto-saved"><i class="ri-checkbox-circle-fill"></i> Saved to Inventory</div>`;
                            // Replace action buttons
                            const actionsEl = document.getElementById(`actions-${tempId}`);
                            if (actionsEl) {
                                actionsEl.innerHTML = `
                                    <button class="action-btn btn-secondary-action archive-item-btn" data-id="${saved.id}" data-tempid="${tempId}">
                                        <i class="ri-archive-line"></i> Archive
                                    </button>
                                    <button class="action-btn btn-primary-action sell-item-btn sell-btn" data-id="${saved.id}">
                                        <i class="ri-money-dollar-circle-line"></i> Sell
                                    </button>
                                `;
                            }
                        }
                    }
                }
                chk.checked = false;
            }

            btn.disabled = false;
            btn.innerHTML = '<i class="ri-save-line"></i> Save Selected';
            updateSelectionCount();
            bindItemActions();  // rebind after DOM updates
            if (savedCount > 0) alert(`✓ ${savedCount} items saved to inventory!`);
        });

        // Bulk Archive
        document.getElementById('bulk-archive-btn')?.addEventListener('click', async () => {
            const checked = document.querySelectorAll('.item-select-chk:checked');
            const btn = document.getElementById('bulk-archive-btn');
            btn.disabled = true;
            btn.innerHTML = '<i class="ri-loader-4-line ri-spin"></i> Archiving...';
            let archivedCount = 0;

            for (const chk of checked) {
                const tempId = chk.getAttribute('data-tempid');
                const index = parseInt(chk.getAttribute('data-index'));
                const item = currentScanItems[index];
                if (item?.id && !item.id.toString().startsWith('item-')) {
                    await archiveItem(item.id, tempId);
                    archivedCount++;
                }
            }

            btn.disabled = false;
            btn.innerHTML = '<i class="ri-archive-line"></i> Archive Selected';
            updateSelectionCount();
            if (archivedCount > 0) alert(`✓ ${archivedCount} items archived!`);
        });

        bindItemActions();
        applyTiltEffect();
        applyAccordionLogic();
    }

    function bindItemActions() {
        document.querySelectorAll('.save-item-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const btnEl = e.currentTarget;
                const index = btnEl.getAttribute('data-index');
                const tempId = btnEl.getAttribute('data-tempid');
                const itemData = {
                    ...currentScanItems[index],
                    home_name: getLocationValue('home-select', 'home-custom-input'),
                    room_name: getLocationValue('room-select', 'room-custom-input')
                };
                btnEl.disabled = true;
                btnEl.innerHTML = '<i class="ri-loader-4-line ri-spin"></i> Saving...';
                const res = await saveItem(itemData);
                if (res.success) {
                    const saved = res.data;
                    document.getElementById(`actions-${tempId}`).innerHTML = `
                        <button class="action-btn btn-secondary-action archive-item-btn" data-id="${saved.id}" data-tempid="${tempId}">
                            <i class="ri-archive-line"></i> Archive
                        </button>
                        <button class="action-btn btn-primary-action sell-item-btn sell-btn" data-id="${saved.id}">
                            <i class="ri-money-dollar-circle-line"></i> Sell
                        </button>
                    `;
                    bindItemActions(); // Rebind
                }
            });
        });

        document.querySelectorAll('.archive-item-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const itemId = e.currentTarget.getAttribute('data-id');
                const tempId = e.currentTarget.getAttribute('data-tempid');
                await archiveItem(itemId, tempId);
            });
        });

        document.querySelectorAll('.sell-item-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                generateResaleListing(e.currentTarget.getAttribute('data-id'));
            });
        });

        document.querySelectorAll('.is-packed-toggle').forEach(chk => {
            chk.addEventListener('change', async (e) => {
                const itemId = e.currentTarget.getAttribute('data-id');
                if (!itemId || itemId.startsWith('item-')) return;
                const res = await fetch(`/api/items/${itemId}/update`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_packed: e.currentTarget.checked })
                });
            });
        });
    }

    function applyTiltEffect() {
        // Tilt removed — CSS hover handles lift/glow without 3D rotation jitter
    }

    function applyAccordionLogic() {
        document.querySelectorAll('.accordion-trigger').forEach(trigger => {
            trigger.addEventListener('click', () => {
                const content = trigger.nextElementSibling;
                trigger.classList.toggle('active');
                if (content.style.maxHeight) {
                    content.style.maxHeight = null;
                    content.classList.remove('is-open');
                } else {
                    content.style.maxHeight = content.scrollHeight + "px";
                    content.classList.add('is-open');
                }
            });
        });
        const first = document.querySelector('.accordion-trigger');
        if (first && !first.classList.contains('active')) first.click();
    }

    async function saveItem(itemData) {
        const sessionStr = localStorage.getItem('holos_session');
        const sess = sessionStr ? JSON.parse(sessionStr) : null;
        if (!sess) return { success: false, error: "Not logged in" };
        const toSave = { ...itemData };
        delete toSave.thumbnail_url; delete toSave.id;
        try {
            const r = await fetch('/api/items/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${sess.access_token}` },
                body: JSON.stringify(toSave)
            });
            const res = await r.json();
            return r.ok ? { success: true, data: res.data } : { success: false };
        } catch (e) { return { success: false }; }
    }

    async function archiveItem(itemId, tempId) {
        const sessionStr = localStorage.getItem('holos_session');
        const sess = sessionStr ? JSON.parse(sessionStr) : null;
        if (!itemId || itemId.startsWith('item-')) {
            document.querySelector(`.asset-card[data-id="${tempId}"]`)?.remove();
            return;
        }
        await fetch(`/api/items/${itemId}/archive`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${sess.access_token}` }
        });
        document.querySelector(`.asset-card[data-id="${tempId}"]`)?.remove();
    }

    async function generateResaleListing(itemId) {
        if (!itemId || itemId.startsWith('item-')) {
            alert('Save the item first!'); return;
        }
        openModal('<div style="text-align:center; padding:3rem;"><i class="ri-loader-4-line ri-spin" style="font-size:3rem; color:var(--primary)"></i><p style="margin-top:1rem;">AI is crafting your marketplace listing...</p></div>');
        try {
            const r = await fetch(`/api/items/${itemId}/resale`);
            const d = await r.json();
            if (d.success) {
                const listing = d.listing;
                modalBody.innerHTML = `
                    <div class="ai-listing-view">
                        <h2 style="color:var(--primary); margin-bottom:1.5rem;"><i class="ri-magic-line"></i> AI Sales Pitch</h2>
                        <div style="margin-bottom:1.5rem;">
                            <label style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px;">Suggested Title</label>
                            <div class="copy-box">${listing.listing_title}</div>
                        </div>
                        <div style="margin-bottom:1.5rem;">
                            <label style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px;">Listing Description</label>
                            <div class="copy-box" style="white-space:pre-wrap;">${listing.listing_description}</div>
                        </div>
                        <button class="auth-btn" id="copy-listing-btn" style="width:100%">Copy Description</button>
                    </div>
                `;
                document.getElementById('copy-listing-btn').addEventListener('click', () => {
                    navigator.clipboard.writeText(listing.listing_description);
                    alert('Copied!');
                });
            }
        } catch (e) { modalBody.innerHTML = '<p>AI service error.</p>'; }
    }

    async function fetchGlobalItems(query = '', showArchived = false) {
        const sessionStr = localStorage.getItem('holos_session');
        if (!sessionStr) return;
        const sess = JSON.parse(sessionStr);
        const res = await fetch(`/api/items?q=${encodeURIComponent(query)}&archived=${showArchived}`, {
            headers: { 'Authorization': `Bearer ${sess.access_token}` }
        });
        const data = await res.json();
        if (data.success) {
            const taggedData = data.data.map((item, idx) => ({
                ...item,
                tempId: item.id || `global-${idx}`,
                name: `${item.name} (${item.home_name} - ${item.room_name})`
            }));
            renderResults(taggedData);
            dropZone.parentElement.classList.add('hidden');
        }
    }

    function openModal(html) {
        modalBody.innerHTML = safeHTML(html);
        modalOverlay.classList.remove('hidden');
    }

    closeModalBtn?.addEventListener('click', () => modalOverlay.classList.add('hidden'));

    // Auth & Navigation
    myInventoryBtn?.addEventListener('click', () => {
        appMode = 'inventory';
        fetchGlobalItems();
    });

    if (generateReportBtn) {
        generateReportBtn.addEventListener('click', async () => {
            const sessionStr = localStorage.getItem('holos_session');
            const sess = sessionStr ? JSON.parse(sessionStr) : null;
            const headers = {};
            if (sess?.access_token) {
                headers['Authorization'] = `Bearer ${sess.access_token}`;
            }

            openModal('<div style="text-align:center; padding:3rem;"><i class="ri-loader-4-line ri-spin" style="font-size:3rem; color:var(--primary)"></i><p style="margin-top:1rem;">Generating your estate report…</p></div>');

            try {
                const r = await fetch('/api/reports/estate', { headers });
                const d = await r.json();
                if (!d.success) {
                    modalBody.innerHTML = `<p style="color:#ef4444; text-align:center; padding:2rem;">Error: ${d.error || 'Could not load report'}</p>`;
                    return;
                }

                // Store raw report data for filtering
                const reportData = d;
                const properties = d.properties || {};

                // Helper: parse a price string like "$120-$150" or "$200" into a number
                const parseVal = (v) => {
                    if (typeof v === 'number') return v;
                    if (!v || v === 'N/A') return 0;
                    const nums = String(v).replace(/[$,]/g, '').match(/[\d.]+/g);
                    return nums ? parseFloat(nums[nums.length - 1]) : 0;
                };
                const fmt = (v) => '$' + (v || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });

                // Flatten all items with location metadata for filtering
                const allItems = [];
                const allCategories = new Set();
                const allHomes = new Set();
                const allRooms = new Set();

                Object.entries(properties).forEach(([homeName, rooms]) => {
                    allHomes.add(homeName);
                    Object.entries(rooms).forEach(([roomName, roomData]) => {
                        allRooms.add(roomName);
                        roomData.items.forEach(item => {
                            allCategories.add(item.category || 'Other');
                            allItems.push({
                                ...item,
                                _home: homeName,
                                _room: roomName,
                                _resale: parseVal(item.resale_price_range),
                                _retail: parseVal(item.retail_replacement_cost),
                                _insurance: parseVal(item.insurance_replacement_value),
                            });
                        });
                    });
                });

                // Render function — called on initial load and on filter change
                function renderReport(filterCat, filterHome, filterRoom) {
                    // Apply filters
                    let filtered = allItems;
                    if (filterCat) filtered = filtered.filter(i => (i.category || 'Other') === filterCat);
                    if (filterHome) filtered = filtered.filter(i => i._home === filterHome);
                    if (filterRoom) filtered = filtered.filter(i => i._room === filterRoom);

                    // Compute KPIs from filtered items
                    const totalMarket = filtered.reduce((s, i) => s + (i.price || 0), 0);
                    const totalResale = filtered.reduce((s, i) => s + i._resale, 0);
                    const totalRetail = filtered.reduce((s, i) => s + i._retail, 0);
                    const totalInsurance = filtered.reduce((s, i) => s + i._insurance, 0);
                    const totalItems = filtered.length;

                    // Rebuild properties structure from filtered items
                    const filteredProps = {};
                    const filteredCats = {};
                    filtered.forEach(item => {
                        const h = item._home;
                        const r = item._room;
                        if (!filteredProps[h]) filteredProps[h] = {};
                        if (!filteredProps[h][r]) filteredProps[h][r] = { items: [], subtotal: 0, total_insurance_value: 0 };
                        filteredProps[h][r].items.push(item);
                        filteredProps[h][r].subtotal += (item.price || 0);
                        filteredProps[h][r].total_insurance_value += item._insurance;

                        const cat = item.category || 'Other';
                        if (!filteredCats[cat]) filteredCats[cat] = { value: 0, count: 0, resale: 0, retail: 0, insurance: 0 };
                        filteredCats[cat].value += (item.price || 0);
                        filteredCats[cat].count += 1;
                        filteredCats[cat].resale += item._resale;
                        filteredCats[cat].retail += item._retail;
                        filteredCats[cat].insurance += item._insurance;
                    });

                    const numProps = Object.keys(filteredProps).length;
                    const numRooms = Object.values(filteredProps).reduce((s, rooms) => s + Object.keys(rooms).length, 0);
                    const cats = Object.entries(filteredCats).sort((a, b) => b[1].value - a[1].value);
                    const maxCatVal = cats.length > 0 ? cats[0][1].value : 1;
                    const catColors = ['#00d2ff','#3a7bd5','#f59e0b','#ef4444','#a855f7','#eab308','#ec4899','#64748b','#22c55e','#6b7280'];

                    // Build filter dropdowns
                    const catOpts = [...allCategories].sort().map(c => `<option value="${c}" ${filterCat === c ? 'selected' : ''}>${c}</option>`).join('');
                    const homeOpts = [...allHomes].sort().map(h => `<option value="${h}" ${filterHome === h ? 'selected' : ''}>${h}</option>`).join('');
                    const roomOpts = [...allRooms].sort().map(r => `<option value="${r}" ${filterRoom === r ? 'selected' : ''}>${r}</option>`).join('');

                    const selectStyle = 'background:var(--card-bg); color:var(--text-main); border:1px solid var(--card-border); border-radius:8px; padding:6px 10px; font-size:0.8rem; flex:1; min-width:0; cursor:pointer;';

                    let html = `<div class="report-view" style="padding:1.5rem;">
                        <div style="text-align:center; margin-bottom:1rem;">
                            <h2 style="color:var(--primary); margin:0 0 0.25rem 0;"><i class="ri-file-chart-line"></i> Estate Value Report</h2>
                            <p style="color:var(--text-muted); font-size:0.85rem;">Generated ${reportData.report_date}</p>
                        </div>

                        <!-- Filter Bar -->
                        <div style="display:flex; gap:8px; margin-bottom:1rem; flex-wrap:wrap; align-items:center;">
                            <span style="color:var(--text-muted); font-size:0.75rem; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;"><i class="ri-filter-3-line"></i> Filter:</span>
                            <select id="rpt-filter-cat" style="${selectStyle}">
                                <option value="">All Categories</option>${catOpts}
                            </select>
                            <select id="rpt-filter-home" style="${selectStyle}">
                                <option value="">All Properties</option>${homeOpts}
                            </select>
                            <select id="rpt-filter-room" style="${selectStyle}">
                                <option value="">All Rooms</option>${roomOpts}
                            </select>
                            <button id="rpt-clear-filters" style="background:rgba(239,68,68,0.1); color:#ef4444; border:1px solid rgba(239,68,68,0.3); border-radius:8px; padding:6px 12px; font-size:0.75rem; font-weight:600; cursor:pointer;">Clear</button>
                        </div>

                        <!-- KPI Cards -->
                        <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:10px; margin-bottom:1rem;">
                            <div style="background:var(--card-bg); border:1px solid var(--card-border); border-radius:12px; padding:14px; text-align:center;">
                                <div style="font-size:1.2rem;">💎</div>
                                <div style="font-size:1.2rem; font-weight:800; color:#2ecc71;">${fmt(totalMarket)}</div>
                                <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px;">Market Value</div>
                            </div>
                            <div style="background:var(--card-bg); border:1px solid var(--card-border); border-radius:12px; padding:14px; text-align:center;">
                                <div style="font-size:1.2rem;">📦</div>
                                <div style="font-size:1.2rem; font-weight:800; color:var(--primary);">${totalItems}</div>
                                <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px;">Items</div>
                            </div>
                            <div style="background:var(--card-bg); border:1px solid var(--card-border); border-radius:12px; padding:14px; text-align:center;">
                                <div style="font-size:1.2rem;">🏠</div>
                                <div style="font-size:1.2rem; font-weight:800; color:#a855f7;">${numProps} / ${numRooms}</div>
                                <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px;">Properties / Rooms</div>
                            </div>
                        </div>
                        <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:10px; margin-bottom:1.5rem;">
                            <div style="background:rgba(46,204,113,0.06); border:1px solid rgba(46,204,113,0.15); border-radius:12px; padding:14px; text-align:center;">
                                <div style="font-size:1.2rem;">🔄</div>
                                <div style="font-size:1.1rem; font-weight:800; color:#2ecc71;">${fmt(totalResale)}</div>
                                <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px;">Resale Value</div>
                            </div>
                            <div style="background:rgba(0,210,255,0.06); border:1px solid rgba(0,210,255,0.15); border-radius:12px; padding:14px; text-align:center;">
                                <div style="font-size:1.2rem;">🏷</div>
                                <div style="font-size:1.1rem; font-weight:800; color:#00d2ff;">${fmt(totalRetail)}</div>
                                <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px;">Retail Replace</div>
                            </div>
                            <div style="background:rgba(245,158,11,0.06); border:1px solid rgba(245,158,11,0.15); border-radius:12px; padding:14px; text-align:center;">
                                <div style="font-size:1.2rem;">🛡</div>
                                <div style="font-size:1.1rem; font-weight:800; color:#f59e0b;">${fmt(totalInsurance)}</div>
                                <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px;">Insurance Value</div>
                            </div>
                        </div>`;

                    // Category breakdown
                    if (cats.length > 0) {
                        html += `<div style="margin-bottom:1.5rem;">
                            <h3 style="color:var(--text-main); font-size:1rem; font-weight:700; margin-bottom:12px;">Value by Category</h3>`;
                        cats.forEach(([name, data], i) => {
                            const pct = Math.max((data.value / maxCatVal) * 100, 3);
                            const color = catColors[i % catColors.length];
                            html += `
                                <div style="margin-bottom:12px; cursor:pointer;" class="rpt-cat-row" data-cat="${name}">
                                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:4px;">
                                        <div style="display:flex; align-items:center; gap:8px;">
                                            <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block;"></span>
                                            <span style="color:var(--text-main); font-size:0.85rem; font-weight:600;">${name}</span>
                                            <span style="color:var(--text-muted); font-size:0.7rem;">${data.count} item${data.count !== 1 ? 's' : ''}</span>
                                        </div>
                                        <div style="display:flex; gap:12px; align-items:center;">
                                            <span style="color:var(--text-muted); font-size:0.7rem;">R: ${fmt(data.resale)}</span>
                                            <span style="color:var(--text-muted); font-size:0.7rem;">I: ${fmt(data.insurance)}</span>
                                            <span style="color:#2ecc71; font-size:0.85rem; font-weight:700;">${fmt(data.value)}</span>
                                        </div>
                                    </div>
                                    <div style="height:5px; background:rgba(255,255,255,0.04); border-radius:3px; overflow:hidden;">
                                        <div style="height:100%; width:${pct}%; background:${color}; border-radius:3px; opacity:0.7;"></div>
                                    </div>
                                </div>`;
                        });
                        html += `</div>`;
                    }

                    // Property / Room breakdown with collapsible sections
                    html += `<h3 style="color:var(--text-main); font-size:1rem; font-weight:700; margin-bottom:12px;">Detailed Breakdown</h3>`;
                    let propIdx = 0;
                    Object.entries(filteredProps).forEach(([propName, rooms]) => {
                        const propTotal = Object.values(rooms).reduce((s, r) => s + r.subtotal, 0);
                        const propIns = Object.values(rooms).reduce((s, r) => s + r.total_insurance_value, 0);
                        const propResale = Object.values(rooms).reduce((s, r) => r.items.reduce((rs, i) => rs + i._resale, 0) + s, 0);
                        const propRetail = Object.values(rooms).reduce((s, r) => r.items.reduce((rs, i) => rs + i._retail, 0) + s, 0);
                        const propItems = Object.values(rooms).reduce((s, r) => s + r.items.length, 0);
                        const propId = `rpt-prop-${propIdx++}`;

                        html += `<div style="background:var(--card-bg); border:1px solid var(--card-border); border-radius:12px; margin-bottom:12px; overflow:hidden;">
                            <div class="rpt-prop-toggle" data-target="${propId}" style="display:flex; align-items:center; padding:14px 16px; cursor:pointer; user-select:none;">
                                <span style="font-size:1.3rem; margin-right:10px;">🏠</span>
                                <div style="flex:1;">
                                    <div style="color:var(--text-main); font-weight:700;">${propName}</div>
                                    <div style="color:var(--text-muted); font-size:0.7rem;">${propItems} items · ${Object.keys(rooms).length} room${Object.keys(rooms).length !== 1 ? 's' : ''} · Market: ${fmt(propTotal)} · Resale: ${fmt(propResale)} · Retail: ${fmt(propRetail)}</div>
                                </div>
                                <span style="background:rgba(245,158,11,0.12); color:#f59e0b; border:1px solid rgba(245,158,11,0.2); border-radius:6px; padding:2px 8px; font-size:0.7rem; font-weight:700; margin-right:8px;">🛡 ${fmt(propIns)}</span>
                                <i class="ri-arrow-down-s-line rpt-chevron" style="color:var(--text-muted); font-size:1.2rem; transition:transform 0.2s;"></i>
                            </div>
                            <div id="${propId}" class="rpt-collapsible" style="display:block;">`;

                        let roomIdx = 0;
                        Object.entries(rooms).forEach(([roomName, roomData]) => {
                            const roomId = `${propId}-room-${roomIdx++}`;
                            const roomResale = roomData.items.reduce((s, i) => s + i._resale, 0);
                            const roomRetail = roomData.items.reduce((s, i) => s + i._retail, 0);

                            html += `<div style="border-top:1px solid rgba(255,255,255,0.04);">
                                <div class="rpt-room-toggle" data-target="${roomId}" style="display:flex; justify-content:space-between; align-items:center; padding:10px 16px; cursor:pointer; user-select:none;">
                                    <div style="display:flex; align-items:center; gap:6px;">
                                        <i class="ri-arrow-right-s-line rpt-chevron" style="color:var(--text-muted); font-size:1rem; transition:transform 0.2s;"></i>
                                        <span style="color:var(--text-main); font-weight:600; font-size:0.9rem;">🚪 ${roomName}</span>
                                    </div>
                                    <div style="display:flex; gap:10px; align-items:center;">
                                        <span style="color:var(--text-muted); font-size:0.75rem;">${roomData.items.length} item${roomData.items.length !== 1 ? 's' : ''}</span>
                                        <span style="color:#2ecc71; font-weight:700; font-size:0.9rem;">${fmt(roomData.subtotal)}</span>
                                    </div>
                                </div>
                                <div id="${roomId}" class="rpt-collapsible" style="display:none; padding:0 16px 12px 16px;">
                                    <div style="display:flex; gap:8px; margin-bottom:8px; flex-wrap:wrap;">
                                        <span style="background:rgba(46,204,113,0.08); border:1px solid rgba(46,204,113,0.15); border-radius:6px; padding:3px 8px; font-size:0.7rem; color:#2ecc71; font-weight:600;">🔄 Resale: ${fmt(roomResale)}</span>
                                        <span style="background:rgba(0,210,255,0.08); border:1px solid rgba(0,210,255,0.15); border-radius:6px; padding:3px 8px; font-size:0.7rem; color:#00d2ff; font-weight:600;">🏷 Retail: ${fmt(roomRetail)}</span>
                                        <span style="background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.15); border-radius:6px; padding:3px 8px; font-size:0.7rem; color:#f59e0b; font-weight:600;">🛡 Insurance: ${fmt(roomData.total_insurance_value)}</span>
                                    </div>`;

                            roomData.items.forEach(item => {
                                html += `<div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.04); border-radius:8px; padding:10px; margin-bottom:6px;">
                                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                                        <div style="flex:1;">
                                            <div style="color:var(--text-main); font-weight:600; font-size:0.9rem;">${item.name}</div>
                                            <div style="color:var(--text-muted); font-size:0.75rem;">${[item.make, item.model].filter(Boolean).join(' · ') || item.category}${item.condition ? ' • ' + item.condition : ''}</div>
                                        </div>
                                        <span style="color:#2ecc71; font-weight:700; white-space:nowrap; margin-left:8px;">${fmt(item.price)}</span>
                                    </div>
                                    <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; margin-top:8px;">
                                        <div style="background:rgba(46,204,113,0.06); border:1px solid rgba(46,204,113,0.12); border-radius:6px; padding:6px; text-align:center;">
                                            <div style="font-size:0.6rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px;">Resale</div>
                                            <div style="font-size:0.8rem; font-weight:700; color:#2ecc71;">${item.resale_price_range || 'N/A'}</div>
                                        </div>
                                        <div style="background:rgba(0,210,255,0.06); border:1px solid rgba(0,210,255,0.12); border-radius:6px; padding:6px; text-align:center;">
                                            <div style="font-size:0.6rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px;">Retail</div>
                                            <div style="font-size:0.8rem; font-weight:700; color:#00d2ff;">${item.retail_replacement_cost || 'N/A'}</div>
                                        </div>
                                        <div style="background:rgba(245,158,11,0.06); border:1px solid rgba(245,158,11,0.12); border-radius:6px; padding:6px; text-align:center;">
                                            <div style="font-size:0.6rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px;">Insurance</div>
                                            <div style="font-size:0.8rem; font-weight:700; color:#f59e0b;">${item.insurance_replacement_value || 'N/A'}</div>
                                        </div>
                                    </div>
                                    ${item.estimated_age && item.estimated_age !== 'Unknown' ? `<div style="color:var(--text-muted); font-size:0.7rem; margin-top:4px;">Age: ~${item.estimated_age} yrs${item.detailed_condition_notes && item.detailed_condition_notes !== 'None' ? ' · ' + item.detailed_condition_notes : ''}</div>` : ''}
                                </div>`;
                            });

                            html += `</div></div>`;
                        });

                        html += `</div></div>`;
                    });

                    // Print button
                    html += `<div style="text-align:center; margin-top:1.5rem;">
                        <button class="auth-btn" onclick="window.print()" style="width:100%;"><i class="ri-printer-line"></i> Print / Export PDF</button>
                    </div></div>`;

                    modalBody.innerHTML = html;

                    // Bind collapsible toggles for properties
                    modalBody.querySelectorAll('.rpt-prop-toggle').forEach(toggle => {
                        toggle.addEventListener('click', () => {
                            const target = document.getElementById(toggle.dataset.target);
                            const chevron = toggle.querySelector('.rpt-chevron');
                            if (target.style.display === 'none') {
                                target.style.display = 'block';
                                chevron.style.transform = 'rotate(0deg)';
                            } else {
                                target.style.display = 'none';
                                chevron.style.transform = 'rotate(-90deg)';
                            }
                        });
                    });

                    // Bind collapsible toggles for rooms
                    modalBody.querySelectorAll('.rpt-room-toggle').forEach(toggle => {
                        toggle.addEventListener('click', () => {
                            const target = document.getElementById(toggle.dataset.target);
                            const chevron = toggle.querySelector('.rpt-chevron');
                            if (target.style.display === 'none') {
                                target.style.display = 'block';
                                chevron.style.transform = 'rotate(90deg)';
                            } else {
                                target.style.display = 'none';
                                chevron.style.transform = 'rotate(0deg)';
                            }
                        });
                    });

                    // Bind category row click to filter
                    modalBody.querySelectorAll('.rpt-cat-row').forEach(row => {
                        row.addEventListener('click', () => {
                            const cat = row.dataset.cat;
                            renderReport(cat, filterHome, filterRoom);
                        });
                    });

                    // Bind filter dropdowns
                    const catSelect = document.getElementById('rpt-filter-cat');
                    const homeSelect = document.getElementById('rpt-filter-home');
                    const roomSelect = document.getElementById('rpt-filter-room');
                    const clearBtn = document.getElementById('rpt-clear-filters');

                    catSelect?.addEventListener('change', () => renderReport(catSelect.value, homeSelect?.value, roomSelect?.value));
                    homeSelect?.addEventListener('change', () => renderReport(catSelect?.value, homeSelect.value, roomSelect?.value));
                    roomSelect?.addEventListener('change', () => renderReport(catSelect?.value, homeSelect?.value, roomSelect.value));
                    clearBtn?.addEventListener('click', () => renderReport('', '', ''));
                }

                // Initial render with no filters
                renderReport('', '', '');

            } catch (e) {
                modalBody.innerHTML = '<p style="color:#ef4444; text-align:center; padding:2rem;">Could not reach the server.</p>';
            }
        });
    }

    // ═══════════════════════════════════════════════════
    // LANDING PAGE AUTH FLOW
    // ═══════════════════════════════════════════════════

    const authOverlay = document.getElementById('auth-overlay');
    const authButtonsGroup = document.getElementById('auth-buttons-group');
    const authFormSection = document.getElementById('auth-form-section');
    const authForm = document.getElementById('auth-form');
    const authTitle = document.getElementById('auth-title');
    const authSubmitBtn = document.getElementById('auth-submit-btn');
    const authToggleText = document.getElementById('auth-toggle-text');
    const authToggleLink = document.getElementById('auth-toggle-link');
    const closeAuthBtn = document.getElementById('close-auth-btn');
    const showSigninBtn = document.getElementById('show-signin-btn');
    const showSignupBtn = document.getElementById('show-signup-btn');
    const quickTestBtn = document.getElementById('quick-test-btn');
    const fullnameGroup = document.getElementById('fullname-group');

    let isLoginMode = true;

    function showAuthForm(loginMode) {
        isLoginMode = loginMode;
        authButtonsGroup.classList.add('hidden');
        authFormSection.classList.remove('hidden');

        if (loginMode) {
            authTitle.textContent = 'Welcome Back';
            authSubmitBtn.textContent = 'Sign In';
            authToggleText.textContent = "Don't have an account?";
            authToggleLink.textContent = 'Sign Up';
            fullnameGroup?.classList.add('hidden');
        } else {
            authTitle.textContent = 'Create Account';
            authSubmitBtn.textContent = 'Sign Up';
            authToggleText.textContent = 'Already have an account?';
            authToggleLink.textContent = 'Sign In';
            fullnameGroup?.classList.remove('hidden');
        }
    }

    function hideAuthForm() {
        authFormSection.classList.add('hidden');
        authButtonsGroup.classList.remove('hidden');
    }

    showSigninBtn?.addEventListener('click', () => showAuthForm(true));
    showSignupBtn?.addEventListener('click', () => showAuthForm(false));
    closeAuthBtn?.addEventListener('click', hideAuthForm);

    authToggleLink?.addEventListener('click', (e) => {
        e.preventDefault();
        showAuthForm(!isLoginMode);
    });

    // Quick Demo: use server-side demo endpoint (no credentials in frontend source)
    quickTestBtn?.addEventListener('click', async () => {
        quickTestBtn.textContent = '⏳ Signing in...';
        quickTestBtn.disabled = true;
        try {
            const r = await fetch('/api/auth/demo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            const data = await r.json();
            if (data.success) {
                localStorage.setItem('holos_session', JSON.stringify(data.session));
                localStorage.setItem('holos_user', JSON.stringify(data.user));
                authOverlay.classList.add('hidden');
                onLoginSuccess(data.user);
            } else {
                alert('Demo login unavailable: ' + (data.error || 'Test accounts are disabled.'));
            }
        } catch (err) {
            alert('Could not reach server.');
        }
        quickTestBtn.textContent = '⚡ Quick Demo — Use Test Account';
        quickTestBtn.disabled = false;
    });

    // Auth form submit
    authForm?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;

        authSubmitBtn.disabled = true;
        authSubmitBtn.textContent = isLoginMode ? 'Signing In...' : 'Creating Account...';

        try {
            const endpoint = isLoginMode ? '/api/auth/login' : '/api/auth/register';
            const payload = { email, password };
            if (!isLoginMode) {
                payload.full_name = document.getElementById('full_name')?.value || '';
            }

            const r = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await r.json();

            if (data.success || data.user) {
                if (!isLoginMode) {
                    // After register, auto-login
                    const loginR = await fetch('/api/auth/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email, password })
                    });
                    const loginData = await loginR.json();
                    if (loginData.success) {
                        localStorage.setItem('holos_session', JSON.stringify(loginData.session));
                        localStorage.setItem('holos_user', JSON.stringify(loginData.user));
                        authOverlay.classList.add('hidden');
                        onLoginSuccess(loginData.user);
                    }
                } else {
                    localStorage.setItem('holos_session', JSON.stringify(data.session));
                    localStorage.setItem('holos_user', JSON.stringify(data.user));
                    authOverlay.classList.add('hidden');
                    onLoginSuccess(data.user);
                }
            } else {
                alert(data.error || 'Authentication failed.');
            }
        } catch (err) {
            alert('Connection error. Is the server running?');
        }

        authSubmitBtn.disabled = false;
        authSubmitBtn.textContent = isLoginMode ? 'Sign In' : 'Sign Up';
    });

    // On successful login
    function onLoginSuccess(user) {
        const name = user?.user_metadata?.full_name || user?.email?.split('@')[0] || 'User';

        // Show the entire app shell (sidebar + content)
        appShell?.classList.remove('hidden');

        // Populate sidebar user info
        const sidebarUserInfo = document.getElementById('sidebar-user-info');
        if (sidebarUserInfo) {
            sidebarUserInfo.innerHTML = `<span>👤 ${name}</span>`;
        }

        // Sidebar logout
        document.getElementById('sidebar-logout-btn')?.addEventListener('click', () => {
            localStorage.removeItem('holos_session');
            localStorage.removeItem('holos_user');
            window.location.reload();
        });

        // Legacy profile container (inside inventory tab)
        const profileContainer = document.getElementById('user-profile-container');
        if (profileContainer) {
            profileContainer.innerHTML = `
                <div style="display:flex; align-items:center; justify-content:center; gap:0.75rem; margin-bottom:1rem;">
                    <span style="color:var(--text-main); font-weight:600;">👤 ${name}</span>
                </div>
            `;
        }

        // Show location selector and action buttons (in inventory tab)
        document.getElementById('location-selector')?.classList.remove('hidden');
        myInventoryBtn?.classList.remove('hidden');
        generateReportBtn?.classList.remove('hidden');

        // Load dashboard data on login
        loadDashboardData();

        // --- Combo Selector Logic for Room (keep simple text input) ---
        function setupComboSelect(selectId, customInputId) {
            const sel = document.getElementById(selectId);
            const inp = document.getElementById(customInputId);
            if (!sel || !inp) return;

            sel.addEventListener('change', () => {
                if (sel.value === '__custom__') {
                    sel.classList.add('hidden');
                    inp.classList.remove('hidden');
                    inp.value = '';
                    inp.focus();
                }
            });

            function commitCustom() {
                const val = inp.value.trim();
                if (val) {
                    const existing = Array.from(sel.options).find(o => o.value === val);
                    if (!existing) {
                        const opt = document.createElement('option');
                        opt.value = val;
                        opt.textContent = val;
                        const customOpt = Array.from(sel.options).find(o => o.value === '__custom__');
                        sel.insertBefore(opt, customOpt);
                    }
                    sel.value = val;
                } else {
                    sel.value = sel.options[0].value;
                }
                inp.classList.add('hidden');
                sel.classList.remove('hidden');
            }

            inp.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); commitCustom(); }
                if (e.key === 'Escape') {
                    sel.value = sel.options[0].value;
                    inp.classList.add('hidden');
                    sel.classList.remove('hidden');
                }
            });
            inp.addEventListener('blur', commitCustom);
        }

        // Room selector keeps the simple combo
        setupComboSelect('room-select', 'room-custom-input');

        // --- Property Setup Modal (replaces simple home combo) ---
        const homeSelect = document.getElementById('home-select');
        const propertyModal = document.getElementById('property-modal-overlay');
        const closePropertyModal = document.getElementById('close-property-modal');
        const savePropertyBtn = document.getElementById('save-property-btn');
        const bedroomCount = document.getElementById('bedroom-count');
        const bathroomCount = document.getElementById('bathroom-count');
        const roomPreviewList = document.getElementById('room-preview-list');
        const propertyNameInput = document.getElementById('property-name');
        const propertyAddressInput = document.getElementById('property-address');

        // Load saved properties from localStorage
        const savedProperties = JSON.parse(localStorage.getItem('holos_properties') || '{}');
        Object.keys(savedProperties).forEach(name => {
            if (!Array.from(homeSelect.options).find(o => o.value === name)) {
                const opt = document.createElement('option');
                opt.value = name;
                opt.textContent = name;
                const customOpt = Array.from(homeSelect.options).find(o => o.value === '__custom__');
                homeSelect.insertBefore(opt, customOpt);
            }
        });

        // When switching homes, load that property's rooms into the room selector
        homeSelect.addEventListener('change', () => {
            if (homeSelect.value === '__custom__') {
                // Open property setup modal instead of a text input
                propertyModal.classList.remove('hidden');
                homeSelect.value = homeSelect.options[0].value; // reset dropdown
                updateRoomPreview();
                return;
            }
            const prop = savedProperties[homeSelect.value];
            if (prop && prop.rooms) {
                populateRoomSelector(prop.rooms);
            }
        });

        closePropertyModal?.addEventListener('click', () => {
            propertyModal.classList.add('hidden');
        });

        // Counter buttons (+/-)
        document.querySelectorAll('.counter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const target = document.getElementById(btn.dataset.target);
                const dir = parseInt(btn.dataset.dir);
                const current = parseInt(target.textContent);
                const newVal = Math.max(0, Math.min(10, current + dir));
                target.textContent = newVal;
                updateRoomPreview();
            });
        });

        // Room toggles — update preview on change
        document.querySelectorAll('.room-toggle input').forEach(chk => {
            chk.addEventListener('change', updateRoomPreview);
        });

        function generateRoomList() {
            const rooms = [];
            const bedrooms = parseInt(bedroomCount.textContent);
            const bathrooms = parseInt(bathroomCount.textContent);

            // Generate bedrooms
            if (bedrooms === 1) {
                rooms.push('Master Bedroom');
            } else {
                for (let i = 1; i <= bedrooms; i++) {
                    rooms.push(i === 1 ? 'Master Bedroom' : `Bedroom ${i}`);
                }
            }

            // Generate bathrooms
            if (bathrooms === 1) {
                rooms.push('Bathroom');
            } else {
                for (let i = 1; i <= bathrooms; i++) {
                    rooms.push(`Bathroom ${i}`);
                }
            }

            // Add checked extra rooms
            document.querySelectorAll('.room-toggle input:checked').forEach(chk => {
                rooms.push(chk.value);
            });

            return rooms;
        }

        function updateRoomPreview() {
            const rooms = generateRoomList();
            roomPreviewList.innerHTML = rooms.map(r =>
                `<span class="room-preview-chip">${r}</span>`
            ).join('');
        }

        function populateRoomSelector(rooms) {
            const roomSelect = document.getElementById('room-select');
            // Clear all except __custom__
            const customOpt = Array.from(roomSelect.options).find(o => o.value === '__custom__');
            roomSelect.innerHTML = '';
            rooms.forEach(room => {
                const opt = document.createElement('option');
                opt.value = room;
                opt.textContent = room;
                roomSelect.appendChild(opt);
            });
            if (customOpt) roomSelect.appendChild(customOpt);
            else {
                const addOpt = document.createElement('option');
                addOpt.value = '__custom__';
                addOpt.textContent = '+ Add New…';
                roomSelect.appendChild(addOpt);
            }
        }

        // Save property
        savePropertyBtn?.addEventListener('click', () => {
            const name = propertyNameInput.value.trim();
            const address = propertyAddressInput.value.trim();

            if (!name) {
                propertyNameInput.focus();
                propertyNameInput.style.borderColor = '#ef4444';
                setTimeout(() => propertyNameInput.style.borderColor = '', 2000);
                return;
            }

            const rooms = generateRoomList();

            // Save to localStorage
            savedProperties[name] = { address, rooms, createdAt: new Date().toISOString() };
            localStorage.setItem('holos_properties', JSON.stringify(savedProperties));

            // Add to home selector if not already there
            if (!Array.from(homeSelect.options).find(o => o.value === name)) {
                const opt = document.createElement('option');
                opt.value = name;
                opt.textContent = name;
                const customOpt = Array.from(homeSelect.options).find(o => o.value === '__custom__');
                homeSelect.insertBefore(opt, customOpt);
            }

            // Select the new property
            homeSelect.value = name;

            // Populate room selector with generated rooms
            populateRoomSelector(rooms);

            // Close modal
            propertyModal.classList.add('hidden');

            // Update save location info
            updateSaveLocationInfo();
        });

        // Initial preview
        updateRoomPreview();

        // Update save-location info when selects change
        function updateSaveLocationInfo() {
            const homeVal = getLocationValue('home-select', 'home-custom-input');
            const roomVal = getLocationValue('room-select', 'room-custom-input');
            const info = document.getElementById('save-location-info');
            if (info) info.textContent = `${homeVal} / ${roomVal}`;
        }
        document.getElementById('home-select')?.addEventListener('change', updateSaveLocationInfo);
        document.getElementById('room-select')?.addEventListener('change', updateSaveLocationInfo);
    }

    // Auto-login if session exists
    const existingSession = localStorage.getItem('holos_session');
    if (existingSession) {
        const existingUser = JSON.parse(localStorage.getItem('holos_user') || '{}');
        authOverlay.classList.add('hidden');
        onLoginSuccess(existingUser);
    }
});

