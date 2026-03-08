document.addEventListener('DOMContentLoaded', () => {
    // --- Auth Logic (PoC Wrapper) ---
    const authOverlay = document.getElementById('auth-overlay');
    const authForm = document.getElementById('auth-form');
    const authToggleLink = document.getElementById('auth-toggle-link');
    const authTitle = document.getElementById('auth-title');
    const authSubtitle = document.getElementById('auth-subtitle');
    const authSubmitBtn = document.getElementById('auth-submit-btn');
    const authToggleText = document.getElementById('auth-toggle-text');
    const userProfileContainer = document.getElementById('user-profile-container');

    const navLoginBtn = document.getElementById('nav-login-btn');
    const heroBtn = document.getElementById('hero-get-started-btn');
    const authBoxWrapper = document.getElementById('auth-box-wrapper');
    const closeAuthBtn = document.getElementById('close-auth-btn');

    let isSignupMode = false;

    // Check login state
    const currentSession = localStorage.getItem('holos_session');
    const currentUser = localStorage.getItem('holos_user');
    if (currentUser && currentSession) {
        authOverlay.classList.add('hidden');
        setupUserProfile(JSON.parse(currentUser));
    }

    if (navLoginBtn) navLoginBtn.addEventListener('click', () => authBoxWrapper.classList.remove('hidden'));
    if (heroBtn) heroBtn.addEventListener('click', () => {
        isSignupMode = true; // By default get started is signup
        authTitle.textContent = 'Create Account';
        authSubtitle.textContent = 'Join Holos to start cataloging';
        authSubmitBtn.textContent = 'Sign Up';
        authToggleText.textContent = 'Already have an account?';
        authToggleLink.textContent = 'Sign In';
        authBoxWrapper.classList.remove('hidden');
    });
    if (closeAuthBtn) closeAuthBtn.addEventListener('click', () => authBoxWrapper.classList.add('hidden'));

    if (authToggleLink) {
        authToggleLink.addEventListener('click', (e) => {
            e.preventDefault();
            isSignupMode = !isSignupMode;

            if (isSignupMode) {
                authTitle.textContent = 'Create Account';
                authSubtitle.textContent = 'Join Holos to start cataloging';
                authSubmitBtn.textContent = 'Sign Up';
                authToggleText.textContent = 'Already have an account?';
                authToggleLink.textContent = 'Sign In';
            } else {
                authTitle.textContent = 'Welcome Back';
                authSubtitle.textContent = 'Sign in to continue to Holos';
                authSubmitBtn.textContent = 'Sign In';
                authToggleText.textContent = "Don't have an account?";
                authToggleLink.textContent = 'Sign Up';
            }
        });
    }

    if (authForm) {
        authForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;

            if (!email || !password) return;

            const endpoint = isSignupMode ? '/api/auth/register' : '/api/auth/login';
            const payload = { email, password, full_name: email.split('@')[0] };

            authSubmitBtn.disabled = true;
            authSubmitBtn.textContent = 'Please wait...';

            try {
                const res = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const data = await res.json();

                if (data.success) {
                    if (data.session) {
                        localStorage.setItem('holos_session', JSON.stringify(data.session));
                    }
                    if (data.user) {
                        const userObj = { email: data.user.email, name: data.user.user_metadata?.full_name || email.split('@')[0] };
                        localStorage.setItem('holos_user', JSON.stringify(userObj));

                        authOverlay.style.opacity = '0';
                        setTimeout(() => {
                            authOverlay.classList.add('hidden');
                            setupUserProfile(userObj);
                        }, 400);
                    } else if (isSignupMode) {
                        alert("Account created! Please verify your email or try logging in.");
                    }
                } else {
                    alert('Error: ' + (data.error || 'Authentication failed. Please check backend config.'));
                }
            } catch (err) {
                console.error(err);
                alert('Failed to communicate with backend. Is it running?');
            } finally {
                authSubmitBtn.disabled = false;
                authSubmitBtn.textContent = isSignupMode ? 'Sign Up' : 'Sign In';
            }
        });
    }

    function setupUserProfile(user) {
        if (userProfileContainer && !userProfileContainer.innerHTML.trim()) {
            userProfileContainer.innerHTML = `
                <div class="user-profile">
                    <div class="user-avatar">${user.name.charAt(0).toUpperCase()}</div>
                    <span class="user-name">${user.name}</span>
                    <button class="logout-btn prominent-logout-btn" id="logout-btn" title="Sign Out">Sign Out <i class="ri-logout-box-r-line"></i></button>
                </div>
            `;

            // Show location selector when logged in
            const locationSelector = document.getElementById('location-selector');
            if (locationSelector) locationSelector.classList.remove('hidden');

            document.getElementById('logout-btn').addEventListener('click', async () => {
                const sessionStr = localStorage.getItem('holos_session');
                if (sessionStr) {
                    try {
                        const sess = JSON.parse(sessionStr);
                        await fetch('/api/auth/logout', {
                            method: 'POST',
                            headers: { 'Authorization': `Bearer ${sess.access_token}` }
                        });
                    } catch (e) { console.error(e); }
                }

                localStorage.removeItem('holos_user');
                localStorage.removeItem('holos_session');
                userProfileContainer.innerHTML = '';

                if (locationSelector) locationSelector.classList.add('hidden');
                if (myInventoryBtn) myInventoryBtn.classList.add('hidden');
                if (resetBtn) resetBtn.classList.add('hidden');

                authOverlay.classList.remove('hidden');
                setTimeout(() => authOverlay.style.opacity = '1', 10);
                document.getElementById('password').value = '';
            });
        }
    }
    // --- End Auth Logic ---

    // --- Location Nav Logic ---
    const addHomeBtn = document.getElementById('add-home-btn');
    const homeSelect = document.getElementById('home-select');
    const addRoomBtn = document.getElementById('add-room-btn');
    const roomSelect = document.getElementById('room-select');

    if (addHomeBtn && homeSelect) {
        addHomeBtn.addEventListener('click', () => {
            const newHome = prompt("Enter new Home name:");
            if (newHome && newHome.trim()) {
                const opt = document.createElement('option');
                opt.value = newHome.trim();
                opt.textContent = newHome.trim();
                homeSelect.appendChild(opt);
                homeSelect.value = newHome.trim();
            }
        });
    }

    if (addRoomBtn && roomSelect) {
        addRoomBtn.addEventListener('click', () => {
            const newRoom = prompt("Enter new Room name:");
            if (newRoom && newRoom.trim()) {
                const opt = document.createElement('option');
                opt.value = newRoom.trim();
                opt.textContent = newRoom.trim();
                roomSelect.appendChild(opt);
                roomSelect.value = newRoom.trim();
                updateSaveInfo();
            }
        });
    }

    const saveInfo = document.getElementById('save-location-info');
    function updateSaveInfo() {
        if (saveInfo && homeSelect && roomSelect) {
            saveInfo.textContent = `${homeSelect.value} / ${roomSelect.value}`;
        }
    }
    if (homeSelect) homeSelect.addEventListener('change', updateSaveInfo);
    if (roomSelect) roomSelect.addEventListener('change', updateSaveInfo);
    updateSaveInfo();

    // --- End Location Nav Logic ---
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const scanningState = document.getElementById('scanning-state');
    const previewImage = document.getElementById('preview-image');
    const resultsSection = document.getElementById('results-section');
    const cardsContainer = document.getElementById('cards-container');
    const resetBtn = document.getElementById('reset-btn');

    const fileCountBadge = document.getElementById('file-count-badge');
    const fileCountText = document.getElementById('file-count-text');
    const startScanBtn = document.getElementById('start-scan-btn');
    const myInventoryBtn = document.getElementById('my-inventory-btn');
    const assetSearch = document.getElementById('asset-search');

    let currentScanItems = []; // Store the items from the last scan
    let selectedFiles = [];
    const fileMap = new Map(); // Store files by their name for picture parsing
    let appMode = 'scan'; // 'scan' or 'inventory'

    // Drag & Drop Events
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'), false);
    });

    // Handle dropped files
    dropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        handleFiles(dt.files);
    }, false);

    // Handle click to upload
    dropZone.addEventListener('click', (e) => {
        // Prevent click if they are clicking the scan button
        if (e.target !== startScanBtn) {
            fileInput.click();
        }
    });

    fileInput.addEventListener('change', function () {
        handleFiles(this.files);
    });

    startScanBtn.addEventListener('click', (e) => {
        e.stopPropagation(); // prevent opening file picker again
        if (selectedFiles.length > 0) {
            startScanningProcess();
        }
    });

    // Reset button
    resetBtn.addEventListener('click', () => {
        resultsSection.classList.add('hidden');
        dropZone.parentElement.classList.remove('hidden');
        cardsContainer.innerHTML = '';
        fileInput.value = '';
        selectedFiles = [];
        fileCountBadge.classList.add('hidden');

        // Reset upload zone content
        dropZone.querySelector('.drop-content').style.display = 'block';
    });

    function handleFiles(files) {
        const validFiles = Array.from(files).filter(f => f.type.startsWith('image/'));

        if (validFiles.length === 0) {
            alert('Please select at least one valid image file.');
            return;
        }

        selectedFiles = validFiles;
        fileMap.clear(); // Clear previous files
        selectedFiles.forEach(f => fileMap.set(f.name, f)); // Populate fileMap

        // Update UI
        fileCountText.textContent = `${selectedFiles.length} file${selectedFiles.length > 1 ? 's' : ''} ready`;
        fileCountBadge.classList.remove('hidden');
        dropZone.querySelector('.drop-content').style.display = 'none';

        // Show the first image as a preview background (optional visual flair)
        const reader = new FileReader();
        reader.onload = (e) => {
            dropZone.style.backgroundImage = `linear-gradient(rgba(15, 17, 21, 0.8), rgba(15, 17, 21, 0.9)), url(${e.target.result})`;
            dropZone.style.backgroundSize = 'cover';
            dropZone.style.backgroundPosition = 'center';
            previewImage.src = e.target.result;
        }
        reader.readAsDataURL(selectedFiles[0]);
    }

    function startScanningProcess() {
        appMode = 'scan';
        // Clear search input when starting a new scan
        if (assetSearch) assetSearch.value = '';
        dropZone.parentElement.classList.add('hidden');
        scanningState.classList.remove('hidden');
        uploadAndScan();
    }

    async function uploadAndScan() {
        const formData = new FormData();
        selectedFiles.forEach(file => {
            formData.append('image', file);
        });
        const homeSelect = document.getElementById('home-select');
        const roomSelect = document.getElementById('room-select');
        if (homeSelect) formData.append('home_name', homeSelect.value);
        if (roomSelect) formData.append('room_name', roomSelect.value);

        const headers = {};
        const sessionStr = localStorage.getItem('holos_session');
        if (sessionStr) {
            try {
                const sess = JSON.parse(sessionStr);
                headers['Authorization'] = `Bearer ${sess.access_token}`;
            } catch (e) { }
        }

        try {
            const response = await fetch('/api/scan', {
                method: 'POST',
                headers: headers,
                body: formData
            });

            const result = await response.json();

            if (result.success) {
                try {
                    // `result.data` is already a pre-parsed JavaScript Array, 
                    // because our Python backend stitches and returns JSON automatically.
                    currentScanItems = (Array.isArray(result.data) ? result.data : [result.data]).map((it, idx) => ({
                        ...it,
                        tempId: `item-${idx}`,
                        originalIndex: idx
                    }));

                    // Show and activate the Recent Scan tab
                    const scanTab = document.getElementById('recent-scan-tab');
                    if (scanTab) {
                        scanTab.classList.remove('hidden');
                        scanTab.classList.add('active');
                        activeTab.classList.remove('active');
                        archivedTab.classList.remove('active');
                    }
                    appMode = 'scan';
                    if (assetSearch) assetSearch.placeholder = "Search scan results...";

                    renderResults(currentScanItems);
                } catch (parseError) {
                    console.error("Failed to render Model output", result.data);
                    alert("Model responded, but the data format was unexpected.");
                    resetState();
                }
            } else {
                alert('Error: ' + result.error);
                if (result.details) {
                    console.warn(result.details);
                }
                resetState();
            }

        } catch (error) {
            console.error('Error:', error);
            alert('Failed to connect to the Holos backend.');
            resetState();
        }
    }

    function resetState() {
        scanningState.classList.add('hidden');
        dropZone.parentElement.classList.remove('hidden');
    }

    function groupByCategory(items) {
        const tree = {};

        items.forEach(item => {
            // Default to "Uncategorized" if the API failed to provide it
            let catString = item.category || "Uncategorized";

            // The prompt forces "Main > Sub", but we should handle messy output safely
            const parts = catString.split('>').map(p => p.trim());
            const mainCat = parts[0] || "Uncategorized";
            const subCat = parts.length > 1 ? parts.slice(1).join(' > ') : "General";

            if (!tree[mainCat]) {
                tree[mainCat] = {};
            }
            if (!tree[mainCat][subCat]) {
                tree[mainCat][subCat] = [];
            }

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

                // Gemini bbox format [ymin, xmin, ymax, xmax] in 0-1000 scale
                const [ymin, xmin, ymax, xmax] = bbox;

                const x = (xmin / 1000) * img.width;
                const y = (ymin / 1000) * img.height;
                const w = ((xmax - xmin) / 1000) * img.width;
                const h = ((ymax - ymin) / 1000) * img.height;

                canvas.width = w;
                canvas.height = h;
                ctx.drawImage(img, x, y, w, h, 0, 0, w, h);
                resolve(canvas.toDataURL('image/jpeg', 0.8));
            };
            img.src = URL.createObjectURL(file);
        });
    }

    async function renderResults(items) {
        scanningState.classList.add('hidden');
        resultsSection.classList.remove('hidden');
        cardsContainer.innerHTML = '';

        // Reset dropzone background since we are done
        dropZone.style.backgroundImage = 'none';

        if (items.length === 0) {
            cardsContainer.innerHTML = '<p style="color:var(--text-muted)">No distinct items identified across these images.</p>';
            return;
        }

        // 1. Build the Tree
        const categoryTree = groupByCategory(items);

        // 2. Render the Tree into HTML
        let delayIndex = 0;

        // Sort main categories alphabetically
        Object.keys(categoryTree).sort().forEach(mainCat => {
            const mainSection = document.createElement('div');
            mainSection.className = 'tree-section';
            mainSection.style.animationDelay = `${delayIndex * 0.1}s`;
            delayIndex++;

            let subCatHtml = '';

            Object.keys(categoryTree[mainCat]).sort().forEach(subCat => {
                const subItems = categoryTree[mainCat][subCat];

                let itemsHtml = subItems.map((item, index) => {
                    // Normalize condition for CSS classes
                    const cond = (item.condition || 'Good').toLowerCase();
                    let badgeClass = 'badge-good';
                    if (cond.includes('excellent')) badgeClass = 'badge-excellent';
                    else if (cond.includes('fair')) badgeClass = 'badge-fair';
                    else if (cond.includes('poor') || cond.includes('repair')) badgeClass = 'badge-poor';

                    return `
                    <div class="asset-card" data-id="${item.tempId}">
                        <div class="asset-thumbnail-container">
                            <img src="${item.thumbnail_url || '/static/HOLOS.jpg'}" 
                                 class="asset-thumbnail" 
                                 id="thumb-${item.tempId}"
                                 alt="${item.name}">
                            <span class="condition-badge ${badgeClass}">${item.condition || 'Good'}</span>
                        </div>
                        <div class="asset-content">
                            <div class="card-header">
                                <h4 class="item-name">${item.name || 'Unknown Asset'}</h4>
                                <span class="price-tag">${typeof item.estimated_price_usd === 'number' ? '$' + item.estimated_price_usd.toLocaleString() : (item.estimated_price_usd || 'N/A')}</span>
                            </div>
                            <div class="card-body">
                                <div class="detail-row">
                                    <span class="detail-label">Brand / Model</span>
                                    <span class="detail-value">${item.make || 'N/A'} - ${item.model || 'N/A'}</span>
                                </div>
                                <div class="detail-row">
                                    <span class="detail-label">Dimensions</span>
                                    <span class="detail-value">${item.estimated_dimensions || 'Est. N/A'}</span>
                                </div>
                                
                                ${item.suggested_replacements ? `
                                <div class="maintenance-tip">
                                    <i class="ri-lightbulb-line"></i>
                                    <span>${item.suggested_replacements}</span>
                                </div>
                                ` : ''}

                                <div class="asset-actions" id="actions-${item.tempId}">
                                    ${(item.id && !item.id.toString().startsWith('item-')) ? `
                                        ${item.is_archived ? `
                                            <button class="action-btn btn-primary-action unarchive-item-btn" data-id="${item.id}" data-tempid="${item.tempId}">
                                                <i class="ri-restart-line"></i> Unarchive
                                            </button>
                                        ` : `
                                            <button class="action-btn btn-secondary-action archive-item-btn" data-id="${item.id}" data-tempid="${item.tempId}">
                                                <i class="ri-archive-line"></i> Archive
                                            </button>
                                        `}
                                    ` : `
                                        <button class="action-btn btn-primary-action save-item-btn" data-index="${item.originalIndex}" data-tempid="${item.tempId}">
                                            <i class="ri-save-line"></i> Save
                                        </button>
                                        <button class="action-btn btn-secondary-action archive-now-btn" data-index="${item.originalIndex}" data-tempid="${item.tempId}">
                                            <i class="ri-delete-bin-line"></i> Archive
                                        </button>
                                    `}
                                    <button class="action-btn btn-primary-action replace-item-btn" data-id="${item.tempId}" data-make="${item.make || ''}" data-model="${item.model || ''}">
                                        <i class="ri-refresh-line"></i> Replace
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
                }).join('');

                subCatHtml += `
                    <div class="tree-subsection">
                        <h4 class="subcat-title"><i class="ri-folder-open-line"></i> ${subCat} <span class="item-count">${subItems.length}</span></h4>
                        <div class="subcat-items">
                            ${itemsHtml}
                        </div>
                    </div>
                `;
            });

            mainSection.innerHTML = `
                <div class="tree-header accordion-trigger">
                    <h3><i class="ri-price-tag-3-line"></i> ${mainCat} <span class="header-count">${Object.values(categoryTree[mainCat]).reduce((acc, curr) => acc + curr.length, 0)}</span></h3>
                    <i class="ri-arrow-down-s-line chevron"></i>
                </div>
                <div class="tree-content">
                    ${subCatHtml}
                </div>
            `;

            cardsContainer.appendChild(mainSection);
        });

        document.querySelectorAll('.archive-item-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const itemId = e.currentTarget.getAttribute('data-id');
                const tempId = e.currentTarget.getAttribute('data-tempid');
                if (confirm('Archive this item? It will be moved to your archive and hidden from main inventory.')) {
                    archiveItem(itemId, tempId);
                }
            });
        });

        document.querySelectorAll('.save-item-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const itemIndex = parseInt(e.currentTarget.getAttribute('data-index'));
                const tempId = e.currentTarget.getAttribute('data-tempid');
                // Capture the current location from UI at the moment of saving
                const homeName = document.getElementById('home-name')?.value || 'My House';
                const roomName = document.getElementById('room-name')?.value || 'General Room';

                const itemData = {
                    ...currentScanItems[itemIndex],
                    home_name: homeName,
                    room_name: roomName
                };
                const btnEl = e.currentTarget;

                btnEl.disabled = true;
                btnEl.innerHTML = '<i class="ri-loader-4-line ri-spin"></i> Saving...';

                const result = await saveItem(itemData);
                if (result.success) {
                    const saved = result.data;
                    const actionsContainer = document.getElementById(`actions-${tempId}`);
                    if (actionsContainer) {
                        actionsContainer.innerHTML = `
                            <button class="action-btn btn-secondary-action archive-item-btn" data-id="${saved.id}" data-tempid="${tempId}">
                                <i class="ri-archive-line"></i> Archive
                            </button>
                            <button class="action-btn btn-primary-action replace-item-btn" data-make="${saved.make || ''}" data-model="${saved.model || ''}">
                                <i class="ri-refresh-line"></i> Replace
                            </button>
                        `;
                        // Re-bind archive for the new button
                        actionsContainer.querySelector('.archive-item-btn').addEventListener('click', (ev) => {
                            archiveItem(saved.id, tempId);
                        });
                    }
                } else {
                    btnEl.disabled = false;
                    btnEl.innerHTML = '<i class="ri-save-line"></i> Save';
                    alert(`Save Failed: ${result.error || 'Unknown Error'}. Please check your database connection or console for details.`);
                }
            });
        });

        document.querySelectorAll('.unarchive-item-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const itemId = e.currentTarget.getAttribute('data-id');
                const tempId = e.currentTarget.getAttribute('data-tempid');
                unarchiveItem(itemId, tempId);
            });
        });

        document.querySelectorAll('.archive-now-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const itemIndex = parseInt(e.currentTarget.getAttribute('data-index'));
                const tempId = e.currentTarget.getAttribute('data-tempid');
                const homeName = document.getElementById('home-name')?.value || 'My House';
                const roomName = document.getElementById('room-name')?.value || 'General Room';

                const itemData = {
                    ...currentScanItems[itemIndex],
                    is_archived: true,
                    home_name: homeName,
                    room_name: roomName
                };

                const btnEl = e.currentTarget;
                btnEl.disabled = true;
                btnEl.innerHTML = '<i class="ri-loader-4-line ri-spin"></i> Archiving...';

                const result = await saveItem(itemData);
                if (result.success) {
                    document.querySelector(`.asset-card[data-id="${tempId}"]`)?.remove();
                } else {
                    btnEl.disabled = false;
                    btnEl.innerHTML = '<i class="ri-delete-bin-line"></i> Archive';
                    alert('Archive Failed: ' + result.error);
                }
            });
        });

        document.querySelectorAll('.replace-item-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const make = e.currentTarget.getAttribute('data-make');
                const model = e.currentTarget.getAttribute('data-model');

                if (make || model) {
                    const query = encodeURIComponent(`${make} ${model} replacement`);
                    window.open(`https://www.google.com/search?q=${query}`, '_blank');
                } else {
                    alert('Not enough brand information to find specific replacements.');
                }
            });
        });

        // 2.5 Generate real thumbnails if bounding boxes exist
        items.forEach(async (item) => {
            if (item.bounding_box && item.original_filename) {
                const file = fileMap.get(item.original_filename);
                if (file) {
                    const thumbUrl = await generateThumbnail(file, item.bounding_box);
                    if (thumbUrl) {
                        const imgEl = document.getElementById(`thumb-${item.tempId}`);
                        if (imgEl) imgEl.src = thumbUrl;
                        item.thumbnail_url = thumbUrl; // Ensure data is ready for save
                    }
                }
            }
        });

        // 3. Add Accordion interactivity for newly rendered elements
        document.querySelectorAll('.accordion-trigger').forEach(trigger => {
            trigger.addEventListener('click', function () {
                this.classList.toggle('active');
                const content = this.nextElementSibling;
                if (content.style.maxHeight) {
                    content.style.maxHeight = null;
                } else {
                    content.style.maxHeight = content.scrollHeight + "px";
                }
            });
        });

        // Open the first one by default to show results immediately
        const firstTrigger = document.querySelector('.accordion-trigger');
        if (firstTrigger) {
            firstTrigger.click();
        }
    }

    async function archiveItem(itemId, tempId = null) {
        const targetId = tempId || itemId;
        if (!itemId || itemId.toString().startsWith('item-')) {
            document.querySelector(`.asset-card[data-id="${targetId}"]`)?.remove();
            return;
        }

        try {
            const sessionStr = localStorage.getItem('holos_session');
            const sess = sessionStr ? JSON.parse(sessionStr) : null;

            const response = await fetch(`/api/items/${itemId}/archive`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${sess ? sess.access_token : ''}`
                }
            });

            if (response.ok) {
                document.querySelector(`.asset-card[data-id="${targetId}"]`)?.remove();
            } else {
                console.error('Failed to archive item');
            }
        } catch (err) {
            console.error('Error archiving item:', err);
        }
    }

    async function unarchiveItem(itemId, tempId = null) {
        const targetId = tempId || itemId;
        try {
            const sessionStr = localStorage.getItem('holos_session');
            const sess = sessionStr ? JSON.parse(sessionStr) : null;

            const response = await fetch(`/api/items/${itemId}/unarchive`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${sess ? sess.access_token : ''}`
                }
            });

            if (response.ok) {
                document.querySelector(`.asset-card[data-id="${targetId}"]`)?.remove();
            } else {
                console.error('Failed to unarchive item');
            }
        } catch (err) {
            console.error('Error unarchiving item:', err);
        }
    }

    async function saveItem(itemData) {
        const sessionStr = localStorage.getItem('holos_session');
        const sess = sessionStr ? JSON.parse(sessionStr) : null;
        if (!sess) return { success: false, error: "No active session" };

        // Clean up data for DB
        const toSave = { ...itemData };
        delete toSave.original_filename;
        delete toSave.id;

        try {
            const response = await fetch('/api/items/save', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${sess.access_token}`
                },
                body: JSON.stringify(toSave)
            });

            const res = await response.json();
            if (response.ok) {
                return { success: true, data: res.data };
            } else {
                return { success: false, error: res.error || "Server Error" };
            }
        } catch (err) {
            console.error('Save error:', err);
            return { success: false, error: err.message };
        }
    }

    // --- Search & Filtering Helper ---
    function filterScanResults(query) {
        if (!query) return currentScanItems;
        const terms = query.toLowerCase().split(' ');
        return currentScanItems.filter(item => {
            const text = `${item.name} ${item.category} ${item.make} ${item.model}`.toLowerCase();
            return terms.every(t => text.includes(t));
        });
    }

    // Global Inventory Search
    myInventoryBtn?.addEventListener('click', () => {
        appMode = 'inventory';
        isArchivedView = false;
        activeTab?.classList.add('active');
        archivedTab?.classList.remove('active');
        document.getElementById('recent-scan-tab')?.classList.remove('active');

        if (assetSearch) {
            assetSearch.value = '';
            assetSearch.placeholder = "Search saved inventory...";
        }
        fetchGlobalItems();
    });

    if (myInventoryBtn) {
        // Toggle visibility when logged in
        const currentSession = localStorage.getItem('holos_session');
        if (currentSession) myInventoryBtn.classList.remove('hidden');
    }

    // Tabs switching logic
    let isArchivedView = false;
    const activeTab = document.getElementById('active-items-tab');
    const archivedTab = document.getElementById('archived-items-tab');

    const recentScanTab = document.getElementById('recent-scan-tab');

    recentScanTab?.addEventListener('click', () => {
        appMode = 'scan';
        isArchivedView = false;
        if (assetSearch) {
            assetSearch.value = '';
            assetSearch.placeholder = "Search scan results...";
        }
        recentScanTab.classList.add('active');
        activeTab.classList.remove('active');
        archivedTab.classList.remove('active');
        renderResults(currentScanItems);
    });

    activeTab?.addEventListener('click', () => {
        appMode = 'inventory';
        isArchivedView = false;
        if (assetSearch) {
            assetSearch.value = '';
            assetSearch.placeholder = "Search saved inventory...";
        }
        activeTab.classList.add('active');
        archivedTab.classList.remove('active');
        recentScanTab?.classList.remove('active');
        fetchGlobalItems('', false);
    });

    archivedTab?.addEventListener('click', () => {
        appMode = 'inventory';
        isArchivedView = true;
        if (assetSearch) {
            assetSearch.value = '';
            assetSearch.placeholder = "Search archive folder...";
        }
        archivedTab.classList.add('active');
        activeTab.classList.remove('active');
        recentScanTab?.classList.remove('active');
        fetchGlobalItems('', true);
    });

    let searchTimeout;
    assetSearch?.addEventListener('input', (e) => {
        const query = e.target.value;

        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            if (appMode === 'scan') {
                // If in scan mode, filter the local currentScanItems array
                const filtered = filterScanResults(query);
                renderResults(filtered);
            } else {
                // If in inventory mode, fetch from server
                fetchGlobalItems(query, isArchivedView);
            }
        }, 300);
    });

    async function fetchGlobalItems(query = '', showArchived = false) {
        const sessionStr = localStorage.getItem('holos_session');
        if (!sessionStr) return;

        try {
            const sess = JSON.parse(sessionStr);
            const res = await fetch(`/api/items?q=${encodeURIComponent(query)}&archived=${showArchived}`, {
                headers: { 'Authorization': `Bearer ${sess.access_token}` }
            });
            const data = await res.json();
            if (data.success) {
                // Add home/room breadcrumb to names if searching globally
                const taggedData = data.data.map((item, idx) => ({
                    ...item,
                    tempId: item.id || `global-${idx}`,
                    name: `${item.name} (${item.home_name} - ${item.room_name})`
                }));
                renderResults(taggedData);
                // Also show reset button to go back to scan
                resetBtn.classList.remove('hidden');
                dropZone.parentElement.classList.add('hidden');
            }
        } catch (err) {
            console.error(err);
        }
    }
});
