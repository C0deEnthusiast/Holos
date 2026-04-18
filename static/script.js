/* HOLOS - Intelligent Home Cataloging & Asset Intelligence */

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

    // --- State ---
    let currentScanItems = []; // Raw results from Gemini
    let appMode = 'scan'; // 'scan' or 'inventory'

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

        // Use the first image as the preview for the "scanning" HUD
        const firstFile = files[0];
        previewImage.src = URL.createObjectURL(firstFile);

        const formData = new FormData();
        for (let file of files) {
            formData.append('image', file);
        }

        // Include location info
        const homeName = document.getElementById('home-select')?.value || 'My House';
        const roomName = document.getElementById('room-select')?.value || 'Living Room';
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
                for (let item of currentScanItems) {
                    const originalFile = Array.from(files).find(f => f.name === item.original_filename);
                    if (originalFile && item.bbox) {
                        item.thumbnail_url = await generateThumbnail(originalFile, item.bbox);
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

    async function generateThumbnail(file, bbox) {
        if (!file || !bbox || bbox.length !== 4) return null;
        return new Promise((resolve) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                const [ymin, xmin, ymax, xmax] = bbox;
                const x = (xmin / 1000) * img.width;
                const y = (ymin / 1000) * img.height;
                const w = ((xmax - xmin) / 1000) * img.width;
                const h = ((ymax - ymin) / 1000) * img.height;
                canvas.width = w; canvas.height = h;
                ctx.drawImage(img, x, y, w, h, 0, 0, w, h);
                resolve(canvas.toDataURL('image/jpeg', 0.8));
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
                    home_name: document.getElementById('home-select')?.value || 'My House',
                    room_name: document.getElementById('room-select')?.value || 'Living Room'
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
        document.querySelectorAll('.asset-card').forEach(card => {
            card.addEventListener('mousemove', (e) => {
                const rect = card.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                const centerX = rect.width / 2;
                const centerY = rect.height / 2;
                const rotateX = (centerY - y) / 10;
                const rotateY = (x - centerX) / 10;
                card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateY(-8px) scale(1.02)`;
                card.style.borderColor = 'var(--primary)';
                card.style.boxShadow = `0 20px 40px rgba(0,0,0,0.5), 0 0 20px rgba(0, 255, 242, 0.2)`;
            });
            card.addEventListener('mouseleave', () => {
                card.style.transform = 'perspective(1000px) rotateX(0) rotateY(0) translateY(0) scale(1)';
                card.style.borderColor = 'var(--card-border)';
                card.style.boxShadow = 'none';
            });
        });
    }

    function applyAccordionLogic() {
        document.querySelectorAll('.accordion-trigger').forEach(trigger => {
            trigger.addEventListener('click', () => {
                const content = trigger.nextElementSibling;
                trigger.classList.toggle('active');
                if (content.style.maxHeight) content.style.maxHeight = null;
                else content.style.maxHeight = content.scrollHeight + "px";
            });
        });
        // Open first one by default
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
        modalBody.innerHTML = html;
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
            const r = await fetch('/api/reports/estate');
            const d = await r.json();
            if (d.success) {
                let reportHtml = `<h2>Estate Value Report</h2><p>Total Assets: ${d.total_items}</p><p class="total-value">Value: $${d.total_value.toLocaleString()}</p>`;
                openModal(reportHtml);
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

    // Quick Demo: auto-fill test account and submit
    quickTestBtn?.addEventListener('click', async () => {
        quickTestBtn.textContent = '⏳ Signing in...';
        quickTestBtn.disabled = true;
        try {
            const r = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: 'admin@holos.com', password: 'holos2026' })
            });
            const data = await r.json();
            if (data.success) {
                localStorage.setItem('holos_session', JSON.stringify(data.session));
                localStorage.setItem('holos_user', JSON.stringify(data.user));
                authOverlay.classList.add('hidden');
                onLoginSuccess(data.user);
            } else {
                alert('Login failed: ' + (data.error || 'Unknown error'));
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
        const profileContainer = document.getElementById('user-profile-container');
        if (profileContainer) {
            profileContainer.innerHTML = `
                <div style="display:flex; align-items:center; justify-content:center; gap:0.75rem; margin-bottom:1rem;">
                    <span style="color:var(--text-main); font-weight:600;">👤 ${name}</span>
                    <button id="logout-btn" class="prominent-logout-btn">Logout</button>
                </div>
            `;
            document.getElementById('logout-btn')?.addEventListener('click', () => {
                localStorage.removeItem('holos_session');
                localStorage.removeItem('holos_user');
                window.location.reload();
            });
        }

        // Show location selector and action buttons
        document.getElementById('location-selector')?.classList.remove('hidden');
        myInventoryBtn?.classList.remove('hidden');
    }

    // Auto-login if session exists
    const existingSession = localStorage.getItem('holos_session');
    if (existingSession) {
        const existingUser = JSON.parse(localStorage.getItem('holos_user') || '{}');
        authOverlay.classList.add('hidden');
        onLoginSuccess(existingUser);
    }
});

