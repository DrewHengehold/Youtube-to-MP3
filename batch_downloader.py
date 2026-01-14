import csv
import os
import re
import concurrent.futures
import sys
from converter import download_as_mp3

CSV_FILE = 'playlist.csv'
OUTPUT_FOLDER = 'ipod touch'
MAX_WORKERS = 5

def sanitize_filename(name):
    # Remove invalid characters for filenames
    return re.sub(r'[\\/*?:"<>|]', "", name)

def process_song(row):
    song_name = row.get('Song Name')
    artist = row.get('Artist')
    album = row.get('Album')
    youtube_link = row.get('Youtube Link')
    
    if not youtube_link:
        print(f"Skipping '{song_name}': No YouTube link provided.")
        return

    # Create filename: "Song Name - Artist"
    # Ensure variables are strings
    safe_song = sanitize_filename(song_name or "Unknown")
    safe_artist = sanitize_filename(artist or "Unknown")
    
    filename = f"{safe_song} - {safe_artist}"
    
    # Check if file exists (converter pads with .mp3)
    # We anticipate the final filename to be filename + ".mp3"
    expected_file_path = os.path.join(OUTPUT_FOLDER, f"{filename}.mp3")
    if os.path.exists(expected_file_path):
        print(f"Skipping: {filename} (Already exists)")
        return

    print(f"Processing: {filename}...")
    
    success = download_as_mp3(
        url=youtube_link,
        output_folder=OUTPUT_FOLDER,
        filename=filename,
        title=song_name,
        artist=artist,
        album=album
    )
    
    if success:
        print(f"Finished: {filename}")
    else:
        print(f"Failed: {filename}")

def main():
    if not os.path.exists(CSV_FILE):
        print(f"Error: {CSV_FILE} not found.")
        sys.exit(1)
        
    rows = []
    try:
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        sys.exit(1)
        
    print(f"Starting batch download for {len(rows)} songs with {MAX_WORKERS} threads...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        executor.map(process_song, rows)
        
    print("Batch download complete!")

if __name__ == "__main__":
    main()
