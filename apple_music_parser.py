import csv
import sys
import os
from bs4 import BeautifulSoup

def parse_apple_music_playlist(html_file, output_csv):
    """
    Parses an Apple Music playlist HTML file and exports it to CSV.
    """
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
    except FileNotFoundError:
        print(f"Error: File '{html_file}' not found.")
        sys.exit(1)

    # Read existing songs to prevent duplicates
    existing_songs = set()
    if os.path.exists(output_csv):
        try:
            with open(output_csv, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Create a tuple of (Song Name, Artist) for uniqueness
                    # Handle potential missing keys if CSV is malformed
                    if 'Song Name' in row and 'Artist' in row:
                        existing_songs.add((row['Song Name'], row['Artist']))
        except Exception as e:
            print(f"Warning: Could not read existing CSV: {e}")

    # Find all song rows
    song_rows = soup.find_all('div', class_='songs-list-row')

    extracted_data = []

    for row in song_rows:
        try:
            # Song Name
            title_div = row.find('div', {'data-testid': 'track-title'})
            song_name = title_div.get_text(strip=True) if title_div else "Unknown Title"

            # Artist
            # The artist is often in a specific div, sometimes with links
            artist_div = row.find('div', {'data-testid': 'track-title-by-line'})
            artist = artist_div.get_text(strip=True) if artist_div else "Unknown Artist"

            # Check for duplicates (both in file and in current batch)
            if (song_name, artist) in existing_songs:
                continue
            
            # Add to set so we don't add duplicate in the same run
            existing_songs.add((song_name, artist))

            # Album
            album_div = row.find('div', {'data-testid': 'track-column-tertiary'})
            album = album_div.get_text(strip=True) if album_div else "Unknown Album"

            # Duration
            duration_time = row.find('time', {'data-testid': 'track-duration'})
            duration = duration_time.get_text(strip=True) if duration_time else "Unknown Duration"

            extracted_data.append([song_name, artist, album, duration, ""]) # Empty string for Youtube Link
        except Exception as e:
            print(f"Warning: Error parsing a row: {e}")
            continue

    if not extracted_data:
        print("No new songs found.")
        return

    # Write to CSV
    try:
        # Check if file is empty or new to decide on writing headers
        write_header = not os.path.exists(output_csv) or os.stat(output_csv).st_size == 0
        
        with open(output_csv, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            if write_header:
                writer.writerow(["Song Name", "Artist", "Album", "Duration", "Youtube Link"])
            writer.writerows(extracted_data)
        print(f"Successfully added {len(extracted_data)} new songs to '{output_csv}'.")
    except Exception as e:
        print(f"Error writing to CSV: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python apple_music_parser.py <html_file> [output_csv]")
        sys.exit(1)
    
    input_html = sys.argv[1]
    output_csv = sys.argv[2] if len(sys.argv) > 2 else "playlist.csv"

    parse_apple_music_playlist(input_html, output_csv)
