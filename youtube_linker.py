import csv
import sys
import subprocess
import json
import os

def parse_duration_to_seconds(duration_str):
    """Parses duration string (e.g., '3:46', '1:03:46') to seconds."""
    if not duration_str:
        return 0
    parts = duration_str.split(':')
    seconds = 0
    try:
        if len(parts) == 2: # MM:SS
            seconds = int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3: # HH:MM:SS
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        pass
    return seconds

def search_youtube(song_name, artist_name, target_duration):
    """
    Searches YouTube for the song matches and returns the best matching URL.
    """
    if artist_name and artist_name != "Unknown Artist":
        query = f"{song_name} {artist_name} audio"
    else:
        query = f"{song_name} audio"

    cmd = [
        'yt-dlp',
        '--print-json',
        '--flat-playlist',
        '--match-filter', '!is_live', 
        'ytsearch5:' + query
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error searching for '{song_name}': {e}")
        return ""

    best_match_url = ""
    min_duration_diff = float('inf')

    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        try:
            video_data = json.loads(line)
            video_duration = video_data.get('duration')
            video_url = video_data.get('url') # yt-dlp usually returns just ID for flat playlist, but sometimes full URL or needs construction.
            video_id = video_data.get('id')
            
            if video_duration is None:
                continue
            
            # Construct URL if necessary
            if video_url and "youtube.com" not in video_url and "youtu.be" not in video_url:
                 video_url = f"https://www.youtube.com/watch?v={video_id}"
            elif not video_url:
                 video_url = f"https://www.youtube.com/watch?v={video_id}"

            diff = abs(video_duration - target_duration)
            
            if diff < min_duration_diff:
                min_duration_diff = diff
                best_match_url = video_url

        except json.JSONDecodeError:
            continue
            
    return best_match_url

def process_csv(input_csv):
    """Reads CSV, populates YouTube links, and saves back to the same file."""
    
    rows = []
    try:
        with open(input_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)
    except FileNotFoundError:
        print(f"Error: File '{input_csv}' not found.")
        return

    total_songs = len(rows)
    print(f"Processing {total_songs} songs...")

    updated = False
    for i, row in enumerate(rows):
        song_name = row.get('Song Name')
        artist = row.get('Artist')
        duration_str = row.get('Duration')
        current_link = row.get('Youtube Link')

        if not song_name:
            continue

        if current_link: # Skip already populated
            print(f"[{i+1}/{total_songs}] Skipping '{song_name}' (already has link)")
            continue
        
        target_seconds = parse_duration_to_seconds(duration_str)
        if target_seconds == 0:
            print(f"[{i+1}/{total_songs}] Skipping '{song_name}' (invalid duration)")
            continue

        print(f"[{i+1}/{total_songs}] Searching for '{song_name}' ({duration_str})...")
        best_url = search_youtube(song_name, artist, target_seconds)
        
        if best_url:
            row['Youtube Link'] = best_url
            updated = True
            print(f"  -> Found: {best_url}")
        else:
            print(f"  -> No suitable match found.")
            
        # Save progress incrementally or batch?
        # For safety, let's just write at the end, but maybe we should write every match?
        # Let's write at the end for simplicity, but if it crashes we lose progress. 
        # Given 47 songs, it might take a few minutes. 
        
    if updated:
        try:
            with open(input_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            print(f"Successfully updated '{input_csv}'.")
        except Exception as e:
            print(f"Error writing to CSV: {e}")
    else:
        print("No updates made.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python youtube_linker.py <playlist_csv>")
        sys.exit(1)
    
    csv_file = sys.argv[1]
    process_csv(csv_file)
