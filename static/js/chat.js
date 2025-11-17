document.addEventListener("DOMContentLoaded", () => {
    // =========================================================================
    // DOM ELEMENTS
    // =========================================================================
    const chatListContainer = document.getElementById('chat-list-container');
    const messagesContainer = document.getElementById('messages-container');
    const chatForm = document.getElementById('chat-form');
    const promptInput = document.getElementById('prompt-input');
    const newChatBtn = document.getElementById('new-chat-btn');

    const userName = document.getElementById('username').textContent;

    const fileStagingArea = document.getElementById('file-staging-area');
    const cvUploadBtn = document.getElementById('cv-upload-btn');
    const cvUploadInput = document.getElementById('cv-upload-input');

    // =========================================================================
    // APPLICATION STATE
    // =========================================================================
    let currentChatId = null;
    let stagedFiles = [];
    let isUploading = false;
    
    // Configuration
    const MAX_FILES = 12;
    const MAX_FILE_SIZE_MB = 10;
    const ALLOWED_FILE_TYPES = ['application/pdf'];

    // =========================================================================
    // MESSAGE RENDERING
    // =========================================================================
    
    /**
     * Render một tin nhắn lên màn hình với markdown support
     */
    function renderMessage(role, content) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${role}`;

        if (typeof marked !== 'undefined') {
            msgDiv.innerHTML = marked.parse(content);
        } else {
            console.warn("marked.js not loaded. Falling back to basic text.");
            msgDiv.innerHTML = content.replace(/\n/g, '<br>');
        }
        
        messagesContainer.appendChild(msgDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    /**
     * Hiển thị loading message với animation
     */
    function renderLoadingMessage() {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message assistant loading';
        msgDiv.innerHTML = `
            <div class="loading-dots">
                <span>●</span>
                <span>●</span>
                <span>●</span>
            </div>
            <span>Analyzing...</span>
        `;
        messagesContainer.appendChild(msgDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
        return msgDiv;
    }

    // =========================================================================
    // CHAT LIST MANAGEMENT
    // =========================================================================
    
    /**
     * Tải danh sách chat từ API
     */
    async function loadChatList() {
        chatListContainer.innerHTML = '<p class="text-gray-500 text-sm">Loading history...</p>';
        
        try {
            const response = await fetch('/api/chats');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            
            const chatList = await response.json();
            chatListContainer.innerHTML = '';
            
            if (chatList.length === 0) {
                chatListContainer.innerHTML = '<p class="text-gray-500 text-sm">No search history yet.</p>';
                return;
            }

            chatList.forEach(chat => {
                const [chatId, title] = chat;
                
                const itemDiv = document.createElement('div');
                itemDiv.className = 'chat-item';
                itemDiv.dataset.chatId = chatId;
                
                const titleBtn = document.createElement('button');
                titleBtn.className = 'chat-select-btn';
                titleBtn.textContent = title;
                
                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'chat-delete-btn';
                deleteBtn.innerHTML = '❌';
                deleteBtn.title = 'Delete chat';

                titleBtn.addEventListener('click', () => loadMessages(chatId));
                deleteBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    deleteChat(chatId);
                });

                itemDiv.appendChild(titleBtn);
                itemDiv.appendChild(deleteBtn);
                chatListContainer.appendChild(itemDiv);
            });

        } catch (error) {
            console.error('Error loading chat list:', error);
            chatListContainer.innerHTML = '<p style="color: red;">Failed to load chat history.</p>';
        }
    }

    /**
     * Tải tin nhắn cho một chat cụ thể
     */
    async function loadMessages(chatId) {
        currentChatId = chatId;
        
        // if (chatIdDisplay) {
        //     chatIdDisplay.textContent = `Chat #${chatId}`;
        // }
        
        messagesContainer.innerHTML = '<p style="color: gray; text-align: center;">Loading messages...</p>';
        
        // Highlight selected chat
        document.querySelectorAll('#chat-list-container .chat-item').forEach(div => {
            div.classList.remove('selected');
            if (div.dataset.chatId == chatId) {
                div.classList.add('selected');
            }
        });

        try {
            const response = await fetch(`/api/chat/${chatId}/messages`);
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            
            const messages = await response.json();
            messagesContainer.innerHTML = '';
            
            if (messages.length === 0) {
                renderMessage('assistant', '👋 Hello! I\'m Vi. What would you like to work on today?');
            } else {
                messages.forEach(msg => renderMessage(msg.role, msg.content));
            }
        } catch (error) {
            console.error('Error loading messages:', error);
            messagesContainer.innerHTML = '<p style="color: red; text-align: center;">Failed to load messages.</p>';
        }
    }

    /**
     * Xóa một chat
     */
    async function deleteChat(chatId) {
        if (!confirm('Are you sure you want to delete this conversation?')) return;
        
        try {
            const response = await fetch(`/api/chat/${chatId}`, { method: 'DELETE' });
            if (!response.ok) throw new Error('Failed to delete chat');
            
            await loadChatList();
            
            if (currentChatId == chatId) {
                currentChatId = null;
                // if (chatIdDisplay) chatIdDisplay.textContent = 'N/A';
                messagesContainer.innerHTML = '<p style="color: gray; text-align: center;">Please select a chat or create a new one.</p>';
            }
        } catch (error) {
            console.error('Error deleting chat:', error);
            alert('Failed to delete chat.');
        }
    }

    // =========================================================================
    // FILE STAGING & VALIDATION
    // =========================================================================
    
    /**
     * Validate file trước khi thêm vào staging
     */
    function validateFile(file) {
        const errors = [];
        
        // Check file type
        if (!ALLOWED_FILE_TYPES.includes(file.type)) {
            errors.push(`Only PDF files are allowed. "${file.name}" is ${file.type || 'unknown type'}.`);
        }
        
        // Check file size
        const fileSizeMB = file.size / (1024 * 1024);
        if (fileSizeMB > MAX_FILE_SIZE_MB) {
            errors.push(`"${file.name}" is too large (${fileSizeMB.toFixed(1)}MB). Maximum ${MAX_FILE_SIZE_MB}MB allowed.`);
        }
        
        return errors;
    }

    /**
     * Thêm files vào staging area với validation
     */
    function addFilesToStaging(files) {
        const errors = [];
        const validFiles = [];
        
        // Check total count
        if (stagedFiles.length + files.length > MAX_FILES) {
            alert(`Maximum ${MAX_FILES} files allowed.\nYou already have ${stagedFiles.length} file(s) staged.`);
            return;
        }
        
        // Validate each file
        Array.from(files).forEach(file => {
            const fileErrors = validateFile(file);
            
            if (fileErrors.length > 0) {
                errors.push(...fileErrors);
            } else {
                // Check for duplicates
                const isDuplicate = stagedFiles.some(f => 
                    f.name === file.name && f.size === file.size
                );
                
                if (isDuplicate) {
                    errors.push(`"${file.name}" is already staged.`);
                } else {
                    validFiles.push(file);
                }
            }
        });
        
        // Show errors if any
        if (errors.length > 0) {
            alert('Some files could not be added:\n\n' + errors.join('\n'));
        }
        
        // Add valid files
        if (validFiles.length > 0) {
            stagedFiles.push(...validFiles);
            renderStagedFiles();
            
            // Show success message
            if (validFiles.length > 1) {
                showToast(`✅ Added ${validFiles.length} files`);
            }
        }
    }

    /**
     * Render staged files với preview và remove buttons
     */
    function renderStagedFiles() {
        if (!fileStagingArea) {
            console.error("DOM element #file-staging-area not found.");
            return;
        }

        if (stagedFiles.length === 0) {
            fileStagingArea.style.display = 'none';
            fileStagingArea.innerHTML = '';
            return;
        }

        fileStagingArea.style.display = 'flex';
        fileStagingArea.innerHTML = '';
        
        // Add header
        const header = document.createElement('div');
        header.className = 'file-staging-header';
        header.innerHTML = `
            <span>📎 ${stagedFiles.length} file(s) ready to upload</span>
            <button type="button" class="clear-all-btn" title="Remove all">Clear All</button>
        `;
        fileStagingArea.appendChild(header);
        
        // Add clear all functionality
        header.querySelector('.clear-all-btn').addEventListener('click', () => {
            if (confirm('Remove all staged files?')) {
                stagedFiles = [];
                renderStagedFiles();
            }
        });

        // Add file cards
        stagedFiles.forEach((file, index) => {
            const fileCard = document.createElement('div');
            fileCard.className = 'file-card';
            
            const fileSizeKB = (file.size / 1024).toFixed(1);
            const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
            const sizeDisplay = file.size > 1024 * 1024 ? `${fileSizeMB} MB` : `${fileSizeKB} KB`;
            
            fileCard.innerHTML = `
                <div class="file-icon">📄</div>
                <div class="file-info">
                    <div class="file-name" title="${file.name}">${file.name}</div>
                    <div class="file-size">${sizeDisplay}</div>
                </div>
                <button type="button" class="file-remove-btn" title="Remove">×</button>
            `;
            
            fileCard.querySelector('.file-remove-btn').addEventListener('click', () => {
                stagedFiles.splice(index, 1);
                renderStagedFiles();
                showToast('File removed');
            });
            
            fileStagingArea.appendChild(fileCard);
        });
    }

    // =========================================================================
    // DRAG & DROP SUPPORT
    // =========================================================================
    
    /**
     * Setup drag and drop functionality
     */
    function setupDragAndDrop() {
        const dropZone = messagesContainer;
        
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => {
                dropZone.classList.add('drag-over');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => {
                dropZone.classList.remove('drag-over');
            }, false);
        });

        dropZone.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                addFilesToStaging(files);
            }
        }, false);
    }

    // =========================================================================
    // TOAST NOTIFICATIONS
    // =========================================================================
    
    /**
     * Show toast notification
     */
    function showToast(message, duration = 2000) {
        const toast = document.createElement('div');
        toast.className = 'toast-notification';
        toast.textContent = message;
        document.body.appendChild(toast);
        
        setTimeout(() => toast.classList.add('show'), 10);
        
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    // =========================================================================
    // MESSAGE SENDING
    // =========================================================================
    
    /**
     * Send message với files
     */
    async function sendMessage(prompt, files) {
        if (isUploading) {
            alert('Please wait for the current upload to complete.');
            return;
        }
        
        if (!currentChatId) {
            alert('Please select a conversation or create a new one.');
            return;
        }
        
        isUploading = true;
        
        // Display user message
        const displayMessage = files.length > 0 
            ? `${prompt}\n\n📎 Attached ${files.length} file(s)` 
            : prompt;
        renderMessage('user', displayMessage);
        
        // Show loading
        const loadingEl = renderLoadingMessage();
        
        // Prepare form data
        const formData = new FormData();
        formData.append('prompt', prompt);
        files.forEach(file => formData.append('files', file));

        try {
            const response = await fetch(`/api/chat/${currentChatId}`, {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `Server error: ${response.statusText}`);
            }

            const data = await response.json();
            
            // Remove loading message
            loadingEl.remove();
            
            if (data.error) {
                renderMessage('assistant', `❌ Error: ${data.error}`);
            } else {
                renderMessage(data.role, data.content);
            }
            
            // Reload chat list if this was the first message
            if (messagesContainer.children.length <= 3) {
                await loadChatList();
            }

        } catch (error) {
            console.error('Error sending message:', error);
            loadingEl.remove();
            renderMessage('assistant', `❌ Failed to send message: ${error.message}`);
        } finally {
            isUploading = false;
        }
    }

    // =========================================================================
    // EVENT LISTENERS
    // =========================================================================
    
    // Initialize
    loadChatList();
    messagesContainer.innerHTML = `<p style="color: gray; text-align: center; padding: 4rem 0; font-size: x-large">👋 Welcome <b>${userName}</b>! Click \'<b>New Chat</b>\' in the sidebar to start.</p>`;
    setupDragAndDrop();

    // New chat button
    newChatBtn.addEventListener('click', async () => {
        try {
            const response = await fetch('/api/chats', { method: 'POST' });
            if (!response.ok) throw new Error('Failed to create new chat');
            
            const newChat = await response.json();
            
            await loadChatList();
            await loadMessages(newChat.id);
            
            // Reset state
            stagedFiles = [];
            renderStagedFiles();
            promptInput.value = '';
            
            showToast('✨ New conversation started');

        } catch (error) {
            console.error('Error creating new chat:', error);
            alert('Failed to create new chat.');
        }
    });

    // Chat form submission
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const prompt = promptInput.value.trim();
        
        // Validation
        if (!prompt && stagedFiles.length === 0) {
            showToast('⚠️ Please enter a message or attach files');
            return;
        }
        
        // Prepare files to send
        const filesToSend = [...stagedFiles];
        
        // Clear input and staged files
        promptInput.value = '';
        stagedFiles = [];
        renderStagedFiles();
        
        // Send message
        await sendMessage(prompt, filesToSend);
    });

    // File upload button
    cvUploadBtn.addEventListener('click', () => {
        if (!cvUploadInput) {
            alert("Error: File input not found.");
            return;
        }
        cvUploadInput.click();
    });

    // File input change
    cvUploadInput.addEventListener('change', (e) => {
        const files = e.target.files;
        if (files.length > 0) {
            addFilesToStaging(files);
        }
        e.target.value = null; // Reset input
    });

    // Textarea auto-resize
    if (promptInput) {
        promptInput.addEventListener('input', () => {
            promptInput.style.height = 'auto';
            promptInput.style.height = `${promptInput.scrollHeight}px`;
        });

        // Submit on Enter (but not Shift+Enter)
        promptInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                chatForm.requestSubmit();
            }
        });
    }

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + K: New chat
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            newChatBtn.click();
        }
        
        // Ctrl/Cmd + U: Upload file
        if ((e.ctrlKey || e.metaKey) && e.key === 'u') {
            e.preventDefault();
            cvUploadBtn.click();
        }
        
        // Escape: Close features modal
        if (e.key === 'Escape') {
            const featuresModal = document.getElementById('features-modal');
            if (featuresModal && featuresModal.style.display === 'flex') {
                featuresModal.style.display = 'none';
            }
        }
    });

    // Features modal functionality
    const openFeaturesBtn = document.getElementById('open-features-btn');
    const closeFeaturesBtn = document.getElementById('close-features-btn');
    const featuresModal = document.getElementById('features-modal');
    const featuresModalOverlay = document.querySelector('.features-modal-overlay');

    if (openFeaturesBtn && featuresModal) {
        // Open modal
        openFeaturesBtn.addEventListener('click', () => {
            featuresModal.style.display = 'flex';
            document.body.style.overflow = 'hidden'; // Prevent body scroll
        });

        // Close modal - close button
        if (closeFeaturesBtn) {
            closeFeaturesBtn.addEventListener('click', () => {
                featuresModal.style.display = 'none';
                document.body.style.overflow = ''; // Restore body scroll
            });
        }

        // Close modal - clicking overlay
        if (featuresModalOverlay) {
            featuresModalOverlay.addEventListener('click', () => {
                featuresModal.style.display = 'none';
                document.body.style.overflow = '';
            });
        }
    }

});