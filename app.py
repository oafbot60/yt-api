from flask import Flask, request, jsonify, send_file, render_template, abort
import yt_dlp
import os
import glob
import threading
import time
import uuid
import logging
from datetime import datetime
import json
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("youtube-audio-api")

app = Flask(__name__)

# Configuration
DOWNLOADS_DIR = "downloads"
METADATA_DIR = "metadata"
MAX_FILE_AGE = 60  # seconds
ALLOWED_FORMATS = ["mp3", "m4a", "wav"]
ALLOWED_QUALITIES = ["128", "192", "320"]
DEFAULT_FORMAT = "mp3"
DEFAULT_QUALITY = "192"
MAX_CONCURRENT_DOWNLOADS = 5

# Create necessary directories
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(METADATA_DIR, exist_ok=True)

# Dictionary to track files and their expiration
active_downloads = {}
download_semaphore = threading.Semaphore(MAX_CONCURRENT_DOWNLOADS)

class DownloadStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    EXTRACTING = "extracting"
    CONVERTING = "converting"
    OPTIMIZING = "optimizing"
    COMPLETED = "completed"
    FAILED = "failed"

class Download:
    def __init__(self, url, format=DEFAULT_FORMAT, quality=DEFAULT_QUALITY):
        self.id = str(uuid.uuid4())
        self.url = url
        self.format = format
        self.quality = quality
        self.status = DownloadStatus.QUEUED
        self.progress = 0
        self.filename = None
        self.title = None
        self.thumbnail = None
        self.duration = None
        self.error = None
        self.created_at = datetime.now()
        self.expires_at = None
        self.file_size = None
        self.artist = None
        self.video_id = self._extract_video_id(url)
        
    def _extract_video_id(self, url):
        # Extract video ID from various YouTube URL formats
        youtube_regex = r'(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
        match = re.search(youtube_regex, url)
        return match.group(1) if match else None
    
    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "format": self.format,
            "quality": self.quality,
            "status": self.status,
            "progress": self.progress,
            "filename": self.filename,
            "title": self.title,
            "thumbnail": self.thumbnail,
            "duration": self.duration,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "file_size": self.file_size,
            "artist": self.artist,
            "video_id": self.video_id
        }
    
    def save_metadata(self):
        metadata_path = os.path.join(METADATA_DIR, f"{self.id}.json")
        with open(metadata_path, 'w') as f:
            json.dump(self.to_dict(), f)

def progress_hook(d):
    download_id = d.get('info_dict', {}).get('__download_id')
    if not download_id or download_id not in active_downloads:
        return
    
    download = active_downloads[download_id]
    
    if d['status'] == 'downloading':
        # Calculate progress percentage
        if 'total_bytes' in d and d['total_bytes'] > 0:
            download.progress = min(int(d['downloaded_bytes'] / d['total_bytes'] * 90), 90)
        elif 'total_bytes_estimate' in d and d['total_bytes_estimate'] > 0:
            download.progress = min(int(d['downloaded_bytes'] / d['total_bytes_estimate'] * 90), 90)
        
        # Update status based on progress
        if download.progress < 30:
            download.status = DownloadStatus.EXTRACTING
        elif download.progress < 60:
            download.status = DownloadStatus.CONVERTING
        else:
            download.status = DownloadStatus.OPTIMIZING
    
    elif d['status'] == 'finished':
        download.progress = 95
        download.status = DownloadStatus.OPTIMIZING
    
    download.save_metadata()

def download_audio(download):
    download_semaphore.acquire()
    try:
        download.status = DownloadStatus.PROCESSING
        download.progress = 0
        download.save_metadata()
        
        # Configuração do yt-dlp com autenticação via cookies
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{DOWNLOADS_DIR}/{download.id}_%(title)s.%(ext)s",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": download.format,
                "preferredquality": download.quality,
            }],
            "progress_hooks": [progress_hook],
            "noplaylist": True,
            "quiet": False,
            "verbose": False,
            "writethumbnail": True,
            "writeinfojson": True,
            "cookies": "cookies.txt",  # 🔥 Adiciona autenticação via cookies
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(download.url, download=False)
                
                # Atualiza informações do download
                download.title = info.get("title", "Unknown Title")
                download.thumbnail = info.get("thumbnail")
                download.duration = info.get("duration")
                download.artist = info.get("artist") or info.get("uploader")
                download.save_metadata()
                
                # Agora baixa o áudio com autenticação
                ydl.download([download.url])
                
                # Procura o arquivo baixado
                pattern = os.path.join(DOWNLOADS_DIR, f"{download.id}_*.{download.format}")
                files = glob.glob(pattern)
                
                if files:
                    download.filename = os.path.basename(files[0])
                    download.file_size = os.path.getsize(files[0])
                    download.status = DownloadStatus.COMPLETED
                    download.progress = 100
                    
                    # Define o tempo de expiração
                    download.expires_at = datetime.now().fromtimestamp(time.time() + MAX_FILE_AGE)
                    
                    # Agendar exclusão do arquivo
                    schedule_file_deletion(download)
                else:
                    download.status = DownloadStatus.FAILED
                    download.error = "Arquivo não encontrado após o download"
                    logger.error(f"Arquivo não encontrado para {download.id}")
        
        except Exception as e:
            download.status = DownloadStatus.FAILED
            download.error = str(e)
            logger.exception(f"Erro ao baixar {download.url}: {str(e)}")
        
        finally:
            download.save_metadata()
            return download
    
    finally:
        download_semaphore.release()

def schedule_file_deletion(download):
    """Schedule the downloaded file for deletion after expiration"""
    filepath = os.path.join(DOWNLOADS_DIR, download.filename)
    
    def delete_file():
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"File '{download.filename}' was auto-deleted")
            
            # Also clean up metadata
            metadata_path = os.path.join(METADATA_DIR, f"{download.id}.json")
            if os.path.exists(metadata_path):
                os.remove(metadata_path)
            
            # Remove from active downloads
            active_downloads.pop(download.id, None)
        
        except Exception as e:
            logger.error(f"Error deleting file {filepath}: {str(e)}")
    
    # Schedule deletion
    timer = threading.Timer(MAX_FILE_AGE, delete_file)
    timer.daemon = True
    timer.start()
    
    logger.info(f"File '{download.filename}' available for {MAX_FILE_AGE} seconds")

def validate_youtube_url(url):
    """Validate if the URL is a valid YouTube URL"""
    youtube_regex = r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$'
    return bool(re.match(youtube_regex, url))

def validate_format(format_str):
    """Validate if the format is allowed"""
    return format_str in ALLOWED_FORMATS

def validate_quality(quality_str):
    """Validate if the quality is allowed"""
    return quality_str in ALLOWED_QUALITIES

def get_download_by_id(download_id):
    """Get download object by ID, either from memory or from saved metadata"""
    if download_id in active_downloads:
        return active_downloads[download_id]
    
    # Try to load from metadata
    metadata_path = os.path.join(METADATA_DIR, f"{download_id}.json")
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r') as f:
                data = json.load(f)
                download = Download(data['url'], data['format'], data['quality'])
                download.id = data['id']
                download.status = data['status']
                download.progress = data['progress']
                download.filename = data['filename']
                download.title = data['title']
                download.thumbnail = data['thumbnail']
                download.duration = data['duration']
                download.error = data['error']
                download.created_at = datetime.fromisoformat(data['created_at'])
                download.expires_at = datetime.fromisoformat(data['expires_at']) if data['expires_at'] else None
                download.file_size = data['file_size']
                download.artist = data['artist']
                download.video_id = data['video_id']
                return download
        except Exception as e:
            logger.error(f"Error loading metadata for {download_id}: {str(e)}")
    
    return None

def format_duration(seconds):
    """Format duration in seconds to MM:SS format"""
    if not seconds:
        return "00:00"
    
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes}:{seconds:02d}"

def format_file_size(size_bytes):
    """Format file size from bytes to human-readable format"""
    if not size_bytes:
        return "Unknown size"
    
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    
    return f"{size_bytes:.2f} TB"

# API Routes
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    format_str = data.get("format", DEFAULT_FORMAT).lower()
    quality = data.get("quality", DEFAULT_QUALITY)
    
    # Validate inputs
    if not url:
        return jsonify({"error": "URL is required"}), 400
    
    if not validate_youtube_url(url):
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    if not validate_format(format_str):
        return jsonify({"error": f"Invalid format. Allowed formats: {', '.join(ALLOWED_FORMATS)}"}), 400
    
    if not validate_quality(quality):
        return jsonify({"error": f"Invalid quality. Allowed qualities: {', '.join(ALLOWED_QUALITIES)}"}), 400
    
    # Create download object
    download = Download(url, format_str, quality)
    active_downloads[download.id] = download
    
    # Start download in a separate thread
    threading.Thread(target=download_audio, args=(download,), daemon=True).start()
    
    return jsonify({
        "id": download.id,
        "status": download.status,
        "message": "Download started"
    }), 202

@app.route("/api/status/<download_id>", methods=["GET"])
def api_status(download_id):
    download = get_download_by_id(download_id)
    
    if not download:
        return jsonify({"error": "Download not found"}), 404
    
    response = download.to_dict()
    
    # Add formatted duration and file size
    response["formatted_duration"] = format_duration(download.duration)
    response["formatted_file_size"] = format_file_size(download.file_size)
    
    return jsonify(response)

@app.route("/api/download/<download_id>", methods=["GET"])
def api_get_file(download_id):
    download = get_download_by_id(download_id)
    
    if not download:
        return jsonify({"error": "Download not found"}), 404
    
    if download.status != DownloadStatus.COMPLETED:
        return jsonify({
            "error": "Download not ready",
            "status": download.status,
            "progress": download.progress
        }), 400
    
    filepath = os.path.join(DOWNLOADS_DIR, download.filename)
    
    if not os.path.exists(filepath):
        return jsonify({"error": "File expired or not found"}), 404
    
    # Set content disposition with the video title for better filename
    filename = f"{download.title}.{download.format}"
    filename = re.sub(r'[^\w\-_\. ]', '', filename)  # Remove invalid filename characters
    
    return send_file(
        filepath,
        as_attachment=True,
        download_name=filename,
        mimetype=f"audio/{download.format}"
    )

@app.route("/download", methods=["GET"])
def download_legacy():
    """Legacy route for backward compatibility"""
    url = request.args.get("url", "").strip()
    format_str = request.args.get("format", DEFAULT_FORMAT).lower()
    quality = request.args.get("quality", DEFAULT_QUALITY)
    
    if not url:
        return jsonify({"error": "URL is required"}), 400
    
    if not validate_youtube_url(url):
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Create download object
    download = Download(url, format_str, quality)
    active_downloads[download.id] = download
    
    # Start download in a separate thread
    threading.Thread(target=download_audio, args=(download,), daemon=True).start()
    
    return jsonify({
        "message": "Download started",
        "id": download.id,
        "file": download.id  # For backward compatibility
    })

@app.route("/get-audio", methods=["GET"])
def get_audio_legacy():
    """Legacy route for backward compatibility"""
    file_id = request.args.get("file")
    
    if not file_id:
        return jsonify({"error": "File ID not specified"}), 400
    
    download = get_download_by_id(file_id)
    
    if not download:
        # Try to find by filename for backward compatibility
        for d in active_downloads.values():
            if d.filename == file_id:
                download = d
                break
    
    if not download:
        return jsonify({"error": "File expired or not found"}), 404
    
    filepath = os.path.join(DOWNLOADS_DIR, download.filename)
    
    if not os.path.exists(filepath):
        return jsonify({"error": "File expired or not found"}), 404
    
    return send_file(filepath, as_attachment=True)

@app.route("/api/formats", methods=["GET"])
def api_formats():
    """Return available formats and qualities"""
    return jsonify({
        "formats": ALLOWED_FORMATS,
        "qualities": ALLOWED_QUALITIES,
        "default_format": DEFAULT_FORMAT,
        "default_quality": DEFAULT_QUALITY
    })

@app.route("/api/info", methods=["GET"])
def api_info():
    """Get video info without downloading"""
    url = request.args.get("url", "").strip()
    
    if not url:
        return jsonify({"error": "URL is required"}), 400
    
    if not validate_youtube_url(url):
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    try:
        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            return jsonify({
                "title": info.get("title", "Unknown Title"),
                "thumbnail": info.get("thumbnail"),
                "duration": info.get("duration"),
                "formatted_duration": format_duration(info.get("duration")),
                "uploader": info.get("uploader"),
                "view_count": info.get("view_count"),
                "upload_date": info.get("upload_date"),
                "video_id": info.get("id")
            })
    
    except Exception as e:
        logger.exception(f"Error fetching video info: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def server_error(error):
    logger.exception("Server error")
    return jsonify({"error": "Internal server error"}), 500

# Cleanup task to remove expired files
def cleanup_expired_files():
    """Periodically clean up expired files"""
    while True:
        try:
            now = time.time()
            
            # Check all files in downloads directory
            for filename in os.listdir(DOWNLOADS_DIR):
                filepath = os.path.join(DOWNLOADS_DIR, filename)
                
                # Skip directories
                if os.path.isdir(filepath):
                    continue
                
                # Check if file is older than MAX_FILE_AGE
                file_age = now - os.path.getmtime(filepath)
                if file_age > MAX_FILE_AGE + 30:  # Add 30 seconds buffer
                    try:
                        os.remove(filepath)
                        logger.info(f"Cleaned up expired file: {filename}")
                    except Exception as e:
                        logger.error(f"Error deleting expired file {filename}: {str(e)}")
            
            # Also clean up metadata files
            for filename in os.listdir(METADATA_DIR):
                if not filename.endswith('.json'):
                    continue
                
                filepath = os.path.join(METADATA_DIR, filename)
                file_age = now - os.path.getmtime(filepath)
                
                if file_age > MAX_FILE_AGE + 60:  # Add 60 seconds buffer
                    try:
                        os.remove(filepath)
                    except Exception as e:
                        logger.error(f"Error deleting metadata file {filename}: {str(e)}")
        
        except Exception as e:
            logger.error(f"Error in cleanup task: {str(e)}")
        
        # Sleep for 5 minutes
        time.sleep(300)

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_expired_files, daemon=True)
cleanup_thread.start()

if __name__ == "__main__":
    logger.info("Starting YouTube Audio Downloader API")
    app.run(debug=True, threaded=True)
