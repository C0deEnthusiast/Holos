document.addEventListener('DOMContentLoaded', () => {
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

    let selectedFiles = [];

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
        dropZone.parentElement.classList.add('hidden');
        scanningState.classList.remove('hidden');
        uploadAndScan();
    }

    async function uploadAndScan() {
        const formData = new FormData();
        selectedFiles.forEach(file => {
            formData.append('image', file);
        });

        try {
            const response = await fetch('/api/scan', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (result.success) {
                try {
                    // `result.data` is already a pre-parsed JavaScript Array, 
                    // because our Python backend stitches and returns JSON automatically.
                    renderResults(result.data);
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

    function renderResults(items) {
        scanningState.classList.add('hidden');
        resultsSection.classList.remove('hidden');
        cardsContainer.innerHTML = '';

        // Reset dropzone background since we are done
        dropZone.style.backgroundImage = 'none';

        const arrayItems = Array.isArray(items) ? items : [items];

        if (arrayItems.length === 0) {
            cardsContainer.innerHTML = '<p style="color:var(--text-muted)">No distinct items identified across these images.</p>';
            return;
        }

        // 1. Build the Tree
        const categoryTree = groupByCategory(arrayItems);

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

                let itemsHtml = subItems.map(item => `
                    <div class="asset-card compact-card">
                        <div class="card-header">
                            <h4 class="item-name">${item.name || 'Unknown Asset'}</h4>
                        </div>
                        <div class="card-body">
                            <div class="detail-row">
                                <span class="detail-label">Brand</span>
                                <span class="detail-value">${item.make || 'N/A'}</span>
                            </div>
                            <div class="detail-row">
                                <span class="detail-label">Model</span>
                                <span class="detail-value" title="${item.model || ''}">${item.model || 'N/A'}</span>
                            </div>
                            <div class="detail-row">
                                <span class="detail-label">Dimensions</span>
                                <span class="detail-value">${item.estimated_dimensions || 'Est. N/A'}</span>
                            </div>
                            <div class="detail-row" style="margin-top: 0.25rem; border-bottom: none;">
                                <span class="detail-label">Value</span>
                                <span class="price-tag">${item.estimated_price_usd || 'Unknown'}</span>
                            </div>
                        </div>
                    </div>
                `).join('');

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
                    <h3><i class="ri-price-tag-3-line"></i> ${mainCat}</h3>
                    <i class="ri-arrow-down-s-line chevron"></i>
                </div>
                <div class="tree-content">
                    ${subCatHtml}
                </div>
            `;

            cardsContainer.appendChild(mainSection);
        });

        // 3. Add Accordion interactivity
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

            // Open the first one by default to show users what to do
            if (trigger === document.querySelector('.accordion-trigger')) {
                trigger.click();
            }
        });
    }
});
