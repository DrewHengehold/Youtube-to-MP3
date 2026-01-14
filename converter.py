import yt_dlp
import os
import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()

def download_as_mp3(url, output_folder=".", filename=None, title=None, artist=None, album=None):
    # Ensure output folder exists
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Configuration options for yt-dlp
    ydl_opts = {
        'format': 'bestaudio/best',  # Get the best audio quality
        'outtmpl': os.path.join(output_folder, f"{filename}.%(ext)s") if filename else os.path.join(output_folder, '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192', # You can change this to 320 for higher quality
        }],
        'quiet': True,
        'no_warnings': True,
    }

    # Prepare ffmpeg arguments for metadata
    postprocessor_args = []
    if title:
        postprocessor_args.extend(['-metadata', f'title={title}'])
    if artist:
        postprocessor_args.extend(['-metadata', f'artist={artist}'])
    if album:
        postprocessor_args.extend(['-metadata', f'album={album}'])
    
    if postprocessor_args:
        ydl_opts['postprocessor_args'] = postprocessor_args

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # print(f"Starting download: {url}") # Suppressed for batch clean output
            ydl.download([url])
            # print("Successfully converted to MP3!")
            return True
    except Exception as e:
        print(f"An error occurred downloading {url}: {e}")
        return False

if __name__ == "__main__":
    link = input("Enter the YouTube URL: ")
    download_as_mp3(link)