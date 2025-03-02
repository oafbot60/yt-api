document.addEventListener('DOMContentLoaded', function() {
    const urlInput = document.getElementById('url');
    const formatSelect = document.getElementById('format');
    const baixarBtn = document.getElementById('baixarBtn');
    const statusElement = document.getElementById('status');
    const downloadLink = document.getElementById('downloadLink');
    const progressContainer = document.getElementById('progress-container');
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');
    const progressPercentage = document.getElementById('progress-percentage');
    const timerContainer = document.getElementById('timer-container');
    const timerElement = document.getElementById('timer');
    const videoInfoElement = document.getElementById('video-info');
    
    // Focus on the URL input when the page loads
    urlInput.focus();
    
    // Add event listener for the Enter key on the URL input
    urlInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            handleDownload();
        }
    });
    
    baixarBtn.addEventListener('click', handleDownload);
    
    function handleDownload() {
        const url = urlInput.value.trim();
        const format = formatSelect.value;
        const quality = document.querySelector('input[name="quality"]:checked').value;
        
        if (!url) {
            showStatus('error', 'Por favor, insira um link do YouTube válido.');
            return;
        }
        
        // Check if it's a valid YouTube URL
        if (!isValidYouTubeUrl(url)) {
            showStatus('error', 'O link fornecido não parece ser um link válido do YouTube.');
            return;
        }
        
        // Reset UI
        resetUI();
        
        // Show loading state
        baixarBtn.disabled = true;
        baixarBtn.classList.add('loading');
        baixarBtn.innerHTML = `
            <svg class="spinner" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle>
                <path d="M12 2a10 10 0 0 1 10 10"></path>
            </svg>
            Processando...
        `;
        
        showStatus('warning', 'Obtendo informações do vídeo...');
        
        // Fetch video info first
        fetch(`/api/info?url=${encodeURIComponent(url)}`)
            .then(response => response.json())
            .then(videoData => {
                if (videoData.error) {
                    throw new Error(videoData.error);
                }
                
                // Show video info
                showVideoInfo(videoData);
                
                // Update status
                showStatus('warning', 'Convertendo para ' + format.toUpperCase() + ' (' + quality + ' kbps)...');
                
                // Show progress bar
                progressContainer.style.display = 'block';
                
                // Call the API to start the download
                return fetch('/api/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url, format: format, quality: quality })
                });
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    showStatus('error', `Erro: ${data.error}`);
                    resetButtonState();
                } else {
                    showStatus('success', 'Download iniciado! Verificando status...');
                    monitorDownload(data.id);
                }
            })
            .catch(error => {
                showStatus('error', 'Erro ao iniciar o download: ' + error.message);
                resetButtonState();
                console.error("Erro:", error);
            });
    }
    
    function resetButtonState() {
        baixarBtn.disabled = false;
        baixarBtn.classList.remove('loading');
        baixarBtn.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            Baixar Áudio
        `;
    }
    
    function monitorDownload(downloadId) {
        fetch(`/api/status/${downloadId}`)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    showStatus('error', `Erro: ${data.error}`);
                    resetButtonState();
                    return;
                }
                
                // Update progress UI
                updateProgressUI(data);
                
                if (data.status === "completed") {
                    completeDownload(downloadId);
                } else if (data.status === "failed") {
                    showStatus('error', `Falha no download: ${data.error || 'Erro desconhecido'}`);
                    resetButtonState();
                } else {
                    // Continue monitoring
                    setTimeout(() => monitorDownload(downloadId), 1000);
                }
            })
            .catch(error => {
                showStatus('error', 'Erro ao verificar status do download.');
                resetButtonState();
                console.error("Erro:", error);
            });
    }
    
    function updateProgressUI(data) {
        // Update progress bar
        progressFill.style.width = data.progress + '%';
        progressPercentage.textContent = data.progress + '%';
        
        // Update progress text based on the status
        if (data.status === "extracting") {
            progressText.textContent = 'Extraindo áudio...';
        } else if (data.status === "converting") {
            progressText.textContent = 'Convertendo formato...';
        } else if (data.status === "optimizing") {
            progressText.textContent = 'Otimizando qualidade...';
        } else if (data.status === "completed") {
            progressText.textContent = 'Finalizado!';
        } else {
            progressText.textContent = 'Processando...';
        }
    }
    
    function completeDownload(downloadId) {
        // Reset button state
        resetButtonState();
        
        // Show success message
        showStatus('success', 'Áudio pronto para download!');
        
        // Show download link
        downloadLink.href = `/api/download/${downloadId}`;
        downloadLink.style.display = 'flex';
        
        // Start timer
        iniciarTimer(60);
    }
    
    function showStatus(type, message) {
        statusElement.className = 'status';
        statusElement.classList.add(type);
        
        let icon = '';
        if (type === 'error') {
            icon = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="8" x2="12" y2="12"></line>
                <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>`;
        } else if (type === 'success') {
            icon = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                <polyline points="22 4 12 14.01 9 11.01"></polyline>
            </svg>`;
        } else {
            icon = `<svg class="spinner" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle>
                <path d="M12 2a10 10 0 0 1 10 10"></path>
            </svg>`;
        }
        
        statusElement.innerHTML = icon + message;
        statusElement.style.display = 'flex';
    }
    
    function isValidYouTubeUrl(url) {
        // More comprehensive validation for YouTube URLs
        const youtubeRegex = /^(https?:\/\/)?(www\.)?(youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/|youtube\.com\/embed\/|youtube\.com\/v\/|youtube\.com\/user\/[^\/]+\/\w+\/|youtube\.com\/[^\/]+\/\w+\/|youtube\.com\/playlist\?list=|youtube\.com\/channel\/|youtube\.com\/c\/|youtube\.com\/user\/).+/;
        return youtubeRegex.test(url);
    }
    
    // Inicia o timer de 60 segundos
    function iniciarTimer(segundos) {
        timerContainer.style.display = 'flex';
        
        let tempoRestante = segundos;
        const intervalo = setInterval(() => {
            if (tempoRestante > 0) {
                timerElement.innerText = `Tempo restante: ${tempoRestante} segundos`;
                tempoRestante--;
            } else {
                clearInterval(intervalo);
                downloadLink.style.display = 'none';
                timerElement.innerText = "O áudio foi autodestruído!";
                
                // After 3 seconds, hide the timer
                setTimeout(() => {
                    timerContainer.style.display = 'none';
                }, 3000);
            }
        }, 1000);
    }
    
    function resetUI() {
        // Hide elements that might be visible from previous operations
        progressContainer.style.display = 'none';
        downloadLink.style.display = 'none';
        timerContainer.style.display = 'none';
        videoInfoElement.style.display = 'none';
        progressFill.style.width = '0%';
        progressPercentage.textContent = '0%';
    }
    
    function showVideoInfo(videoData) {
        // Create and populate video info HTML
        videoInfoElement.innerHTML = `
            <div class="video-info-header">
                <img src="${videoData.thumbnail}" alt="Thumbnail" class="video-thumbnail">
                <h3 class="video-title">${videoData.title}</h3>
            </div>
            <div class="video-details">
                <div class="video-detail">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="12" cy="12" r="10"></circle>
                        <polyline points="12 6 12 12 16 14"></polyline>
                    </svg>
                    <span>${videoData.formatted_duration}</span>
                </div>
                <div class="video-detail">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                        <circle cx="12" cy="12" r="3"></circle>
                    </svg>
                    <span>${formatViewCount(videoData.view_count)} visualizações</span>
                </div>
                <div class="video-detail">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                        <circle cx="9" cy="7" r="4"></circle>
                        <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
                        <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
                    </svg>
                    <span>${videoData.uploader}</span>
                </div>
                <div class="video-detail">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M9 18V5l12-2v13"></path>
                        <circle cx="6" cy="18" r="3"></circle>
                        <circle cx="18" cy="16" r="3"></circle>
                    </svg>
                    <span>${document.querySelector('input[name="quality"]:checked').value} kbps</span>
                </div>
            </div>
        `;
        
        // Show the video info element
        videoInfoElement.style.display = 'block';
    }
    
    function formatViewCount(count) {
        if (!count) return "0";
        
        if (count >= 1000000) {
            return (count / 1000000).toFixed(1) + 'M';
        } else if (count >= 1000) {
            return (count / 1000).toFixed(1) + 'K';
        }
        return count.toString();
    }
});
