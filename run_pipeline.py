import apple_music_parser
import youtube_linker
import batch_downloader
import sys
import os

def main():
    print("=== Apple Music to MP3 Pipeline ===")
    
    # Configuration
    INPUT_HTML = "dummy_playlist.html"
    OUTPUT_CSV = "playlist.csv"
    
    # 1. Parse HTML and merge to CSV
    print(f"\n[1/4] Parsing '{INPUT_HTML}'...")
    if not os.path.exists(INPUT_HTML):
        print(f"Error: '{INPUT_HTML}' not found. Please save your playlist HTML to this file.")
        sys.exit(1)
        
    apple_music_parser.parse_apple_music_playlist(INPUT_HTML, OUTPUT_CSV)
    
    # 2. Find YouTube Links for new entries
    print(f"\n[2/4] Linking YouTube videos...")
    youtube_linker.process_csv(OUTPUT_CSV)
    
    # 3. User Verification
    print(f"\n[3/4] Verification")
    print("="*60)
    print(f"Please inspect '{OUTPUT_CSV}' to ensure the YouTube links are correct.")
    print("You can edit the file now if needed.")
    print("="*60)
    
    try:
        input("Press Enter to continue to download (or Ctrl+C to abort)...")
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(0)
    
    # 4. Batch Download
    print(f"\n[4/4] Downloading songs...")
    # Clean sys.argv arguments so batch_downloader doesn't get confused if we passed any to this script
    # batch_downloader uses hardcoded paths which is fine for this pipeline
    batch_downloader.main()
    
    print("\n=== Pipeline Complete ===")

if __name__ == "__main__":
    main()
